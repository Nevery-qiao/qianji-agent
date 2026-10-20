import copy,unittest
from decimal import Decimal
from test_business import snapshot
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import digest,loads

class LinkedTests(unittest.TestCase):
 def setUp(self):self.s=snapshot()
 def debt(self,stype=51):
  d={'id':12,'userid':'123','name':'debt','type':5,'stype':stype,'money':Decimal('-0.04') if stype==51 else Decimal('0.04'),'currency':'CNY','loan':{'money':Decimal('-0.04') if stype==51 else Decimal('0.04')}}
  self.s['assets'].append(d);return d
 def test_lend_create_native_account_and_cash_direction(self):
  p=prepare({'action':'debt_create','name':'Lend','kind':'lend','book_id':'1','account_id':'10','amount':'0.04','start_date':'2026-10-18'},self.s,'123')
  v=loads(p['params']['v']);self.assertEqual(v['stype'],52);self.assertEqual(v['money'],Decimal('0.04'));self.assertEqual(p['balances']['10'],Decimal('0.96'))
 def test_borrow_repay_principal_and_interest_are_separate_native_bills(self):
  d=self.debt();p=prepare({'action':'debt_pay','object_id':'12','expected_version':digest(d),'book_id':'1','account_id':'10','amount':'0.02','interest':'0.01','time':'2026-10-18T08:00:00+08:00'},self.s,'123',bill_id='100')
  self.assertEqual([r['type'] for r in p['rows']],[9,10]);self.assertEqual(p['balances'],{'10':Decimal('0.97'),'12':Decimal('-0.02')})
 def test_collect_lend_and_interest_income_native_direction(self):
  d=self.debt(52);p=prepare({'action':'debt_pay','object_id':'12','expected_version':digest(d),'book_id':'1','account_id':'10','amount':'0.02','interest':'0.01','time':'2026-10-18T08:00:00+08:00'},self.s,'123',bill_id='100')
  self.assertEqual([r['type'] for r in p['rows']],[4,11]);self.assertEqual(p['balances'],{'10':Decimal('1.03'),'12':Decimal('0.02')})
 def test_overpay_refused(self):
  d=self.debt()
  with self.assertRaises(ValueError):prepare({'action':'debt_pay','object_id':'12','expected_version':digest(d),'book_id':'1','account_id':'10','amount':'0.05','time':'2026-10-18T08:00:00+08:00'},self.s,'123')
 def test_repeat_task_uses_native_schedule_no_local_scheduler(self):
  p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','repeat_unit':'day','end_count':1,'clock':'08:00'},self.s,'123')
  self.assertEqual(p['route'],'repeat_task/submit');v=loads(p['params']['v']);self.assertEqual(v['data']['end']['count'],1);self.assertEqual(v['data']['repeat'],{'type':'day','value':None})
 def test_installment_requires_credit_and_exact_total(self):
  with self.assertRaises(ValueError):prepare({'action':'installment_create','name':'Plan','account_id':'10','category_id':'20','amount':'0.04','periods':2,'time':'2026-10-18T00:00:00+08:00'},self.s,'123')
  self.s['assets'][0].update(type=2,stype=200)
  p=prepare({'action':'installment_create','name':'Plan','account_id':'10','category_id':'20','amount':'0.05','periods':2,'time':'2026-10-18T00:00:00+08:00'},self.s,'123')
  v=loads(p['params']['v']);self.assertEqual(v['totalmoney'],Decimal('0.05'));self.assertEqual(v['money'],Decimal('0.02'));self.assertEqual(v['data']['lefttype'],'first')
 def test_task_readback_omits_null_schedule_keys(self):
  p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','repeat_unit':'day','end_count':1,'clock':'08:00'},self.s,'123')
  v=loads(p['params']['v']);v.update(id=30,count=0,status=0,packid=1234);v['data']['end'].pop('date');v['data']['repeat'].pop('value')
  after=copy.deepcopy(self.s);after['repeat']=[v]
  self.assertEqual(verify(p,after)['object_id'],'30')
 def test_repeat_update_strips_server_only_bookuid_preserves_native_pack(self):
  p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','end_count':2,'clock':'08:00'},self.s,'123')
  v=loads(p['params']['v']);v.update(id=30,status=0,count=0,packid=1234,bookuid='123');self.s['repeat']=[v]
  changed=prepare({'action':'repeat_update','object_id':'30','expected_version':digest(v),'amount':'0.02'},self.s,'123')
  payload=loads(changed['params']['v']);self.assertNotIn('bookuid',payload);self.assertEqual(payload['packid'],1234);self.assertEqual(payload['data']['money'],Decimal('0.02'))
 def test_native_task_clock_can_omit_leading_zero(self):
  p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','end_count':2,'clock':'08:00'},self.s,'123')
  v=loads(p['params']['v']);v.update(id=30,count=0,status=0,packid=1234);v['data']['time']='8:0';self.s['repeat']=[v]
  self.assertEqual(verify(p,self.s)['object_id'],'30')
  change=prepare({'action':'repeat_update','object_id':'30','expected_version':digest(v),'amount':'0.02'},self.s,'123');self.assertEqual(loads(change['params']['v'])['data']['time'],'08:00')
 def test_weekly_schedule_preserves_explicit_weekdays(self):
  p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','repeat_unit':'week','repeat_values':[1,5],'end_count':2,'clock':'08:00'},self.s,'123')
  self.assertEqual(loads(p['params']['v'])['data']['repeat'],{'type':'week','value':[1,5]})
 def test_interval_schedule_requires_positive_integer_days(self):
  c={'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','repeat_unit':'bystep','repeat_value':3,'end_count':2,'clock':'08:00'}
  self.assertEqual(loads(prepare(c,self.s,'123')['params']['v'])['data']['repeat'],{'type':'bystep','value':[3]})
  c['repeat_value']=0
  with self.assertRaises(ValueError):prepare(c,self.s,'123')
 def test_debt_finish_requires_zero_principal_and_keeps_native_finish_date(self):
  d=self.debt();c={'action':'debt_finish','object_id':'12','expected_version':digest(d),'end_date':'2026-10-18'}
  with self.assertRaises(ValueError):prepare(c,self.s,'123')
  d['money']=Decimal('0.00');c['expected_version']=digest(d)
  p=prepare(c,self.s,'123');self.assertEqual(p['route'],'asset/finish');self.assertEqual(p['params']['v'],'2026-10-18')
 def test_installment_config_only_changes_native_count_flag(self):
  r={'id':30,'userid':'123','incount':0,'data':{},'packid':1234};self.s['installment']=[r]
  p=prepare({'action':'installment_config','object_id':'30','expected_version':digest(r),'include_statistics':True},self.s,'123')
  self.assertEqual(p['route'],'installment/config');self.assertEqual(loads(p['params']['v']),{'incount':1,'feeincount':0})
 def test_native_prepay_uses_remaining_principal_and_two_account_balances(self):
  self.s['assets'][1].update(type=2,stype=200,money=Decimal('-0.03'))
  self.s['installment']=[{'id':30,'userid':'123','assetid':11,'type':1,'status':1,'money':Decimal('.02'),'fee':Decimal(0),'totalfee':Decimal(0),'totalmoney':Decimal('0.05'),'totalcount':2,'count':1,'packid':300,'data':{'cateid':20,'lefttype':'first','feetype':'ave'}}]
  self.s['bills']=[{'id':100,'userid':'123','bookid':1,'cateid':20,'type':0,'assetid':11,'packid':300,'money':Decimal('0.03')}]
  r=self.s['installment'][0];p=prepare({'action':'installment_prepay','object_id':'30','expected_version':digest(r),'book_id':'1','account_id':'10','amount':'0.02','fee':'0.00','time':'2026-10-18T08:00:00+08:00'},self.s,'123')
  v=loads(p['params']['v']);self.assertEqual(v['dataid'],30);self.assertEqual(v['fromid'],10);self.assertEqual(v['money'],Decimal('0.02'))
  self.assertEqual(p['balances'],{'10':Decimal('0.98'),'11':Decimal('-0.03')})
 def test_native_workday_empty_values_equal_default(self):
  p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','repeat_unit':'workday','end_count':1,'clock':'08:00'},self.s,'123')
  p['task_data']['repeat']={'type':'workday','value':None}
  v=loads(p['params']['v']);v.update(id=30,count=0,status=1,packid=300);v['data']['repeat']={'type':'workday','value':[]};self.s['repeat']=[v]
  self.assertEqual(verify(p,self.s)['object_id'],'30')

 def test_bystep_readback_singleton_list_matches_prior_string_request(self):
  p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','repeat_unit':'bystep','repeat_value':3,'end_count':1,'clock':'08:00'},self.s,'123')
  p['task_data']['repeat']={'type':'bystep','value':'3'}
  v=loads(p['params']['v']);v.update(id=30,count=0,status=1,packid=300);v['data']['repeat']={'type':'bystep','value':[3]};self.s['repeat']=[v]
  self.assertEqual(verify(p,self.s)['object_id'],'30')
 def test_native_installment_false_fee_flag_may_be_omitted(self):
  r={'id':30,'userid':'123','incount':0,'data':{},'packid':1234};self.s['installment']=[r]
  p=prepare({'action':'installment_config','object_id':'30','expected_version':digest(r),'include_statistics':True,'fee_include_statistics':False},self.s,'123')
  after=copy.deepcopy(self.s);after['installment'][0]['incount']=1
  self.assertEqual(verify(p,after)['object_id'],'30')
  after['installment'][0]['data']['feeincount']=1
  with self.assertRaises(ValueError):verify(p,after)
 def test_prepay_record_pair_delete_requires_both_versions_and_removed_task(self):
  from qianji_agent.operations import make_row
  pay=make_row('123','1','100',1792281600,3);pay.update(money=Decimal('0.02'),fromid=10,targetid=11,packid=300,extra={'presid':101})
  spend=make_row('123','1','101',1792281600,0);spend.update(money=Decimal('0.02'),assetid=11,packid=300,extra={'pretid':100,'preinstallid':30})
  self.s['bills']=[pay,spend];self.s['assets'][1]['type']=2
  c={'action':'prepay_records_delete','object_id':'100','related_id':'101','expected_version':digest(pay),'related_version':digest(spend)}
  p=prepare(c,self.s,'123');self.assertEqual(loads(p['params']['v'])['bills']['dellist'],[100,101]);self.assertEqual(p['balances'],{'10':Decimal('1.02'),'11':Decimal('2.00')})
  after=copy.deepcopy(self.s);after.update(bills=[],deletes=[100,101]);after['assets'][0]['money']=Decimal('1.02')
  self.assertEqual(set(verify(p,after)['related_bill_ids']),{'100','101'})
  after['deletes']=[100]
  with self.assertRaises(ValueError):verify(p,after)
  self.s['installment']=[{'id':30,'packid':300}]
  with self.assertRaises(ValueError):prepare(c,self.s,'123')
 def test_transfer_repayment_and_advance_recurring_use_native_types(self):
  self.s['assets'][1]['type']=2
  base={'action':'repeat_create','book_id':'1','account_id':'10','amount':'0.01','start_date':'2026-10-19','end_count':1,'clock':'08:00'}
  for kind,typ in [('transfer',2),('repayment',3)]:
   p=prepare({**base,'kind':kind,'to_account_id':'11'},self.s,'123');v=loads(p['params']['v']);self.assertEqual(v['type'],typ);self.assertEqual(v['data']['targetid'],11);self.assertIsNone(v['data']['cateid'])
  p=prepare({**base,'kind':'reimburse_advance','category_id':'20'},self.s,'123');self.assertEqual(loads(p['params']['v'])['type'],5)
 def test_recurring_generated_bill_must_match_task_kind_and_references(self):
  from qianji_agent.operations import make_row
  p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-18','end_count':1,'clock':'08:00'},self.s,'123')
  task=loads(p['params']['v']);task.update(id=30,count=1,status=2,packid=300);self.s['repeat']=[task]
  wrong=make_row('123','1','100',1792281600,1);wrong.update(packid=300,money=Decimal('0.01'),assetid=10,cateid=20);self.s['bills']=[wrong];self.s['assets'][0]['money']=Decimal('1.01')
  with self.assertRaisesRegex(ValueError,'task_child_relation_not_verified'):verify(p,self.s)
 def test_prepay_pair_cleanup_reverses_native_transfer_fee(self):
  from qianji_agent.operations import make_row
  pay=make_row('123','1','100',1792281600,3);pay.update(money=Decimal('0.02'),fromid=10,targetid=11,packid=300,extra={'presid':101,'transfee':Decimal('0.01')})
  spend=make_row('123','1','101',1792281600,0);spend.update(money=Decimal('0.02'),assetid=11,packid=300,extra={'pretid':100,'preinstallid':30});self.s['bills']=[pay,spend]
  p=prepare({'action':'prepay_records_delete','object_id':'100','related_id':'101','expected_version':digest(pay),'related_version':digest(spend)},self.s,'123');self.assertEqual(p['balances']['10'],Decimal('1.03'))
 def test_prepay_requires_fee_and_bidirectional_native_pair(self):
  from qianji_agent.operations import make_row
  pay=make_row('123','1','100',1792281600,3);pay.update(money=Decimal('0.02'),fromid=10,targetid=11,packid=300,extra={'presid':101})
  spend=make_row('123','1','101',1792281600,0);spend.update(money=Decimal('0.02'),assetid=11,packid=300,extra={'pretid':100,'preinstallid':30})
  self.s.update(bills=[pay,spend],installment=[{'id':30,'data':{'prepay':1}}])
  p={'collection':'installment','object_id':'30','expected':{},'balances':{},'prepay':{'principal':Decimal('0.02'),'fee':Decimal('0.01'),'credit':'11','cash':'10','bookid':1,'packid':300,'before_ids':[]}}
  with self.assertRaisesRegex(ValueError,'native_prepay_bills_not_verified'):verify(p,self.s)
  pay['extra']['transfee']=Decimal('0.01');self.assertEqual(set(verify(p,self.s)['related_bill_ids']),{'100','101'})
 def test_unrecognized_fee_allocation_is_not_exposed(self):
  self.s['assets'][0].update(type=2,stype=200)
  with self.assertRaisesRegex(ValueError,'unsupported_operation'):prepare({'action':'installment_create','name':'Fee Plan','account_id':'10','category_id':'20','amount':'0.05','periods':2,'fee':'0.02','fee_method':'guess','time':'2026-10-18T00:00:00+08:00'},self.s,'123')
 def test_native_installment_task_type_is_distinct_from_bill_expense_type(self):
  from qianji_agent.operations import make_row
  self.s['assets'][0].update(type=2,stype=200)
  p=prepare({'action':'installment_create','name':'Native Plan','account_id':'10','category_id':'20','amount':'0.05','periods':2,'time':'2026-10-18T00:00:00+08:00'},self.s,'123')
  task=loads(p['params']['v']);task.update(id=30,type=1,count=1,packid=300)
  child=make_row('123','1','100',task['starttime'],0);child.update(money=Decimal('0.03'),assetid=10,cateid=20,packid=300)
  self.s.update(installment=[task],bills=[child]);self.s['assets'][0]['money']-=Decimal('0.03')
  self.assertTrue(verify(p,self.s)['task_execution_observed']);self.assertEqual(p['expected']['type'],1)
 def test_repeat_update_accepts_native_omitted_optional_remark(self):
  p=prepare({'action':'repeat_create','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','end_count':2,'clock':'08:00'},self.s,'123')
  row=loads(p['params']['v']);row.update(id=30,status=1,count=0,packid=300);row['data'].pop('remark');self.s['repeat']=[row]
  update=prepare({'action':'repeat_update','object_id':'30','expected_version':digest(row),'amount':'0.02'},self.s,'123')
  self.assertIsNone(update['task_data']['remark'])
 def test_repeat_update_accepts_proven_native_workday_empty_list(self):
  p=prepare({'action':'repeat_create','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','repeat_unit':'workday','end_count':2,'clock':'08:00'},self.s,'123')
  row=loads(p['params']['v']);row.update(id=30,status=1,count=0,packid=300);row['data']['repeat']['value']=[];self.s['repeat']=[row]
  update=prepare({'action':'repeat_update','object_id':'30','expected_version':digest(row),'amount':'0.02'},self.s,'123')
  self.assertEqual(loads(update['params']['v'])['data']['money'],Decimal('0.02'))
