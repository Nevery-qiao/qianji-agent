"""Breaks caught: wrong dependency branch, incomplete legacy scope and hidden credit links."""
import copy,unittest
from test_business import snapshot,expense
from qianji_agent.operations import prepare
from qianji_agent.linked import prepare_linked
from qianji_agent.codec import dumps,loads
try:
 from qianji_agent.continuation import classify_pending,decide
except ImportError:
 classify_pending=decide=None

class ContinuationScopeTests(unittest.TestCase):
 def setUp(self):
  self.assertTrue(callable(decide),'Missing complete pending-dependency decision')
  self.s=snapshot();self.policy={'version':'continuation-v1','historical_requests':['old']}
 def bill(self,account='10'):
  return {'request_id':'old','plan':prepare(expense(account_id=account),self.s,'123',bill_id='100'),'dispatch':None}
 def credit(self):
  self.s['assets'][0].update(type=2,credit={'limit':100,'shareid':-1})
 def installment(self):
  self.credit()
  p=prepare_linked({'action':'installment_create','name':'Old plan','account_id':'10','category_id':'20','amount':'3.00','periods':3,'time':'2026-10-18T08:00:00+08:00'},self.s,'123')
  return {'request_id':'old','plan':p,'dispatch':None}
 def decision(self,record,command=None,halts=None):
  return decide([record] if isinstance(record,dict) else record,command or expense(),self.s,self.policy,halts or [])
 def test_legacy_plain_without_independence_scope_uses_actual_plan(self):
  old=self.bill();before=copy.deepcopy(old)
  self.assertTrue(self.decision(old)['allowed']);self.assertEqual(old,before)
 def test_historical_installment_create_can_continue_same_independent_credit(self):
  old=self.installment();c=classify_pending(old,self.s)
  self.assertEqual(c['account_ids'],['10']);self.assertTrue(c['complete'])
  self.assertTrue(self.decision(old)['allowed'])
 def test_installment_conflicting_embedded_account_cannot_guess_scope(self):
  old=self.installment();v=loads(old['plan']['params']['v']);v['data']['asset']=dumps({**loads(v['data']['asset']),'id':11});old['plan']['params']['v']=dumps(v)
  self.assertEqual(self.decision(old)['code'],'dependency_scope_unknown')
 def test_missing_legacy_plan_scope_stops_every_account(self):
  old={'request_id':'old','plan':{'action':'installment_create','collection':'installment','balances':{'10':'0.90'}},'dispatch':None}
  self.assertEqual(self.decision(old,expense(account_id='11'))['code'],'dependency_scope_unknown')
 def test_new_pending_cannot_become_historical_by_new_request_or_income(self):
  old=self.bill();old['request_id']='new-unknown'
  for c in (expense(),expense(kind='income',category_id='21')):
   with self.subTest(c=c):self.assertFalse(self.decision(old,c)['allowed'])
 def test_new_pending_different_account_can_continue(self):
  old=self.bill();old['request_id']='new-unknown'
  self.assertTrue(self.decision(old,expense(account_id='11'))['allowed'])
 def test_every_pending_is_checked(self):
  old=self.bill();other=copy.deepcopy(old);other['request_id']='second';other['plan']={'action':'unknown_action','collection':'bills'}
  self.assertFalse(self.decision([old,other])['allowed'])
 def test_halt_is_account_scoped_and_direction_independent(self):
  old=self.bill()
  for c in (expense(),expense(kind='income',category_id='21')):
   self.assertEqual(self.decision(old,c,[{'account_id':'10','state':'active'}])['code'],'account_halted')
  self.assertTrue(self.decision(old,expense(account_id='11'),[{'account_id':'10','state':'active'}])['allowed'])
 def test_owner_halt_stops_other_account(self):
  self.assertFalse(self.decision(self.bill(),expense(account_id='11'),[{'account_id':'*','state':'active'}])['allowed'])
 def test_hidden_credit_child_prevents_independent_credit(self):
  old=self.installment();self.s['relationship_assets']=self.s['assets']+[{'id':12,'type':2,'currency':'CNY','status':2,'credit':{'shareid':10,'limit':100},'userid':'123','money':0}]
  self.assertEqual(self.decision(old)['code'],'credit_dependency_not_adapted')
 def test_credit_member_is_not_independent(self):
  old=self.installment();self.s['assets'][0]['credit']['shareid']=11
  self.assertFalse(self.decision(old)['allowed'])
 def test_unknown_extra_or_related_task_is_not_plain_old_bill(self):
  for extra in ({'newRelation':'x'},{'refundsid':99}):
   old=self.bill();old['plan']['row']['extra']=extra
   self.assertFalse(self.decision(old)['allowed'])
 def test_catalog_dependency_blocks_category_descendant(self):
  self.s['categories'][0].update(level=2,parentid=22);self.s['categories'].append({'id':22,'bookid':1,'name':'Parent','type':0,'level':1})
  old={'request_id':'old','plan':{'action':'category_update','collection':'categories','object_id':'22','params':{'did':'22','bookid':'1'},'expected':{'bookid':1}},'dispatch':None}
  self.assertEqual(self.decision(old)['code'],'dependency_conflict')
 def test_catalog_other_book_is_independent_if_scope_complete(self):
  old={'request_id':'old','plan':{'action':'book_rename','collection':'books','object_id':'2','params':{'v':dumps({'bookid':2,'name':'New'})},'expected':{'name':'New'}},'dispatch':None}
  self.assertTrue(self.decision(old)['allowed'])
 def test_relation_actions_same_account_never_use_create_exception(self):
  for action in ('refund_create','bill_update','debt_pay','repeat_update','installment_delete','account_update'):
   old=self.bill();old['plan']['action']=action
   with self.subTest(action=action):self.assertFalse(self.decision(old)['allowed'])
 def test_new_continuation_rejects_non_first_release_fields(self):
  for fields in ({'fee':'0.00'},{'tag_ids':[]},{'kind':'transfer','to_account_id':'11'},{'currency':'USD'},{'discount':'0.01'}):
   self.assertFalse(self.decision(self.bill(),expense(**fields))['allowed'])
 def test_existing_native_id_wrong_relation_is_conflict(self):
  old=self.bill();self.s['bills']=[{**old['plan']['row'],'assetid':11}]
  self.assertEqual(self.decision(old)['code'],'record_relationship_conflict')
 def test_explicit_balance_conflict_is_not_legacy_exemption(self):
  old=self.bill();old['receipt']={'verification_code':'balance_not_verified'}
  self.assertFalse(self.decision(old)['allowed'])
 def test_rejected_unknown_preserves_whole_snapshot_no_effect_proof(self):
  old=self.bill();old['dispatch']={'outcome':'backend_error','error_code':'backend_rejected'}
  self.assertFalse(self.decision(old,expense(account_id='11'))['allowed'])
 def test_halt_without_financial_pending_does_not_allow_implicit_target_update(self):
  r=decide([],{'action':'bill_update','object_id':'100'},self.s,self.policy,[{'account_id':'10','state':'active'}])
  self.assertFalse(r['allowed'])
