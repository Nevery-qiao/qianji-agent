import copy,unittest
from decimal import Decimal
from test_business import snapshot,expense
from qianji_agent.operations import prepare
from qianji_agent.codec import digest
from qianji_agent.models import Command

class CrossFeeTests(unittest.TestCase):
 def setUp(self):self.s=snapshot();self.s['assets'][1]['currency']='USD'
 def command(self,**kw):return expense(kind='transfer',category_id=None,to_account_id='11',currency='USD',amount='0.01',account_amount='0.07',base_amount='0.07',fee='0.01',fee_base_amount='0.01',**kw)
 def test_source_gross_is_deducted_once(self):
  p=prepare(self.command(),self.s,'123',bill_id='100');r=p['row'];self.assertEqual(r['money'],Decimal('.07'));self.assertEqual(r['extra']['curr']['sv'],Decimal('.08'));self.assertEqual(r['extra']['curr']['bv'],Decimal('.08'));self.assertEqual(p['balances'],{'10':Decimal('.92'),'11':Decimal('2.01')})
 def test_foreign_source_fee_requires_explicit_base_value(self):
  c=self.command();c.update(account_id='11',to_account_id='10',currency='CNY',amount='0.07',account_amount='0.01',fee_base_amount='0.07');p=prepare(c,self.s,'123');self.assertEqual(p['balances']['11'],Decimal('1.98'));self.assertEqual(p['row']['extra']['curr']['bv'],Decimal('.14'))
  del c['fee_base_amount']
  with self.assertRaises(ValueError):prepare(c,self.s,'123')
 def test_same_currency_fee_base_cannot_disagree(self):
  c=self.command();c['fee_base_amount']='0.02'
  with self.assertRaises(ValueError):prepare(c,self.s,'123')
 def test_delete_reverses_gross_and_copy_preserves_fee(self):
  p=prepare(self.command(),self.s,'123',bill_id='100');r=p['row'];self.s['bills']=[r]
  for a,v in p['balances'].items():next(x for x in self.s['assets'] if str(x['id'])==a)['money']=v
  deleted=prepare({'action':'bill_delete','object_id':'100','expected_version':digest(r)},self.s,'123');self.assertEqual(deleted['balances'],{'10':Decimal('1.00'),'11':Decimal('2.00')})
  copied=prepare({'action':'bill_copy','object_id':'100'},self.s,'123',bill_id='101');self.assertEqual(copied['row']['extra'],r['extra'])
 def test_fee_edit_requires_new_conversions_and_public_contract_accepts_field(self):
  p=prepare(self.command(),self.s,'123',bill_id='100');r=p['row'];self.s['bills']=[r]
  with self.assertRaises(ValueError):prepare({'action':'bill_update','object_id':'100','expected_version':digest(r),'fee':'0.02'},self.s,'123')
  self.assertEqual(Command(**self.command()).fee_base_amount,'0.01')
 def test_unrepresentable_independent_fee_exchange_rate_is_refused(self):
  c=self.command();c.update(account_id='11',to_account_id='10',currency='CNY',amount='7.00',account_amount='1.00',base_amount='7.00',fee='0.10',fee_base_amount='1.00')
  with self.assertRaises(ValueError):prepare(c,self.s,'123')
 def test_cent_rounded_fee_rate_still_matches_native_statistical_amounts(self):
  c=self.command();c.update(account_id='11',to_account_id='10',currency='CNY',amount='0.20',account_amount='0.03',base_amount='0.20',fee='0.01',fee_base_amount='0.07')
  p=prepare(c,self.s,'123');self.assertEqual(p['row']['extra']['curr']['bv'],Decimal('.27'))
