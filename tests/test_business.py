import unittest,copy
from decimal import Decimal
from qianji_agent.codec import digest
try:from qianji_agent.operations import prepare,verify
except ImportError:prepare=verify=None

def snapshot():
 return {'books':[{'bookid':1,'name':'Book','userid':'123'}],
 'assets':[{'id':10,'name':'Cash','money':Decimal('1.00'),'currency':'CNY','type':1,'stype':11,'userid':'123'}, {'id':11,'name':'Other','money':Decimal('2.00'),'currency':'CNY','type':1,'stype':11,'userid':'123'}],
 'categories':[{'id':20,'bookid':1,'name':'Expense','type':0,'icon':'http://res3.qianjiapp.com/cateic_yinshi.png','level':1}, {'id':21,'bookid':1,'name':'Income','type':1,'icon':'x','level':1}],
 'bills':[],'deletes':[],'tags':[],'repeat':[],'installment':[]}

def expense(**kw):return {'action':'bill_create','kind':'expense','book_id':'1','account_id':'10','category_id':'20','amount':'0.10','time':'2026-10-18T08:00:00+08:00','remark':'test',**kw}

class BusinessTests(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(prepare,'Product business adapter required');self.s=snapshot()
 def test_expense_expected_balance_and_precise_wire(self):
  p=prepare(expense(),self.s,'123',bill_id='9007199254740993123',now=1792281600)
  self.assertEqual(p['balances'],{'10':Decimal('0.90')});self.assertEqual(p['row']['id'],9007199254740993123)
  self.assertEqual(p['row']['time'],1792281600);self.assertEqual(p['row']['type'],0)
  self.assertIn('9007199254740993123',p['params']['v'])
 def test_income_type_and_reference_pairing(self):
  p=prepare(expense(kind='income',category_id='21'),self.s,'123',bill_id='100',now=1792281600)
  self.assertEqual(p['row']['type'],1);self.assertEqual(p['balances'],{'10':Decimal('1.10')})
  with self.assertRaises(ValueError):prepare(expense(category_id='21'),self.s,'123')
 def test_transfer_both_sides_and_fee(self):
  p=prepare(expense(kind='transfer',category_id=None,to_account_id='11'),self.s,'123',bill_id='100')
  self.assertEqual(p['row']['type'],2);self.assertEqual(p['row']['fromid'],10);self.assertEqual(p['row']['targetid'],11)
  self.assertEqual(p['balances'],{'10':Decimal('0.90'),'11':Decimal('2.10')})
 def test_unknown_fields_and_wrong_owner_prevent_prepare(self):
  for cmd in [expense(uid='other'),expense(amount='0.001'),expense(account_id='99'),expense(currency='USD')]:
   with self.subTest(cmd=cmd),self.assertRaises(ValueError):prepare(cmd,self.s,'123')
  self.s['assets'][0]['userid']='456'
  with self.assertRaises(ValueError):prepare(expense(),self.s,'123')
 def test_version_conflict_and_linked_edit_block(self):
  p=prepare(expense(),self.s,'123',bill_id='100');self.s['bills']=[p['row']]
  with self.assertRaises(ValueError):prepare({'action':'bill_update','object_id':'100','amount':'0.20','expected_version':'stale'},self.s,'123')
 def test_verification_requires_balance_not_just_native_ack(self):
  p=prepare(expense(),self.s,'123',bill_id='100');after=copy.deepcopy(self.s);after['bills']=[p['row']]
  with self.assertRaises(ValueError):verify(p,after)
  after['assets'][0]['money']=Decimal('0.90')
  self.assertEqual(verify(p,after)['object_id'],'100')
 def test_refund_over_remaining_and_wrong_type_blocked(self):
  p=prepare(expense(),self.s,'123',bill_id='100');self.s['bills']=[p['row']]
  with self.assertRaises(ValueError):prepare({'action':'refund_create','object_id':'100','account_id':'10','amount':'0.11','time':'2026-10-18T08:00:00+08:00'},self.s,'123')
 def test_new_book_ambiguous_existing_name_refused(self):
  with self.assertRaises(ValueError):prepare({'action':'book_create','name':'Book'},self.s,'123')
 def test_delete_occupied_book_refused(self):
  self.s['bills']=[prepare(expense(),self.s,'123',bill_id='100')['row']]
  from qianji_agent.codec import digest
  with self.assertRaises(ValueError):prepare({'action':'book_delete','object_id':'1','expected_version':digest(self.s['books'][0])},self.s,'123')
 def test_new_account_decimal_scale_not_mistaken_for_missing_effect(self):
  p=prepare({'action':'account_create','name':'New Cash','amount':'1.00'},self.s,'123')
  after=copy.deepcopy(self.s);after['assets'].append({'id':12,'userid':'123','name':'New Cash','money':Decimal('1'),'type':1,'stype':11,'incount':1,'currency':'CNY'})
  self.assertEqual(verify(p,after)['object_id'],'12')
 def test_native_account_template_and_total_assets_preference(self):
  self.s['account_templates']=[{'name':'微信','type':1,'stype':14,'icon':'http://res3.qianjiapp.com/assetv2/asset_icon_weixin.png','c':'6AB37A'}]
  p=prepare({'action':'account_create','name':'WeChat Wallet','account_kind':'微信','amount':'1.00','include_in_total':True},self.s,'123')
  from qianji_agent.codec import loads
  v=loads(p['params']['v']);self.assertEqual(v['stype'],14);self.assertEqual(v['incount'],1);self.assertEqual(v['icon'],'http://res3.qianjiapp.com/assetv2/asset_icon_weixin.png')
 def test_real_account_defaults_to_included_total_assets(self):
  p=prepare({'action':'account_create','name':'New Account','amount':'1.00'},self.s,'123')
  self.assertEqual(p['expected']['incount'],1)
 def test_child_category_rename_preserves_parent(self):
  from qianji_agent.codec import digest
  self.s['categories'].append({'id':22,'bookid':1,'userid':'123','name':'Child','type':0,'icon':'http://res3.qianjiapp.com/cateic_yinshi.png','level':2,'parentid':20})
  p=prepare({'action':'category_update','object_id':'22','expected_version':digest(self.s['categories'][-1]),'name':'Renamed'},self.s,'123')
  self.assertEqual(p['params']['parentid'],'20')
 def test_account_archive_and_restore_use_native_status_without_balance_change(self):
  r=self.s['assets'][0];r['status']=0
  p=prepare({'action':'account_archive','object_id':'10','expected_version':digest(r)},self.s,'123')
  self.assertEqual(p['route'],'asset/visible');self.assertEqual(p['expected']['status'],2);self.assertEqual(p['balances']['10'],Decimal('1.00'))
  r['status']=2
  p=prepare({'action':'account_restore','object_id':'10','expected_version':digest(r)},self.s,'123');self.assertEqual(p['expected']['status'],0)
 def test_category_parent_move_requires_native_parent_readback(self):
  self.s['categories'] += [{'id':22,'bookid':1,'name':'Child','type':0,'level':2,'parentid':20,'icon':'http://res3.qianjiapp.com/cateic_yinshi.png'},{'id':23,'bookid':1,'name':'Other Parent','type':0,'level':1}]
  child=self.s['categories'][-2]
  p=prepare({'action':'category_move','object_id':'22','expected_version':digest(child),'parent_id':'23'},self.s,'123')
  with self.assertRaises(ValueError):verify(p,self.s)
  child['parentid']=23
  self.assertEqual(verify(p,self.s)['object_id'],'22')
 def test_category_move_has_dedicated_native_route(self):
  self.s['categories'] += [{'id':22,'bookid':1,'name':'Child','type':0,'level':2,'parentid':20,'icon':'http://res3.qianjiapp.com/cateic_yinshi.png'},{'id':23,'bookid':1,'name':'Other Parent','type':0,'level':1}]
  p=prepare({'action':'category_move','object_id':'22','expected_version':digest(self.s['categories'][-2]),'parent_id':'23'},self.s,'123')
  self.assertEqual(p['route'],'category/movesubcate');self.assertEqual(p['params'],{'did':'22','parentid':'23'})
 def test_book_visibility_uses_native_toggle_with_explicit_expected_state(self):
  b=self.s['books'][0];b['visible']=1
  p=prepare({'action':'book_archive','object_id':'1','expected_version':digest(b)},self.s,'123');self.assertEqual(p['route'],'book/visible');self.assertEqual(p['expected']['visible'],0)
  with self.assertRaises(ValueError):verify(p,self.s)
  b['visible']=0;self.assertEqual(verify(p,self.s)['object_id'],'1')
  p=prepare({'action':'book_restore','object_id':'1','expected_version':digest(b)},self.s,'123');self.assertEqual(p['expected']['visible'],1)
