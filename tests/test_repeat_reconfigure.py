import unittest,copy
from decimal import Decimal
from test_business import snapshot
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import loads,digest
class RepeatReconfigureTests(unittest.TestCase):
 def setUp(self):
  self.s=snapshot();p=prepare({'action':'repeat_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.02','start_date':'2026-10-18','clock':'00:01','repeat_unit':'day','end_count':2},self.s,'123');self.row=loads(p['params']['v']);self.row.update(id=30,count=1,status=1,packid=300);self.s['repeat']=[self.row]
 def cmd(self,**kw):return {'action':'repeat_update','object_id':'30','expected_version':digest(self.row),**kw}
 def test_frequency_and_funding_account_update_do_not_rewrite_history(self):
  p=prepare(self.cmd(repeat_unit='week',repeat_values=[1,3],account_id='11'),self.s,'123');d=loads(p['params']['v'])['data'];self.assertEqual(d['repeat'],{'type':'week','value':[1,3]});self.assertEqual(d['fromid'],11)
 def test_move_book_requires_matching_category(self):
  self.s['books'].append({'bookid':2,'userid':'123','name':'Other'});self.s['categories'].append({'id':22,'bookid':2,'type':0,'name':'Other','level':1})
  with self.assertRaises(ValueError):prepare(self.cmd(book_id='2'),self.s,'123')
  p=prepare(self.cmd(book_id='2',category_id='22'),self.s,'123');self.assertEqual(loads(p['params']['v'])['data']['bookid'],2)
 def test_period_value_without_type_is_not_silently_ignored(self):
  with self.assertRaises(ValueError):prepare(self.cmd(repeat_values=[1]),self.s,'123')
 def test_irrelevant_transfer_account_and_missing_mutation_refused(self):
  for c in [self.cmd(to_account_id='11'),self.cmd()]:
   with self.assertRaises(ValueError):prepare(c,self.s,'123')
 def prepared_after(self):
  p=prepare(self.cmd(repeat_unit='week',repeat_values=[1,3],account_id='11'),self.s,'123');after=copy.deepcopy(self.s);after['repeat']=[loads(p['params']['v'])];return p,after
 def child(self):
  from qianji_agent.operations import make_row
  row=make_row('123','1','100',1792281600,0);row.update(money=Decimal('.02'),assetid=11,cateid=20,packid=300);return row
 def test_new_child_wrong_source_is_not_reported_as_verified(self):
  p,after=self.prepared_after();b=self.child();b.update(assetid=10,money=Decimal('99'));after['bills']=[b]
  with self.assertRaisesRegex(ValueError,'task_child_relation_not_verified'):verify(p,after)
 def test_new_child_requires_matching_balance_and_preserves_old_account(self):
  from decimal import Decimal
  p,after=self.prepared_after();after['bills']=[self.child()]
  with self.assertRaisesRegex(ValueError,'task_balance_not_verified'):verify(p,after)
  after['assets'][1]['money']=Decimal('1.98');self.assertTrue(verify(p,after)['task_execution_observed'])
  after['assets'][0]['money']=Decimal('.99')
  with self.assertRaisesRegex(ValueError,'task_balance_not_verified'):verify(p,after)
 def test_no_new_child_still_requires_related_balances_unchanged(self):
  from decimal import Decimal
  p,after=self.prepared_after();self.assertFalse(verify(p,after)['task_execution_observed'])
  for index in (0,1):
   altered=copy.deepcopy(after);altered['assets'][index]['money']-=Decimal('.01')
   with self.assertRaisesRegex(ValueError,'task_balance_not_verified'):verify(p,altered)
 def test_pack_relation_must_remain_unchanged(self):
  p,after=self.prepared_after();after['repeat'][0]['packid']=301
  with self.assertRaisesRegex(ValueError,'native_fields_not_verified'):verify(p,after)
