import unittest,tempfile,copy
from decimal import Decimal
from pathlib import Path
from test_business import snapshot,expense
try:from qianji_agent.engine import Engine
except ImportError:Engine=None

class Backend:
 def __init__(self):self.data=snapshot();self.uid='123';self.writes=0;self.lose=False;self.fail_read=False
 def read(self,route,params):
  if self.fail_read:raise ValueError('private-token backend exception')
  if route=='asset/typelist':return {'list':[{'name':'资金账户'},{'type':{'name':'微信','type':1,'stype':14,'icon':'http://res3.qianjiapp.com/assetv2/asset_icon_weixin.png','c':'6AB37A'}}]}
  if route=='book/list':return {'list':copy.deepcopy(self.data['books'])}
  if route=='asset/list':return {'list':copy.deepcopy([a for a in self.data['assets'] if a.get('status',0)==params.get('status',0)])}
  if route=='asset/listloan':return {'list':copy.deepcopy([a for a in self.data['assets'] if a.get('type')==5 and a.get('status')==params['status'] and a.get('stype')==params['t']])}
  if route=='category/listv2':return {'list':[copy.deepcopy(r) for r in self.data['categories'] if str(r['bookid'])==str(params['bookid'])]}
  if route=='syncv2/pull':return {'changes':copy.deepcopy(self.data['bills']),'deletes':self.data['deletes'],'categories':self.data['categories'],'hasmore':0}
  if route=='tag/list':return {'list':[]}
  if route in ('repeat_task/list','installment/list'):return {'list':[],'hasmore':0}
  raise ValueError('unexpected fake route')
 def write(self,route,params):
  from qianji_agent.codec import loads
  self.writes+=1
  if route!='bill/syncall':raise ValueError('unexpected fake write')
  b=loads(params['v'])['bills']
  if 'changelist' in b:
   row=loads(b['changelist'])[0]
   self.data['bills'].append(row);self.data['assets'][0]['money']-=row['money']
  if self.lose:raise TimeoutError('private-token lost-response')
  return {}

class EngineTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(Engine,'Shared product execution core required');self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.path=Path(self.t.name)/'state';self.b=Backend();self.e=Engine(self.b,'123',self.path)
 def test_preview_does_not_dispatch(self):
  r=self.e.preview(expense());self.assertEqual(r['state'],'preview');self.assertEqual(self.b.writes,0)
  self.assertNotIn('params',r);self.assertNotIn('userid',str(r))
 def test_verified_duplicate_reuses_receipt_no_write(self):
  r=self.e.execute('unique-1',expense());self.assertEqual(r['state'],'verified')
  self.assertEqual(r['object_id'],str(self.b.data['bills'][0]['id']))
  self.assertEqual(self.e.execute('unique-1',expense())['state'],'verified');self.assertEqual(self.b.writes,1)
  self.assertEqual(self.e.execute('unique-1',expense(amount='0.20'))['code'],'request_conflict')
 def test_lost_response_reconciles_without_resend(self):
  self.b.lose=True;r=self.e.execute('loss',expense());self.assertEqual(r['state'],'verified');self.assertEqual(self.b.writes,1)
 def test_crash_pending_blocks_new_requests_after_restart(self):
  self.b.lose=True
  original=self.e.snapshot
  calls=[0]
  def read_then_fail(*a,**kw):
   calls[0]+=1
   if calls[0]>1:raise ValueError('private-token')
   return original(*a,**kw)
  self.e.snapshot=read_then_fail
  r=self.e.execute('loss',expense());self.assertEqual(r['state'],'pending_verification')
  other=Engine(self.b,'123',self.path)
  self.assertEqual(other.execute('new',expense())['code'],'previous_result_unknown');self.assertEqual(self.b.writes,1)
  self.assertEqual(other.operation('loss')['state'],'verified');self.assertEqual(self.b.writes,1)
 def test_read_failure_never_echoes_private_exception(self):
  self.b.fail_read=True;r=self.e.query('books');self.assertNotIn('private-token',str(r));self.assertEqual(r['state'],'not_executed')
 def test_public_money_ids_and_filter(self):
  self.e.execute('a',expense());r=self.e.query('bills',{'book_id':'1','kind':'expense','limit':1})
  self.assertEqual(r['state'],'read');self.assertEqual(r['records'][0]['money'],'0.10')
  self.assertIsInstance(r['records'][0]['id'],str);self.assertNotIn('userid',r['records'][0]);self.assertIn('version',r['records'][0])
 def test_unrecognized_filter_refused_before_backend(self):
  self.assertEqual(self.e.query('books',{'utoken':'private-token'})['state'],'not_executed')
 def test_incomplete_sync_not_accepted(self):
  read=self.b.read
  def incomplete(route,params):
   d=read(route,params)
   if route=='syncv2/pull':d['hasmore']=1
   return d
  self.b.read=incomplete
  self.assertEqual(self.e.execute('a',expense())['state'],'not_executed');self.assertEqual(self.b.writes,0)

 def test_sync_categories_are_not_authoritative_for_every_book(self):
  read=self.b.read
  def sparse_sync(route,params):
   result=read(route,params)
   if route=='syncv2/pull':result['categories']=[]
   return result
  self.b.read=sparse_sync
  self.assertEqual(len(self.e.snapshot()['categories']),2)
 def test_journal_failure_after_effect_cannot_claim_not_executed(self):
  def fail(*a,**k):raise OSError('disk failure private-token')
  self.e.journal.finish=fail
  r=self.e.execute('disk',expense())
  self.assertEqual(r['state'],'pending_verification');self.assertEqual(self.b.writes,1)
  self.assertEqual(Engine(self.b,'123',self.path).operation('disk')['state'],'verified')
 def test_attachment_reference_from_verified_shared_journal_is_usable(self):
  with self.e.journal.lock():
   self.e.journal.start('upload','h',{'collection':'uploads'})
   self.e.journal.finish('upload',{'state':'verified','image_key':'a'*32})
  r=self.e.execute('image-bill',expense(image_keys=['a'*32]))
  self.assertEqual(r['state'],'verified');self.assertEqual(self.b.data['bills'][0]['images'],['a'*32])
 def test_native_rejection_without_effect_ignores_synthetic_tag_read_time(self):
  from qianji_agent.transport import QianjiError
  self.e._extended=lambda c:True
  read=self.b.read;tick=[0]
  def changing_metadata(route,params):
   r=read(route,params)
   if route=='tag/list':tick[0]+=1;r['list']=[{'id':'g','name':'Ungrouped','createtime':tick[0],'tags':[]}]
   return r
  def rejected(route,params):raise QianjiError('feature_unavailable')
  self.b.read=changing_metadata;self.b.write=rejected
  r=self.e.execute('rejected',expense());self.assertEqual(r['state'],'failed');self.assertIsNone(self.e.journal.unresolved())

 def test_account_templates_use_native_type_envelope_not_research_outline(self):
  result=self.e.preview({'action':'account_create','name':'Wallet','account_kind':'微信','amount':'0.00'})
  self.assertEqual(result['state'],'preview')
  r=self.e.query('account_types');self.assertEqual(r['records'][0]['name'],'微信');self.assertEqual(r['records'][0]['stype'],14)
 def test_non_cny_base_does_not_silently_use_cny_math(self):
  from types import SimpleNamespace
  self.b.session=SimpleNamespace(base_currency='USD')
  r=self.e.execute('non-cny',expense());self.assertEqual(r['state'],'not_executed');self.assertEqual(self.b.writes,0)
 def test_unknown_source_currency_not_accepted_without_catalogue_check(self):
  r=self.e.preview(expense(currency='ZZZ',account_amount='0.10',base_amount='0.10'))
  self.assertEqual(r['state'],'not_executed')
 def test_closed_debt_is_read_by_identity_for_native_record_maintenance(self):
  from qianji_agent.operations import make_row
  from qianji_agent.codec import digest
  debt={'id':12,'userid':'123','name':'Closed','type':5,'stype':51,'status':1,'money':Decimal('0.00'),'currency':'CNY'}
  self.b.data['assets'].append(debt)
  b=make_row('123','1','100',1792281600,9);b.update(money=Decimal('0.04'),assetid=12,fromid=10);self.b.data['bills']=[b]
  read=self.b.read
  def with_closed(route,params):
   if route=='asset/info':return dict(debt)
   r=read(route,params)
   if route=='asset/list':r['list']=[a for a in r['list'] if a.get('status')!=1]
   return r
  self.b.read=with_closed
  r=self.e.preview({'action':'bill_delete','object_id':'100','expected_version':digest(b)})
  self.assertEqual(r['state'],'preview');self.assertEqual(r['expected_balances']['12'],'-0.04')
  def delete_native(route,params):
   self.b.writes+=1;self.b.data['bills']=[];self.b.data['deletes']=[100];debt['money']=Decimal('-0.04');self.b.data['assets'][0]['money']+=Decimal('0.04');return {}
  self.b.write=delete_native
  result=self.e.execute('closed-delete',{'action':'bill_delete','object_id':'100','expected_version':digest(b)})
  self.assertEqual(result['state'],'verified');self.assertEqual(self.b.writes,1)
 def test_task_book_filter_reads_native_nested_data(self):
  read=self.b.read
  def tasks(route,params):
   if route=='repeat_task/list':return {'list':[{'id':30,'type':0,'data':{'bookid':1,'fromid':10,'cateid':20,'money':Decimal('0.01')},'userid':'123'}]}
   return read(route,params)
  self.b.read=tasks
  r=self.e.query('repeat',{'book_id':'1','account_id':'10','category_id':'20'})
  self.assertEqual(r['total'],1)
 def test_inapplicable_filters_are_explicitly_rejected(self):
  self.assertEqual(self.e.query('currencies',{'since':'2026-10-18T00:00:00+08:00'})['code'],'invalid_filter')
 def test_public_native_images_and_currency_values_are_typed(self):
  from qianji_agent.engine import public_row
  r=public_row({'id':100,'images':'["key"]','extra':{'curr':{'sv':1,'tv':Decimal('7.00'),'bv':7,'ss':'USD','ts':'CNY','bs':'CNY'}}})
  self.assertEqual(r['images'],['key']);self.assertEqual(r['extra']['curr']['sv'],'1');self.assertEqual(r['extra']['curr']['bv'],'7')
