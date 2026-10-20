import copy,tempfile,unittest
from decimal import Decimal
from pathlib import Path
from test_engine import Backend
from test_business import expense
from qianji_agent.engine import Engine,snapshot_digest
from qianji_agent.transport import QianjiError
from qianji_agent.journal import Journal
from qianji_agent.models import Receipt
from qianji_agent.codec import loads
from qianji_agent.operations import make_row


class DispatchEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)/'journal';self.backend=Backend()
  self.engine=Engine(self.backend,'123',self.root)
 def evidence(self,engine=None):
  journal=(engine or self.engine).journal
  self.assertTrue(callable(getattr(journal,'dispatch_evidence',None)),'Persist the actual financial dispatch outcome')
  return journal.dispatch_evidence('original')
 def fail_first_verification_read(self):
  original=self.engine.snapshot;calls=[0]
  def snapshot(*a,**k):
   calls[0]+=1
   if calls[0]>1:raise QianjiError('read_unavailable')
   return original(*a,**k)
  self.engine.snapshot=snapshot
 def test_success_response_persists_privately_and_scrubs_credentials(self):
  write=self.backend.write
  def acknowledged(*a):
   write(*a)
   return {'native_result':'private-financial-reply','utoken':'private-login','Tok':'private-protocol-auth',
           'nested':{'Authorization':'private-login','t_o_k':'private-protocol-auth','task_id':'native-task'}}
  self.backend.write=acknowledged
  receipt=self.engine.execute('original',expense())
  self.assertEqual(receipt['state'],'verified')
  evidence=self.evidence(Engine(self.backend,'123',self.root))
  self.assertEqual(evidence['outcome'],'response_received')
  self.assertEqual(evidence['response']['native_result'],'private-financial-reply')
  self.assertNotIn('private-login',str(evidence));self.assertNotIn('private-protocol-auth',str(evidence));self.assertNotIn('private-financial',str(receipt))
  self.assertEqual(self.backend.writes,1)
 def test_acknowledgement_alone_never_proves_execution(self):
  def ack(*a):self.backend.writes+=1;return {'accepted':True}
  self.backend.write=ack
  receipt=self.engine.execute('original',expense())
  self.assertEqual(receipt['state'],'pending_verification')
  self.assertEqual(receipt.get('dispatch_state'),'response_received')
  self.assertEqual(receipt.get('verification_code'),'balance_not_verified')
  self.assertEqual(self.engine.operation('original')['state'],'pending_verification')
  self.assertEqual(self.engine.execute('another',expense())['code'],'previous_result_unknown')
  self.assertEqual(self.backend.writes,1)
 def test_known_rejection_survives_restart_and_no_effect_read_recovers(self):
  def rejected(*a):self.backend.writes+=1;raise QianjiError('feature_unavailable')
  self.backend.write=rejected;self.fail_first_verification_read()
  self.assertEqual(self.engine.execute('original',expense())['state'],'pending_verification')
  restored=Engine(self.backend,'123',self.root)
  self.assertEqual(self.evidence(restored)['error_code'],'feature_unavailable')
  result=restored.operation('original')
  self.assertEqual(result['state'],'failed')
  self.assertEqual(result['code'],'backend_rejected_no_effect_verified')
  self.assertEqual(self.backend.writes,1)
 def test_known_rejection_cannot_clear_if_snapshot_changed(self):
  def rejected(*a):self.backend.writes+=1;raise QianjiError('feature_unavailable')
  self.backend.write=rejected;self.fail_first_verification_read()
  self.engine.execute('original',expense());self.backend.data['assets'][1]['name']='external change'
  self.assertEqual(Engine(self.backend,'123',self.root).operation('original')['state'],'pending_verification')
 def test_unknown_backend_error_is_not_a_proven_rejection(self):
  def rejected(*a):self.backend.writes+=1;raise QianjiError('backend_result_unknown')
  self.backend.write=rejected;self.engine.execute('original',expense())
  restored=Engine(self.backend,'123',self.root)
  self.assertEqual(restored.operation('original')['state'],'pending_verification')
  self.assertEqual(self.evidence(restored)['outcome'],'backend_error')
  self.assertEqual(self.backend.writes,1)
 def test_timeout_keeps_unknown_without_private_exception_text(self):
  def lost(*a):self.backend.writes+=1;raise TimeoutError('private-token exception')
  self.backend.write=lost;receipt=self.engine.execute('original',expense())
  self.assertEqual(receipt['state'],'pending_verification')
  evidence=self.evidence();self.assertEqual(evidence['outcome'],'transport_unknown')
  self.assertEqual(evidence['exception_type'],'TimeoutError')
  self.assertNotIn('private-token',str(evidence));self.assertNotIn('private-token',str(receipt))
 def test_legacy_missing_evidence_is_not_backfilled_or_cleared(self):
  before=self.engine.snapshot();plan=self.engine.prepare(expense(),before)
  plan.update(extended=False,owner='123',before_digest=snapshot_digest(before))
  with self.engine.journal.lock():self.engine.journal.start('original','legacy-hash',plan)
  receipt=self.engine.operation('original')
  self.assertEqual(receipt['state'],'pending_verification')
  self.assertEqual(receipt.get('dispatch_state'),'not_recorded')
  self.assertEqual(receipt.get('verification_code'),'balance_not_verified')
  self.assertIsNone(self.evidence());self.assertEqual(self.backend.writes,0)
 def test_legacy_installment_missing_object_keeps_original_unknown(self):
  self.backend.data['assets'][0].update(type=2,stype=21)
  before=self.engine.snapshot(True)
  cmd={'action':'installment_create','name':'Old plan','account_id':'10','category_id':'20',
       'amount':'3648.00','periods':24,'fee':'0.00','time':'2026-09-13T22:16:00+08:00'}
  plan=self.engine.prepare(cmd,before);plan.update(extended=True,owner='123',before_digest=snapshot_digest(before))
  with self.engine.journal.lock():self.engine.journal.start('original','legacy-plan',plan)
  receipt=self.engine.operation('original')
  self.assertEqual(receipt['state'],'pending_verification');self.assertEqual(receipt['verification_code'],'object_not_verified')
  self.assertEqual(receipt['dispatch_state'],'not_recorded');self.assertIsNone(self.evidence())
  self.assertEqual(self.backend.writes,0)
 def test_evidence_recording_failure_after_effect_cannot_claim_not_executed(self):
  def fail(*a):raise OSError('private-disk-error')
  self.engine.journal.record_dispatch=fail
  result=self.engine.execute('original',expense())
  self.assertEqual(result['state'],'pending_verification')
  self.assertEqual(Engine(self.backend,'123',self.root).operation('original')['state'],'verified')
  self.assertEqual(self.backend.writes,1)
 def test_recorded_evidence_is_append_only_and_requires_original(self):
  self.assertTrue(callable(getattr(self.engine.journal,'record_dispatch',None)))
  with self.engine.journal.lock():
   with self.assertRaises(ValueError):self.engine.journal.record_dispatch('missing',{'outcome':'response_received','response':{}})
   self.engine.journal.start('original','h',{'collection':'bills'})
   self.engine.journal.record_dispatch('original',{'outcome':'response_received','response':{}})
   with self.assertRaises(ValueError):self.engine.journal.record_dispatch('original',{'outcome':'backend_error','error_code':'feature_unavailable'})
  self.assertEqual(self.evidence()['outcome'],'response_received')
 def test_public_receipt_accepts_only_redacted_diagnostic_fields(self):
  self.assertTrue('dispatch_state' in Receipt.model_fields)
  value=Receipt(state='pending_verification',dispatch_state='not_recorded',verification_code='object_not_verified')
  self.assertEqual(value.dispatch_state,'not_recorded')
  with self.assertRaises(ValueError):Receipt(state='pending_verification',dispatch_state='private-login')
 def test_unreadable_evidence_does_not_claim_absence_or_clear_unknown(self):
  def rejected(*a):self.backend.writes+=1;raise QianjiError('feature_unavailable')
  self.backend.write=rejected
  def unavailable(*a):raise OSError('private-disk-path')
  self.engine.journal.dispatch_evidence=unavailable
  result=self.engine.execute('original',expense())
  self.assertEqual(result['state'],'pending_verification')
  self.assertEqual(result['dispatch_state'],'unavailable')
  self.assertNotIn('private-disk-path',str(result))
 def test_backend_error_details_are_retained_only_in_private_evidence(self):
  def rejected(*a):raise QianjiError('backend_result_unknown',{'ec':8888,'em':'private-native-error'})
  self.backend.write=rejected;result=self.engine.execute('original',expense())
  self.assertEqual(self.evidence()['response'],{'ec':8888,'em':'private-native-error'})
  self.assertNotIn('private-native-error',str(result));self.assertEqual(result['state'],'pending_verification')
 def test_late_native_success_wins_over_rejection_label_without_resend(self):
  write=self.backend.write
  def ambiguous(*a):write(*a);raise QianjiError('feature_unavailable')
  self.backend.write=ambiguous;self.fail_first_verification_read()
  self.assertEqual(self.engine.execute('original',expense())['state'],'pending_verification')
  self.assertEqual(Engine(self.backend,'123',self.root).operation('original')['state'],'verified')
  self.assertEqual(self.backend.writes,1)
 def test_unrecognized_verifier_exception_never_exposes_private_text(self):
  def private_error(*a):raise ValueError('private-native-id token message')
  self.engine.verify=private_error;result=self.engine.execute('original',expense())
  self.assertEqual(result['state'],'pending_verification');self.assertEqual(result['verification_code'],'verification_incomplete')
  self.assertNotIn('private-native-id',str(result));self.assertEqual(self.backend.writes,1)
 def test_legacy_database_migration_preserves_operations_and_never_dispatches(self):
  before=self.engine.snapshot();plan=self.engine.prepare(expense(),before);plan.update(extended=False,owner='123',before_digest=snapshot_digest(before))
  with self.engine.journal.lock(),self.engine.journal.db() as db:
   self.engine.journal.start('original','old-hash',plan)
   db.execute('DROP TABLE dispatch_evidence')
  restored=Engine(self.backend,'123',self.root)
  self.assertEqual(restored.journal.get('original')['hash'],'old-hash')
  self.assertEqual(restored.operation('original')['state'],'pending_verification')
  self.assertIsNone(restored.journal.dispatch_evidence('original'));self.assertEqual(self.backend.writes,0)
 def test_real_installment_verifier_failures_keep_specific_public_category(self):
  self.backend.data['assets'][0].update(type=2,stype=21)
  before=self.engine.snapshot(True)
  cmd={'action':'installment_create','name':'Plan','account_id':'10','category_id':'20',
       'amount':'0.05','periods':2,'time':'2026-10-18T00:00:00+08:00'}
  plan=self.engine.prepare(cmd,before);plan.update(extended=True,owner='123',before_digest=snapshot_digest(before))
  task=loads(plan['params']['v']);task.update(id=30,type=1,count=1,packid=300,money=Decimal('0.02'),fee=Decimal('0.00'))
  child=make_row('123','1','100',task['starttime'],0);child.update(money=Decimal('0.03'),assetid=10,cateid=20,packid=300)
  after=copy.deepcopy(before);after.update(installment=[task],bills=[child]);after['assets'][0]['money']-=Decimal('0.03')
  original_read=self.backend.read
  def read(route,params):
   if route=='installment/list':return {'list':copy.deepcopy(self.backend.data['installment'])}
   return original_read(route,params)
  self.backend.read=read
  for case,want in [('data','task_data_not_verified'),('remaining','installment_remaining_not_verified'),
                    ('relation','installment_child_relation_not_verified'),('balance','task_balance_not_verified')]:
   self.backend.data=copy.deepcopy(after)
   if case=='data':self.backend.data['installment'][0]['data']['lefttype']='last'
   elif case=='remaining':self.backend.data['installment'][0]['money']=Decimal('0.99')
   elif case=='relation':self.backend.data['bills'][0]['cateid']=21
   else:self.backend.data['assets'][0]['money']-=Decimal('0.01')
   request='original-'+case
   with self.engine.journal.lock():self.engine.journal.start(request,'old-'+case,plan)
   with self.subTest(case=case):
    result=self.engine.operation(request)
    self.assertEqual(result['state'],'pending_verification');self.assertEqual(result['verification_code'],want)
  self.assertEqual(self.backend.writes,0)
 def test_real_repeat_clock_failure_keeps_its_specific_category(self):
  before=self.engine.snapshot(True)
  cmd={'action':'repeat_create','book_id':'1','account_id':'10','category_id':'20',
       'amount':'0.10','start_date':'2026-10-18','clock':'08:00','end_count':2}
  plan=self.engine.prepare(cmd,before);plan.update(extended=True,owner='123',before_digest=snapshot_digest(before))
  task=loads(plan['params']['v']);task.update(id=30,packid=300,status=1,count=0);task['data']['time']='09:00'
  original_read=self.backend.read
  self.backend.read=lambda route,params:{'list':[task]} if route=='repeat_task/list' else original_read(route,params)
  with self.engine.journal.lock():self.engine.journal.start('original','old-clock',plan)
  result=self.engine.operation('original');self.assertEqual(result['state'],'pending_verification')
  self.assertEqual(result['verification_code'],'task_clock_not_verified');self.assertEqual(self.backend.writes,0)


class TransportDispatchEvidenceTests(unittest.TestCase):
 def test_transport_timeout_retains_finite_exception_kind_only(self):
  from unittest.mock import patch
  from qianji_agent.auth import Session
  from qianji_agent.transport import Transport
  from qianji_agent.dispatch import dispatch_error
  class Opener:
   def open(self,*a,**k):raise TimeoutError('private-session timeout details')
  with patch('qianji_agent.transport.urllib.request.build_opener',return_value=Opener()):
   with self.assertRaises(QianjiError) as error:Transport(Session('123',{},('a','b','c'),'1580')).write('installment/submit',{'v':'{}'})
  proof=dispatch_error(error.exception)
  self.assertEqual(proof['exception_type'],'TimeoutError');self.assertEqual(proof['outcome'],'transport_unknown')
  self.assertNotIn('private-session',str(proof))
 def test_native_error_reply_survives_without_changing_public_exception(self):
  import io,json
  from unittest.mock import patch
  from qianji_agent.auth import Session
  from qianji_agent.transport import Transport
  class Reply(io.BytesIO):status=200
  class Opener:
   def open(self,*a,**k):return Reply(json.dumps({'ec':8888,'em':'private-native-error'}).encode())
  with patch('qianji_agent.transport.urllib.request.build_opener',return_value=Opener()):
   with self.assertRaises(QianjiError) as error:Transport(Session('123',{},('a','b','c'),'1580')).write('installment/submit',{'v':'{}'})
  self.assertEqual(str(error.exception),'backend_result_unknown')
  self.assertEqual(getattr(error.exception,'response',None),{'ec':8888,'em':'private-native-error'})

