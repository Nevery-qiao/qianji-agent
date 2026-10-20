import unittest,copy
from decimal import Decimal
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import digest
from test_business import snapshot,expense

class DetailTests(unittest.TestCase):
 def setUp(self):self.s=snapshot()
 def test_statistics_and_budget_are_independent_native_bits(self):
  p=prepare(expense(include_statistics=False,include_budget=True),self.s,'123',bill_id='100')
  self.assertEqual(p['row']['extra']['flag'],1)
  p=prepare(expense(include_statistics=True,include_budget=False),self.s,'123',bill_id='100')
  self.assertEqual(p['row']['extra']['flag'],2)
  p=prepare(expense(include_statistics=False,include_budget=False),self.s,'123',bill_id='100')
  self.assertEqual(p['row']['extra']['flag'],3)
 def test_native_transfer_fee_is_additional_source_debit(self):
  p=prepare(expense(kind='transfer',category_id=None,to_account_id='11',fee='0.01'),self.s,'123',bill_id='100')
  self.assertEqual(p['balances'],{'10':Decimal('0.89'),'11':Decimal('2.10')})
  self.assertEqual(p['row']['extra']['transfee'],Decimal('0.01'))
 def test_flagged_bill_can_be_updated_and_deleted_without_losing_flags(self):
  self.s['bills']=[prepare(expense(),self.s,'123',bill_id='100')['row']];self.s['bills'][0]['extra']={'flag':3}
  p=prepare({'action':'bill_update','object_id':'100','expected_version':digest(self.s['bills'][0]),'amount':'0.20'},self.s,'123')
  self.assertEqual(p['row']['extra'],{'flag':3})
 def test_tag_reference_must_be_active_owned_native_tag(self):
  self.s['tags']=[{'id':'g-a','tags':[{'id':'t-a','userid':'123','groupid':'g-a','name':'tag','status':1}]}]
  p=prepare(expense(tag_ids=['t-a']),self.s,'123',bill_id='100')
  self.assertEqual(p['row']['extra']['tags'][0]['id'],'t-a')
  self.s['tags'][0]['tags'][0]['userid']='other'
  with self.assertRaises(ValueError):prepare(expense(tag_ids=['t-a']),self.s,'123')
 def test_generated_bill_id_collision_refuses_before_dispatch(self):
  self.s['bills']=[prepare(expense(),self.s,'123',bill_id='100')['row']]
  with self.assertRaises(ValueError):prepare(expense(),self.s,'123',bill_id='100')
 def test_attachment_requires_verified_native_reference_and_exact_readback(self):
  self.s['uploaded_keys']=['a'*32]
  p=prepare(expense(image_keys=['a'*32]),self.s,'123',bill_id='100')
  self.assertEqual(p['row']['images'],['a'*32])
  with self.assertRaises(ValueError):prepare(expense(image_keys=['b'*32]),self.s,'123')
  after=copy.deepcopy(self.s);row=copy.deepcopy(p['row']);row['images']=None;after['bills']=[row];after['assets'][0]['money']=Decimal('0.90')
  with self.assertRaises(ValueError):verify(p,after)
 def test_foreign_expense_keeps_original_and_explicit_converted_values(self):
  p=prepare(expense(currency='USD',amount='0.01',account_amount='0.07',base_amount='0.07'),self.s,'123',bill_id='100')
  self.assertEqual(p['row']['extra']['curr'],{'ss':'USD','sv':Decimal('0.01'),'ts':'CNY','tv':Decimal('0.07'),'bs':'CNY','bv':Decimal('0.07')})
  self.assertEqual(p['balances']['10'],Decimal('0.93'));self.assertEqual(p['row']['money'],Decimal('0.07'))
 def test_foreign_expense_delete_uses_account_currency_not_original_amount(self):
  r=prepare(expense(),self.s,'123',bill_id='100')['row'];r['money']=Decimal('0.01');r['extra']={'curr':{'ss':'USD','sv':Decimal('0.01'),'ts':'CNY','tv':Decimal('0.07'),'bs':'CNY','bv':Decimal('0.07')}};self.s['bills']=[r]
  p=prepare({'action':'bill_delete','object_id':'100','expected_version':digest(r)},self.s,'123');self.assertEqual(p['balances']['10'],Decimal('1.07'))
 def test_expense_discount_preserves_paid_amount_and_original_coupon(self):
  p=prepare(expense(amount='0.03',discount='0.01'),self.s,'123',bill_id='100')
  self.assertEqual(p['row']['money'],Decimal('0.03'));self.assertEqual(p['row']['extra']['transfee'],Decimal('-0.01'));self.assertEqual(p['balances']['10'],Decimal('0.97'))
