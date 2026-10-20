"""Breaks caught: global digest false positives, late drift swallowed, stale ready."""
import copy,tempfile,unittest
from pathlib import Path
from decimal import Decimal
from test_business import expense
from test_recovery_integration import AccountBackend
from qianji_agent.engine import Engine
from qianji_agent.journal import Journal
from qianji_agent.linked import prepare_linked

class FullBackend(AccountBackend):
 def read(self,route,params):
  if route=='asset/list':
   if self.fail_read:raise ValueError('private-token')
   return {'list':copy.deepcopy([a for a in self.data['assets'] if a.get('status',0)==params.get('status',0)])}
  if route=='asset/listloan':return {'list':copy.deepcopy([a for a in self.data['assets'] if a.get('type')==5 and a.get('status')==params['status'] and a.get('stype')==params['t']])}
  return super().read(route,params)

class AccountReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'state';self.b=FullBackend()
  self.assertTrue(callable(getattr(Engine,'account_review',None)),'Missing account review and write-before-drift check')
 def engine(self):return Engine(self.b,'123',self.root)
 def history(self):
  self.b.data['assets'][0].update(type=2,credit={'limit':100,'shareid':-1})
  p=prepare_linked({'action':'installment_create','name':'History','account_id':'10','category_id':'20','amount':'3.00','periods':3,'time':'2026-10-18T08:00:00+08:00'},self.b.data,'123');p['owner']='123';p['extended']=True
  j=Journal(self.root,'123');j.start('old','old',p);return copy.deepcopy(j.get('old'))
 def account(self,r,aid):return next(a for a in r['account_review']['accounts'] if a['account_id']==aid)
 def test_explicit_review_is_persistent_and_has_actual_observation_time(self):
  e=self.engine();r=e.account_review();self.assertEqual(r['state'],'read');self.assertTrue(r['account_review']['ready']);self.assertTrue(r['account_review']['current']);self.assertGreater(r['account_review']['observed_at'],0)
  self.assertIn('10',e.journal.watch_state()['watchpoints']);self.assertEqual(self.b.writes,0)
 def test_historical_same_credit_expense_strictly_verified_without_old_mutation(self):
  original=self.history();e=self.engine();r=e.execute('new',expense())
  self.assertEqual(r['state'],'verified');self.assertTrue(r['native_fields_verified']);self.assertTrue(r['balances_verified']);self.assertEqual(self.b.writes,1)
  self.assertEqual(e.journal.get('old'),original);self.assertEqual(r['continuation']['historical_count'],1)
 def test_new_unknown_stops_same_account_after_restart_and_income_switch(self):
  self.history();e=self.engine();self.b.lose=True;r=e.execute('first',expense());self.assertEqual(r['state'],'pending_verification');self.b.fail_read=False;self.b.lose=False
  restored=self.engine()
  for cmd in (expense(),expense(kind='income',category_id='21')):
   self.assertEqual(restored.execute('different',cmd)['continuation']['decision_code'],'account_halted')
  self.assertEqual(self.b.writes,1)
 def test_a_drift_does_not_stop_b_with_complete_independent_scope(self):
  self.history();e=self.engine();e.account_review();self.b.data['assets'][0]['money']-=Decimal('0.20')
  r=e.execute('other',expense(account_id='11'));self.assertEqual(r['state'],'verified');self.assertEqual(self.b.writes,1)
  halted=e.journal.active_halts();self.assertTrue(any(h['account_id']=='10' for h in halted));self.assertFalse(any(h['account_id']=='11' for h in halted))
 def test_a_external_bill_change_does_not_stop_b(self):
  e=self.engine();e.account_review();self.b.data['bills'].append({'id':991,'assetid':10,'type':0,'money':Decimal('0.20'),'remark':'external'})
  self.b.data['assets'][0]['money']-=Decimal('0.20')
  self.assertEqual(e.execute('b',expense(account_id='11'))['state'],'verified')
 def test_drift_before_prepare_cannot_be_swallowed_by_new_balance_anchor(self):
  e=self.engine();e.account_review();before=copy.deepcopy(e.journal.watch_state()['watchpoints']['10']);self.b.data['assets'][0]['money']-=Decimal('0.20')
  self.assertEqual(e.execute('new',expense())['code'],'account_halted');self.assertEqual(self.b.writes,0)
  self.assertEqual(e.journal.watch_state()['watchpoints']['10'],before)
 def test_verified_then_late_effect_is_discovered_without_new_financial_work(self):
  self.history();e=self.engine();self.assertEqual(e.execute('new',expense())['state'],'verified');self.b.data['assets'][0]['money']-=Decimal('0.20')
  r=e.account_review();self.assertEqual(self.account(r,'10')['state'],'halted');self.assertEqual(self.b.writes,1)
  self.assertEqual(self.engine().execute('later',expense())['code'],'account_halted')
 def test_late_effect_during_write_keeps_new_request_pending_and_stops_account(self):
  self.history();e=self.engine();write=self.b.write
  def late(*args):
   result=write(*args);self.b.data['assets'][0]['money']-=Decimal('0.20');return result
  self.b.write=late;r=e.execute('new',expense());self.assertEqual(r['state'],'pending_verification');self.assertEqual(self.b.writes,1)
  self.assertTrue(e.journal.active_halts());self.assertEqual(e.execute('later',expense())['continuation']['decision_code'],'account_halted')
 def test_equal_balance_but_extra_external_bill_never_verified(self):
  self.history();e=self.engine();write=self.b.write
  def extra(*args):
   result=write(*args);self.b.data['bills'].append({'id':992,'assetid':10,'type':0,'money':0,'remark':'external'});return result
  self.b.write=extra;self.assertEqual(e.execute('new',expense())['state'],'pending_verification')
 def test_failed_read_marks_current_unavailable_not_cached_ready(self):
  e=self.engine();self.assertTrue(e.account_review()['account_review']['ready']);before=e.journal.watch_state();self.b.fail_read=True
  r=e.account_review();self.assertFalse(r['account_review']['ready']);self.assertFalse(r['account_review']['current']);self.assertEqual(r['account_review']['state'],'unavailable');self.assertEqual(e.journal.watch_state(),before)
 def test_credit_hidden_shared_member_blocks_first_release_continuation(self):
  self.history();self.b.data['assets'].append({'id':12,'type':2,'status':2,'money':0,'currency':'CNY','userid':'123','credit':{'shareid':10,'limit':100}})
  self.assertEqual(self.engine().execute('new',expense())['code'],'credit_dependency_not_adapted');self.assertEqual(self.b.writes,0)
 def test_known_new_request_verifies_original_without_resend_and_updates_watchpoint(self):
  self.history();e=self.engine();self.b.lose=True;e.execute('new',expense());self.b.lose=False;self.b.fail_read=False
  self.assertEqual(e.operation('new')['state'],'verified');self.assertEqual(self.b.writes,1)
  self.assertEqual(e.execute('next',expense())['state'],'verified');self.assertEqual(self.b.writes,2)
 def test_first_review_does_not_initialize_over_active_pending(self):
  e=self.engine();self.b.lose=True;e.execute('new',expense());self.b.lose=False;self.b.fail_read=False
  # Every write now records its BEFORE observation, even without an explicit review.
  before=copy.deepcopy(e.journal.watch_state()['watchpoints']['10'])
  r=e.account_review();self.assertEqual(self.account(r,'10')['state'],'halted')
  self.assertEqual(e.journal.watch_state()['watchpoints']['10'],before)
  self.assertEqual(before['balance'],'1');self.assertEqual(before['bills'],{})
 def test_old_object_appears_but_new_verified_balance_context_stays_unknown(self):
  from qianji_agent.codec import loads
  old=self.history();e=self.engine();self.assertEqual(e.execute('new',expense())['state'],'verified')
  task=loads(old['plan']['params']['v']);task.update(id=77,type=1,money=Decimal('3.00'),fee=Decimal('0.00'),count=0,packid=777)
  read=self.b.read
  def with_task(route,params):return {'list':[task],'hasmore':0} if route=='installment/list' else read(route,params)
  self.b.read=with_task;r=e.operation('old')
  self.assertEqual(r['state'],'pending_verification');self.assertEqual(r['verification_code'],'historical_balance_context_unattributed')
  self.assertEqual(e.journal.get('old')['plan'],old['plan']);self.assertEqual(self.b.writes,1)
 def test_balance_formatting_alone_does_not_create_halt(self):
  e=self.engine();e.account_review();self.b.data['assets'][0]['money']=Decimal('1')
  self.assertEqual(self.account(e.account_review(),'10')['state'],'matched')
 def test_review_does_not_leave_orphan_cause_after_original_unknown_verified(self):
  e=self.engine();e.account_review();self.b.lose=True;e.execute('new',expense());self.b.lose=False;self.b.fail_read=False
  e.account_review();self.assertEqual(e.operation('new')['state'],'verified')
  self.assertEqual(e.journal.active_halts(),[])
 def test_existing_balance_stop_clears_only_after_original_verified_without_orphan(self):
  from qianji_agent.operations import prepare
  p=prepare(expense(),self.b.data,'123',bill_id='101');p['extended']=False
  j=Journal(self.root,'123');j.start('old-conflict','h',p);j.finish('old-conflict',{'state':'pending_verification','verification_code':'balance_not_verified'})
  self.b.write(p['route'],p['params']);e=self.engine();e.account_review()
  self.assertEqual(e.operation('old-conflict')['state'],'verified');self.assertEqual(e.journal.active_halts(),[])
 def test_private_context_read_failure_does_not_erase_unknown_dispatch_state(self):
  self.history();e=self.engine();write=self.b.write
  def off_balance(*args):
   result=write(*args);self.b.data['assets'][0]['money']-=Decimal('0.20');return result
  self.b.write=off_balance
  def broken(*a):raise OSError('private disk error')
  e.journal.continuation_context=broken
  r=e.execute('new',expense());self.assertEqual(r['state'],'pending_verification');self.assertEqual(self.b.writes,1);self.assertNotIn('private disk',str(r));self.assertEqual(r['verification_code'],'balance_not_verified')

 def test_own_verified_edit_advances_only_its_account_watchpoint(self):
  from qianji_agent.codec import loads,digest
  class EditBackend(FullBackend):
   def write(self,route,params):
    self.writes+=1;row=loads(loads(params['v'])['bills']['changelist'])[0]
    previous=next((b for b in self.data['bills'] if b['id']==row['id']),None)
    a=next(a for a in self.data['assets'] if a['id']==row['assetid'])
    if previous:self.data['bills'].remove(previous);a['money']+=previous['money']
    self.data['bills'].append(row);a['money']-=row['money'];return {}
  self.b=EditBackend();e=self.engine();first=e.execute('first',expense());e.account_review()
  old=self.b.data['bills'][0]
  r=e.execute('edit',{'action':'bill_update','object_id':first['object_id'],'expected_version':digest(old),'amount':'0.20'})
  self.assertEqual(r['state'],'verified');self.assertEqual(self.account(e.account_review(),'10')['state'],'matched')

 def test_own_account_rename_does_not_create_unexplained_drift(self):
  from qianji_agent.codec import loads,digest
  class RenameBackend(FullBackend):
   def write(self,route,params):
    self.assert_route=route;self.writes+=1;value=loads(params['v'])
    self.data['assets']=[value if a['id']==value['id'] else a for a in self.data['assets']];return {}
  self.b=RenameBackend();e=self.engine();e.account_review()
  r=e.execute('rename',{'action':'account_rename','object_id':'10','name':'Renamed','expected_version':digest(self.b.data['assets'][0])})
  self.assertEqual(r['state'],'verified');self.assertEqual(self.account(e.account_review(),'10')['state'],'matched')

 def test_hidden_credit_member_added_during_write_is_not_silently_accepted(self):
  self.history();e=self.engine();write=self.b.write
  def add_member(*args):
   result=write(*args);self.b.data['assets'].append({'id':12,'type':2,'status':2,'money':0,'currency':'CNY','userid':'123','credit':{'shareid':10,'limit':100}});return result
  self.b.write=add_member;self.assertEqual(e.execute('new',expense())['state'],'pending_verification')
