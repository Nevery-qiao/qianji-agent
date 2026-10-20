import tempfile,unittest,copy
from pathlib import Path
from unittest.mock import patch
from test_engine import Backend
from test_business import expense
from qianji_agent.engine import Engine
from qianji_agent.codec import loads

class AccountBackend(Backend):
 def write(self,route,params):
  self.writes+=1;row=loads(loads(params['v'])['bills']['changelist'])[0];self.data['bills'].append(row)
  account=next(a for a in self.data['assets'] if a['id']==row['assetid']);account['money']+=row['money'] if row['type']==1 else -row['money']
  if self.lose:self.fail_read=True;raise TimeoutError('private-token')
  return {}

class RecoveryIntegrationTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.b=AccountBackend();self.e=Engine(self.b,'123',Path(self.t.name)/'state')
 def unknown(self,rid='old'):
  self.b.lose=True;r=self.e.execute(rid,expense());self.assertEqual(r['state'],'pending_verification');self.b.lose=False;self.b.fail_read=False
 def test_engine_exposes_persistent_recovery_and_requires_final_ack(self):
  self.assertTrue(hasattr(self.e,'recovery_list'),'Generic recovery entry points required')
  self.unknown();r=self.e.recovery_list();self.assertEqual(r['total'],1)
  self.assertEqual(self.e.operation('old')['state'],'verified');item=self.e.recovery_list()['records'][0]
  self.assertEqual(item['phase'],'awaiting_ack');self.assertEqual(self.b.writes,1)
  ack=self.e.recovery_ack('old',item['version'],'recorded','ledger:one');self.assertEqual(ack['state'],'acknowledged');self.assertEqual(self.e.recovery_list()['total'],0)
 def test_same_account_pending_still_blocks_new_financial_write(self):
  self.unknown();r=self.e.execute('new',expense());self.assertEqual(r['code'],'previous_result_unknown');self.assertEqual(self.b.writes,1)
 def test_different_account_plain_bill_does_not_destroy_original_verification(self):
  self.unknown();plan=copy.deepcopy(self.e.journal.get('old')['plan'])
  r=self.e.execute('independent',expense(account_id='11'));self.assertEqual(r['state'],'verified');self.assertEqual(self.b.writes,2)
  self.assertEqual(self.e.operation('old')['state'],'verified');self.assertEqual(self.b.writes,2);self.assertEqual(self.e.journal.get('old')['plan'],plan)
 def test_complex_pending_dependency_is_not_treated_as_independent(self):
  with self.e.journal.lock():self.e.journal.start('task','h',{'action':'installment_create','collection':'installment','balances':{'10':'0.90'}})
  r=self.e.execute('new',expense(account_id='11'));self.assertEqual(r['code'],'previous_result_unknown');self.assertEqual(self.b.writes,0)
 def test_all_pending_dependencies_are_checked_not_only_first(self):
  self.unknown('one');self.b.lose=True
  self.assertEqual(self.e.execute('two',expense(account_id='11'))['state'],'pending_verification')
  self.b.lose=False;self.b.fail_read=False
  r=self.e.execute('three',expense(account_id='11'));self.assertEqual(r['code'],'previous_result_unknown');self.assertEqual(self.b.writes,2)
 def test_known_rejection_with_full_snapshot_recovery_dependency_blocks_isolation(self):
  from qianji_agent.dispatch import dispatch_error
  from qianji_agent.transport import QianjiError
  plan=self.e.prepare(expense(),self.e.snapshot());plan.update(owner='123',extended=False)
  with self.e.journal.lock():
   self.e.journal.start('rejected','h',plan);self.e.journal.record_dispatch('rejected',dispatch_error(QianjiError('backend_rejected')))
  r=self.e.execute('new',expense(account_id='11'));self.assertEqual(r['code'],'previous_result_unknown');self.assertEqual(self.b.writes,0)
 def test_account_with_complex_credit_state_is_not_cash_isolation(self):
  self.unknown();self.b.data['assets'][1].update(type=3,credit={'shareid':'10'})
  r=self.e.execute('new',expense(account_id='11'));self.assertEqual(r['state'],'not_executed');self.assertEqual(r['code'],'previous_result_unknown');self.assertEqual(self.b.writes,1)
  self.assertTrue(any(h['account_id']=='11' and h['reason']=='account_drift_unexplained' for h in self.e.journal.active_halts()))
 def test_plain_plan_without_old_scope_annotation_can_recover_complete_scope(self):
  plan=self.e.prepare(expense(),self.e.snapshot())
  with self.e.journal.lock():self.e.journal.start('legacy','h',plan)
  original=copy.deepcopy(self.e.journal.get('legacy'))
  r=self.e.execute('new',expense(account_id='11'));self.assertEqual(r['state'],'verified');self.assertEqual(self.b.writes,1)
  self.assertEqual(self.e.journal.get('legacy'),original)
 def test_same_process_status_after_missing_finish_preserves_external_completion(self):
  finish=self.e.journal.finish;calls=[0]
  def once(*args,**kwargs):
   calls[0]+=1
   if calls[0]==1:raise OSError('disk unavailable')
   return finish(*args,**kwargs)
  self.e.journal.finish=once;self.assertEqual(self.e.execute('old',expense())['state'],'pending_verification')
  self.assertEqual(self.e.operation('old')['state'],'verified');self.assertEqual(self.e.recovery_list()['recovery']['awaiting_ack'],1);self.assertEqual(self.b.writes,1)
 def test_duplicate_execute_recovery_after_missing_finish_also_needs_ack(self):
  finish=self.e.journal.finish;calls=[0]
  def once(*args,**kwargs):
   calls[0]+=1
   if calls[0]==1:raise OSError('disk unavailable')
   return finish(*args,**kwargs)
  self.e.journal.finish=once;self.e.execute('old',expense())
  self.assertEqual(self.e.execute('old',expense())['state'],'verified');self.assertEqual(self.e.recovery_list()['recovery']['awaiting_ack'],1);self.assertEqual(self.b.writes,1)
 def test_legacy_pending_reconciled_before_discovery_still_needs_ack(self):
  from qianji_agent.codec import dumps,digest
  plan=self.e.prepare(expense(),self.e.snapshot());plan.update(owner='123',extended=False);self.b.write(plan['route'],plan['params'])
  with self.e.journal.db() as c:c.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',('old',digest(expense()),'pending_verification',dumps(plan),None,1000))
  self.assertEqual(self.e.operation('old')['state'],'verified');self.assertEqual(self.e.recovery_list()['recovery']['awaiting_ack'],1)
 def test_verification_budget_is_reserved_before_native_reads_when_finish_fails(self):
  self.unknown()
  def fail(*args,**kwargs):raise OSError('disk unavailable')
  self.e.journal.finish=fail;created=self.e.recovery_list()['records'][0]['created_at']
  for offset in [60,360,2160,5000]:
   with patch('qianji_agent.recovery.time.time',return_value=created+offset):
    try:self.e.operation('old',automatic=True)
    except OSError:pass
  row=self.e.recovery_list()['records'][0];self.assertEqual(row['checks'],3);self.assertEqual(row['phase'],'needs_attention');self.assertEqual(self.b.writes,1)
 def test_visible_new_refund_relation_prevents_plain_account_isolation(self):
  from decimal import Decimal
  self.unknown();original=self.b.data['bills'][0];child=copy.deepcopy(original);child.update(id=original['id']+1,type=20,assetid=11,money=Decimal('0.01'),extra={'refundsid':original['id']})
  original['extra']={**(original.get('extra') or {}),'rfds':{str(child['id']):Decimal('0.01')}};self.b.data['bills'].append(child);self.b.data['assets'][1]['money']+=Decimal('0.01')
  result=self.e.execute('new',expense(account_id='11'));self.assertEqual(result['state'],'not_executed');self.assertEqual(self.b.writes,1)
 def test_credit_type_with_missing_details_is_not_plain_cash(self):
  self.unknown();self.b.data['assets'][1].update(type=2,stype=200,credit=None)
  result=self.e.execute('new',expense(account_id='11'));self.assertEqual(result['state'],'not_executed');self.assertEqual(self.b.writes,1)
 def test_native_money_scale_does_not_falsely_create_a_linked_dependency(self):
  from decimal import Decimal
  self.unknown();self.b.data['bills'][0]['money']=Decimal('0.100')
  result=self.e.execute('new',expense(account_id='11'));self.assertEqual(result['state'],'verified');self.assertEqual(self.b.writes,2)
 def test_lost_successful_mcp_response_is_found_by_next_agent_and_not_redispatched(self):
  self.e.execute('lost-delivery',expense())
  next_agent=Engine(self.b,'123',self.e.journal.root);r=next_agent.recovery_list()
  self.assertEqual(r['total'],1);self.assertEqual(r['records'][0]['phase'],'awaiting_ack')
  self.assertEqual(next_agent.execute('lost-delivery',expense())['state'],'verified');self.assertEqual(self.b.writes,1)
 def test_automatic_review_obeys_due_time_and_exhausted_budget(self):
  self.assertTrue(hasattr(self.e,'recovery_list'),'Generic recovery entry points required')
  with patch('qianji_agent.recovery.time.time',return_value=1000):
   self.unknown();self.b.data['bills']=[];self.b.data['assets'][0]['money']+=__import__('decimal').Decimal('0.10')
   self.assertEqual(self.e.operation('old',automatic=True)['code'],'recovery_not_due')
  for now in [1060,1360,3160]:
   with patch('qianji_agent.recovery.time.time',return_value=now):self.assertEqual(self.e.operation('old',automatic=True)['state'],'pending_verification')
  with patch('qianji_agent.recovery.time.time',return_value=10000):self.assertEqual(self.e.operation('old',automatic=True)['code'],'recovery_requires_attention')
  self.assertEqual(self.b.writes,1)
