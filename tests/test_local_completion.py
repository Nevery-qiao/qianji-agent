"""Regression cases for native continuation, state discovery and category levels."""
import unittest,tempfile,copy
from decimal import Decimal
from pathlib import Path
from qianji_agent.engine import Engine
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import digest,loads
from test_engine import Backend
from test_business import snapshot,expense

class CompletionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.b=Backend();self.e=Engine(self.b,'123',Path(self.tmp.name)/'state')
 def test_sync_continues_with_server_cursor_and_lasttimes(self):
  base=self.b.read;calls=[]
  def read(route,p):
   if route!='syncv2/pull':return base(route,p)
   calls.append(p)
   if len(calls)==1:return {'changes':[{'id':100}], 'deletes':[], 'categories':[], 'hasmore':1,'bookid':1,'pageoffset':7,'pagesign':'opaque','lasttimes':{'1':20}}
   self.assertEqual(p,{'bookid':1,'pageoffset':7,'pagesign':'opaque','lasttimes':'{"1":20}'})
   return {'changes':[{'id':101}], 'deletes':[], 'categories':[], 'hasmore':0}
  self.b.read=read
  self.assertEqual([r['id'] for r in self.e.snapshot()['bills']],[100,101]);self.assertEqual(len(calls),2)
 def test_bad_cursor_never_dispatches_financial_write(self):
  base=self.b.read
  for changes in ({'hasmore':True},{'hasmore':1,'bookid':1,'pageoffset':0,'pagesign':'x','lasttimes':{}},{'hasmore':2}):
   def read(route,p):
    r=base(route,p)
    return {**r,**changes} if route=='syncv2/pull' else r
   self.b.read=read
   self.assertEqual(self.e.execute('bad',expense())['state'],'not_executed')
  self.assertEqual(self.b.writes,0)
 def test_cross_page_duplicate_does_not_claim_complete(self):
  base=self.b.read;calls=[]
  def read(route,p):
   if route!='syncv2/pull':return base(route,p)
   calls.append(p);return {'changes':[{'id':100}], 'deletes':[], 'categories':[], 'hasmore':int(len(calls)==1),'bookid':1,'pageoffset':1,'pagesign':'x','lasttimes':{}}
  self.b.read=read
  self.assertEqual(self.e.query('bills')['state'],'not_executed')
 def test_accounts_all_discovers_hidden_and_finished_loans(self):
  base=self.b.read
  def read(route,p):
   if route=='asset/list':return {'list':[{'id':10,'status':0}] if p['status']==0 else [{'id':13,'status':2}]}
   if route=='asset/listloan':return {'list':[{'id':14 if p['t']==51 else 15,'status':1,'type':5,'stype':p['t']}]}
   return base(route,p)
  self.b.read=read
  r=self.e.query('accounts',{'status':'all'});self.assertEqual(r['state'],'read');self.assertEqual({x['id'] for x in r['records']},{'10','13','14','15'})
  self.assertEqual(self.e.query('accounts',{'status':'finished'})['total'],2)
  self.assertEqual(self.e.query('books',{'status':'all'})['code'],'invalid_filter')
 def test_account_state_mismatch_is_not_silently_complete(self):
  self.b.read=lambda route,p:{'list':[{'id':13,'status':0}]}
  self.assertEqual(self.e.query('accounts',{'status':'hidden'})['state'],'not_executed')
 def test_category_promote_demote_and_parent_guards(self):
  s=snapshot();s['categories'][0]['parentid']=-1
  old=s['categories'][0];cmd={'action':'category_demote','object_id':'20','expected_version':digest(old),'parent_id':'22'}
  s['categories'].append({**old,'id':22,'name':'Another'})
  p=prepare(cmd,s,'123');self.assertEqual(p['route'],'category/changelevel');self.assertEqual(p['params'],{'did':'20','parentid':'22'})
  after=copy.deepcopy(s);after['categories'][0].update(level=2,parentid=22)
  self.assertEqual(verify(p,after)['object_id'],'20')
  child=after['categories'][0];p=prepare({'action':'category_promote','object_id':'20','expected_version':digest(child)},after,'123')
  self.assertEqual(p['params'],{'did':'20'});self.assertEqual(p['expected']['level'],1)
  for bad in ({'bookid':2},{'type':1},{'level':2}):
   broken=copy.deepcopy(s);broken['categories'][-1].update(bad)
   with self.assertRaises(ValueError):prepare(cmd,broken,'123')
  s['categories'].append({**old,'id':23,'level':2,'parentid':20})
  with self.assertRaises(ValueError):prepare(cmd,s,'123')

if __name__=='__main__':unittest.main()

class AccountCompletionTests(unittest.TestCase):
 def test_account_settings_preserve_balance_and_native_subtype(self):
  s=snapshot();old=s['assets'][0];old.update(status=0,incount=0,remark=None)
  c={'action':'account_update','object_id':'10','expected_version':digest(old),'include_in_total':True,'remark':'Updated'}
  p=prepare(c,s,'123');v=loads(p['params']['v'])
  self.assertEqual(v['money'],1);self.assertEqual(v['stype'],11);self.assertEqual(v['incount'],1);self.assertEqual(v['remark'],'Updated')
  self.assertEqual(p['expected']['money'],1)
  with self.assertRaises(ValueError):prepare({**c,'limit':'2.00'},s,'123')
 def test_credit_settings_cannot_erase_unrelated_native_fields(self):
  s=snapshot();old=s['assets'][0];old.update(type=2,credit={'statedate':1,'paydate2':'d20','limit':100,'statein':0},incount=0)
  p=prepare({'action':'account_update','object_id':'10','expected_version':digest(old),'limit':'200.00','statement_day':2,'payment_day':21},s,'123')
  self.assertEqual(loads(p['params']['v'])['credit'],{'statedate':2,'paydate2':'21','limit':200,'statein':0})
  with self.assertRaises(ValueError):prepare({'action':'account_update','object_id':'10','expected_version':digest(old),'statement_day':32},s,'123')
 def test_recharge_and_investment_templates_keep_native_type(self):
  for name,typ,sub in [('Bus',3,32),('Fund',4,42)]:
   s=snapshot();s['account_templates']=[{'name':name,'type':typ,'stype':sub,'icon':'http://res3.qianjiapp.com/test.png','c':'123456'}]
   p=prepare({'action':'account_create','name':'Test','account_kind':name,'amount':'1.00'},s,'123')
   v=loads(p['params']['v']);self.assertEqual(v['type'],typ);self.assertEqual(v['stype'],sub);self.assertIsNone(v['credit'])

class InstallmentCompletionTests(unittest.TestCase):
 def test_fee_schedule_uses_total_fee_and_explicit_allocation(self):
  s=snapshot();s['assets'][0].update(type=2)
  c={'action':'installment_create','name':'Fee plan','account_id':'10','category_id':'20','amount':'0.05','fee':'0.03','periods':2,'time':'2026-10-18T00:00:00+08:00','fee_method':'average','remainder':'first'}
  p=prepare(c,s,'123');v=loads(p['params']['v'])
  self.assertEqual(v['totalfee'],Decimal('0.03'));self.assertEqual(v['fee'],Decimal('0.01'))
  self.assertEqual(v['data']['feetype'],'ave');self.assertEqual(p['installment_contract']['fees'],[Decimal('0.02'),Decimal('0.01')])
  p=prepare({**c,'fee_method':'last','remainder':'last'},s,'123');self.assertEqual(p['installment_contract']['fees'],[0,Decimal('0.03')]);self.assertEqual(p['installment_contract']['principal'],[Decimal('0.02'),Decimal('0.03')])

class NativeSettingsVerificationTests(unittest.TestCase):
 def test_credit_limits_verify_by_decimal_value_without_ignoring_other_fields(self):
  s=snapshot();old=s['assets'][0];old.update(type=2,credit={'statedate':1,'paydate2':'d20','limit':100,'statein':0},incount=0)
  p=prepare({'action':'account_update','object_id':'10','expected_version':digest(old),'limit':'200.00'},s,'123')
  after=copy.deepcopy(s);after['assets'][0]['credit']['limit']=200
  self.assertEqual(verify(p,after)['object_id'],'10')
  after['assets'][0]['credit']['statedate']=5
  with self.assertRaises(ValueError):verify(p,after)

class InstallmentFeeRelationsTests(unittest.TestCase):
 def test_detached_installment_bill_deletes_total_but_active_task_still_blocks(self):
  s=snapshot();b=prepare(expense(),s,'123',bill_id='100')['row'];b.update(money=Decimal('0.05'),packid=300,extra={'fee':Decimal('0.02')});s['bills']=[b]
  cmd={'action':'bill_delete','object_id':'100','expected_version':digest(b)}
  p=prepare(cmd,s,'123');self.assertEqual(p['balances']['10'],Decimal('1.05'))
  s['installment']=[{'id':30,'packid':300}]
  with self.assertRaises(ValueError):prepare(cmd,s,'123')
 def test_fee_child_metadata_is_checked_in_addition_to_total_balance(self):
  s=snapshot();s['assets'][0].update(type=2)
  p=prepare({'action':'installment_create','name':'Fee','account_id':'10','category_id':'20','amount':'0.05','fee':'0.03','periods':2,'time':'2026-10-18T00:00:00+08:00'},s,'123')
  v=loads(p['params']['v']);v.update(id=30,type=1,count=1,packid=300)
  b=prepare(expense(),s,'123',bill_id='100')['row'];b.update(packid=300,money=Decimal('0.05'),extra={'fee':Decimal('0.01')})
  after=copy.deepcopy(s);after['bills']=[b];after['installment']=[v];after['assets'][0]['money']=Decimal('0.95')
  with self.assertRaises(ValueError):verify(p,after)
  b['extra']['fee']=Decimal('0.02');self.assertEqual(verify(p,after)['related_bill_ids'],['100'])

class InstallmentDynamicAmountTests(unittest.TestCase):
 def test_two_period_remaining_amount_after_first_execution(self):
  s=snapshot();s['assets'][0].update(type=2)
  p=prepare({'action':'installment_create','name':'Last fee','account_id':'10','category_id':'20','amount':'0.05','fee':'0.03','fee_method':'last','remainder':'last','periods':2,'time':'2026-10-18T00:00:00+08:00'},s,'123')
  v=loads(p['params']['v']);v.update(id=30,type=1,count=1,packid=300,money=Decimal('0.03'),fee=Decimal('0.03'))
  b=prepare(expense(),s,'123',bill_id='100')['row'];b.update(packid=300,money=Decimal('0.02'),extra=None)
  after=copy.deepcopy(s);after['bills']=[b];after['installment']=[v];after['assets'][0]['money']=Decimal('0.98')
  self.assertEqual(verify(p,after)['object_id'],'30')
  v['money']=Decimal('0.04')
  with self.assertRaises(ValueError):verify(p,after)

class ForeignAccountCompletionTests(unittest.TestCase):
 def test_foreign_account_currency_is_preserved_on_creation(self):
  p=prepare({'action':'account_create','name':'USD cash','amount':'1.00','currency':'USD'},snapshot(),'123')
  self.assertEqual(loads(p['params']['v'])['currency'],'USD');self.assertEqual(p['expected']['currency'],'USD')
 def test_foreign_account_uses_own_units_for_balance_and_base_for_bill(self):
  s=snapshot();s['assets'][0]['currency']='USD'
  p=prepare(expense(currency='USD',amount='0.01',account_amount='0.01',base_amount='0.07'),s,'123',bill_id='100')
  self.assertEqual(p['balances']['10'],Decimal('0.99'));self.assertEqual(p['row']['money'],Decimal('0.01'));self.assertEqual(p['row']['extra']['curr']['ts'],'USD')
  row=p['row'];s['bills']=[row];s['assets'][0]['money']=Decimal('0.99')
  p=prepare({'action':'bill_delete','object_id':'100','expected_version':digest(row)},s,'123');self.assertEqual(p['balances']['10'],Decimal('1.00'))
  with self.assertRaises(ValueError):prepare(expense(currency='USD',amount='0.01',account_amount='0.02',base_amount='0.07'),s,'123')
 def test_cny_source_to_foreign_account_requires_consistent_base_amount(self):
  s=snapshot();s['assets'][0]['currency']='USD'
  p=prepare(expense(currency='CNY',amount='0.07',account_amount='0.01',base_amount='0.07'),s,'123')
  self.assertEqual(p['balances']['10'],Decimal('0.99'))
  with self.assertRaises(ValueError):prepare(expense(currency='CNY',amount='0.07',account_amount='0.01',base_amount='0.08'),s,'123')

class JournalPathCompletionTests(unittest.TestCase):
 def test_public_service_rejects_relative_state_before_loading_account(self):
  from qianji_agent.server import LocalService
  from unittest.mock import patch
  with patch('qianji_agent.auth.load_session',side_effect=AssertionError('must not load')):
   r=LocalService('relative-state').query('books')
  self.assertEqual(r['state'],'not_executed');self.assertEqual(r['code'],'unsafe_state_path')

class CrossCurrencyTransferTests(unittest.TestCase):
 def test_transfer_uses_explicit_source_and_target_units(self):
  s=snapshot();s['assets'][1]['currency']='USD'
  p=prepare({'action':'bill_create','kind':'transfer','book_id':'1','account_id':'10','to_account_id':'11','amount':'0.01','currency':'USD','account_amount':'0.07','base_amount':'0.07','time':'2026-10-18T00:00:00+08:00'},s,'123',bill_id='100')
  self.assertEqual(p['balances'],{'10':Decimal('0.93'),'11':Decimal('2.01')})
  self.assertEqual(p['row']['extra']['curr'],{'ss':'CNY','sv':Decimal('0.07'),'ts':'USD','tv':Decimal('0.01'),'bs':'CNY','bv':Decimal('0.07')})
  s['bills']=[p['row']];q=prepare({'action':'bill_delete','object_id':'100','expected_version':digest(p['row'])},s,'123')
  self.assertEqual(q['balances'],{'10':Decimal('1.07'),'11':Decimal('1.99')})
 def test_conversion_fee_and_inconsistent_same_currency_are_refused(self):
  s=snapshot();s['assets'][1]['currency']='USD'
  c={'action':'bill_create','kind':'transfer','book_id':'1','account_id':'10','to_account_id':'11','amount':'0.01','currency':'USD','account_amount':'0.07','base_amount':'0.07','fee':'0.01','time':'2026-10-18T00:00:00+08:00'}
  with self.assertRaises(ValueError):prepare(c,s,'123')

class PaginationAccumulationTests(unittest.TestCase):
 def test_lasttimes_from_completed_books_survive_later_pages(self):
  with tempfile.TemporaryDirectory() as root:
   b=Backend();base=b.read;calls=[]
   def read(route,p):
    if route!='syncv2/pull':return base(route,p)
    calls.append(p)
    if len(calls)==1:return {'changes':[{'id':100}],'deletes':[],'categories':[],'hasmore':1,'bookid':1,'pageoffset':1,'pagesign':'a','lasttimes':{'1':10}}
    if len(calls)==2:return {'changes':[{'id':101}],'deletes':[],'categories':[],'hasmore':1,'bookid':2,'pageoffset':0,'pagesign':'b','lasttimes':{'2':20}}
    self.assertEqual(loads(p['lasttimes']),{'1':10,'2':20})
    return {'changes':[{'id':102}],'deletes':[],'categories':[],'hasmore':0}
   b.read=read;self.assertEqual(len(Engine(b,'123',Path(root)/'state').snapshot()['bills']),3)

class CurrencyConsistencyTests(unittest.TestCase):
 def test_unused_conversion_fields_cannot_hide_inconsistent_cny_amounts(self):
  with self.assertRaises(ValueError):prepare(expense(amount='0.10',account_amount='0.20',base_amount='0.20'),snapshot(),'123')
 def test_foreign_copy_keeps_conversion_and_charges_account_units_once(self):
  s=snapshot();s['assets'][0]['currency']='USD';row=prepare(expense(currency='USD',amount='0.01',account_amount='0.01',base_amount='0.07'),s,'123',bill_id='100')['row'];s['bills']=[row]
  p=prepare({'action':'bill_copy','object_id':'100','time':'2026-10-18T08:00:00+08:00'},s,'123',bill_id='101')
  self.assertEqual(p['balances']['10'],Decimal('0.99'));self.assertEqual(p['row']['extra']['curr'],row['extra']['curr'])

class TransferNativeUnitsTests(unittest.TestCase):
 def test_native_transfer_money_is_source_units_not_base_currency(self):
  s=snapshot();s['assets'][0]['currency']='USD'
  p=prepare({'action':'bill_create','kind':'transfer','book_id':'1','account_id':'10','to_account_id':'11','amount':'0.07','currency':'CNY','account_amount':'0.01','base_amount':'0.07','time':'2026-10-18T00:00:00+08:00'},s,'123',bill_id='100')
  self.assertEqual(p['row']['money'],Decimal('0.01'));self.assertEqual(p['balances'],{'10':Decimal('0.99'),'11':Decimal('2.07')})

class BillMoveCompletionTests(unittest.TestCase):
 def test_expense_move_changes_account_and_book_with_matching_category(self):
  s=snapshot();row=prepare(expense(),s,'123',bill_id='100')['row'];s['bills']=[row];s['assets'][0]['money']=Decimal('0.90')
  s['books'].append({'bookid':2,'userid':'123','name':'Other'});s['categories'].append({**s['categories'][0],'id':22,'bookid':2})
  p=prepare({'action':'bill_update','object_id':'100','expected_version':digest(row),'account_id':'11','book_id':'2','category_id':'22'},s,'123')
  self.assertEqual(p['row']['bookid'],2);self.assertEqual(p['row']['assetid'],11);self.assertEqual(p['balances'],{'10':Decimal('1.00'),'11':Decimal('1.90')})
  with self.assertRaises(ValueError):prepare({'action':'bill_update','object_id':'100','expected_version':digest(row),'book_id':'2'},s,'123')
 def test_transfer_edit_validates_new_target_is_not_source(self):
  s=snapshot();row=prepare(expense(kind='transfer',to_account_id='11',category_id=None),s,'123',bill_id='100')['row'];s['bills']=[row]
  with self.assertRaises(ValueError):prepare({'action':'bill_update','object_id':'100','expected_version':digest(row),'to_account_id':'10'},s,'123')
