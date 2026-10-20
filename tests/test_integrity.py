import unittest,copy
from decimal import Decimal
from test_business import snapshot,expense
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import digest
class IntegrityTests(unittest.TestCase):
 def setUp(self):self.s=snapshot()
 def test_foreign_refund_fails_before_native_cny_adapter(self):
  p=prepare(expense(currency='USD',account_amount='0.10',base_amount='0.10'),self.s,'123',bill_id='100');self.s['bills']=[p['row']]
  with self.assertRaisesRegex(ValueError,'refund_requires_cny_expense'):prepare({'action':'refund_create','object_id':'100','account_id':'10','amount':'0.01','time':'2026-10-18T08:00:00+08:00'},self.s,'123')
 def test_default_book_rename_cannot_be_misread_as_create(self):
  b={'bookid':-1,'name':'Default','userid':'123'};self.s['books'].append(b)
  with self.assertRaisesRegex(ValueError,'default_book_rename_requires_adapter'):prepare({'action':'book_rename','object_id':'-1','name':'New','expected_version':digest(b)},self.s,'123')
 def test_root_with_children_cannot_be_reparented_into_third_level(self):
  self.s['categories'] += [{'id':22,'bookid':1,'name':'Child','type':0,'level':2,'parentid':20},{'id':23,'bookid':1,'name':'Parent2','type':0,'level':1}]
  root=self.s['categories'][0]
  with self.assertRaisesRegex(ValueError,'category_has_children'):prepare({'action':'category_update','object_id':'20','name':'Renamed','parent_id':'23','expected_version':digest(root)},self.s,'123')
 def test_created_object_from_other_owner_cannot_verify(self):
  p=prepare({'action':'account_create','name':'New','amount':'1.00'},self.s,'123');p['owner']='123'
  self.s['assets'].append({'id':12,'userid':'456','name':'New','type':1,'stype':11,'incount':1,'money':Decimal('1.00'),'currency':'CNY'})
  with self.assertRaisesRegex(ValueError,'owner_mismatch'):verify(p,self.s)
 def test_foreign_bill_edit_requires_new_explicit_conversion(self):
  p=prepare(expense(currency='USD',account_amount='0.70',base_amount='0.70'),self.s,'123',bill_id='100');r=p['row'];self.s['bills']=[r]
  c={'action':'bill_update','object_id':'100','expected_version':digest(r),'currency':'USD','amount':'0.20','account_amount':'1.40','base_amount':'1.40'}
  out=prepare(c,self.s,'123');self.assertEqual(out['row']['extra']['curr']['sv'],Decimal('0.20'));self.assertEqual(out['balances']['10'],Decimal('0.30'))
 def test_unsupported_foreign_account_math_cannot_dispatch_delete(self):
  p=prepare(expense(),self.s,'123',bill_id='100');self.s['bills']=[p['row']];self.s['assets'][0]['currency']='USD'
  with self.assertRaisesRegex(ValueError,'currency_adapter_required'):prepare({'action':'bill_delete','object_id':'100','expected_version':digest(p['row'])},self.s,'123')
 def test_related_debt_row_owner_must_match(self):
  from qianji_agent.operations import make_row
  row=make_row('123','1','100',1792281600,9);row.update(money=Decimal('0.02'),assetid=11,fromid=10)
  p={'collection':'bills','object_id':'100','expected':{},'rows':[row],'owner':'123','balances':{}}
  second=copy.deepcopy(row);second['id']=101;p['rows'].append(second)
  child=copy.deepcopy(second);child['userid']='456';self.s['bills']=[row,child]
  with self.assertRaisesRegex(ValueError,'owner_mismatch'):verify(p,self.s)
