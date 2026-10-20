"""Original-currency refund caps remain separate from destination-account amounts."""
import copy,unittest
from decimal import Decimal
from test_business import snapshot,expense
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import digest,loads

class ForeignRefundTests(unittest.TestCase):
 def setUp(self):
  self.s=snapshot();self.source=prepare(expense(currency='USD',amount='0.02',account_amount='0.14',base_amount='0.14'),self.s,'123',bill_id='100')['row'];self.s['bills']=[self.source];self.s['assets'][0]['money']=Decimal('0.86')
 def command(self,**kw):return {'action':'refund_create','object_id':'100','account_id':'10','currency':'USD','amount':'0.01','account_amount':'0.07','base_amount':'0.07','time':'2026-10-18T08:00:00+08:00',**kw}
 def test_refund_keeps_original_amount_and_native_account_amount(self):
  p=prepare(self.command(),self.s,'123');v=loads(p['params']['v']);self.assertEqual(v['money'],Decimal('0.07'));self.assertEqual(v['currency'],{'ss':'USD','sv':Decimal('0.01'),'ts':'CNY','tv':Decimal('0.07'),'bs':'CNY','bv':Decimal('0.07')});self.assertEqual(p['balances']['10'],Decimal('0.93'))
 def test_original_currency_cap_cannot_be_bypassed_by_small_conversion(self):
  child={'id':101,'userid':'123','bookid':1,'type':20,'money':Decimal('0.07'),'status':2,'cateid':None,'time':1792281600,'createtime':1792281600,'assetid':10,'extra':{'refundsid':100,'curr':{'ss':'USD','sv':Decimal('0.01'),'ts':'CNY','tv':Decimal('0.07'),'bs':'CNY','bv':Decimal('0.07')}}}
  self.s['bills'].append(child);self.source['extra']['rfds']={'101':Decimal('0.07')}
  with self.assertRaisesRegex(ValueError,'refund_exceeds_remaining'):prepare(self.command(amount='0.02',account_amount='0.01',base_amount='0.01'),self.s,'123')
 def test_usd_account_refund_credits_usd_units(self):
  self.s['assets'][0]['currency']='USD';self.s['assets'][0]['money']=Decimal('0.98');self.source['money']=Decimal('0.02');self.source['extra']['curr'].update(ts='USD',tv=Decimal('0.02'))
  p=prepare(self.command(account_amount='0.01'),self.s,'123');self.assertEqual(p['balances']['10'],Decimal('0.99'))
 def test_mismatched_source_currency_and_missing_conversion_are_refused(self):
  for c in [self.command(currency='EUR'),{k:v for k,v in self.command().items() if k!='account_amount'}]:
   with self.assertRaises(ValueError):prepare(c,self.s,'123')
 def test_foreign_refund_edit_uses_new_original_and_account_amounts(self):
  child={'id':101,'userid':'123','bookid':1,'type':20,'money':Decimal('0.07'),'status':2,'cateid':None,'time':1792281600,'createtime':1792281600,'assetid':10,'extra':{'refundsid':100,'curr':{'ss':'USD','sv':Decimal('0.01'),'ts':'CNY','tv':Decimal('0.07'),'bs':'CNY','bv':Decimal('0.07')}}}
  self.s['bills'].append(child);self.source['extra']['rfds']={'101':Decimal('0.07')};self.s['assets'][0]['money']=Decimal('0.93')
  c={**self.command(),'action':'refund_update','object_id':'101','expected_version':digest(child),'amount':'0.02','account_amount':'0.14','base_amount':'0.14'}
  p=prepare(c,self.s,'123');self.assertEqual(p['balances']['10'],Decimal('1.00'));self.assertEqual(p['refund_original_amount'],Decimal('0.02'))

 def test_cross_account_refund_uses_destination_units_and_original_cap(self):
  self.s['assets'][1]['currency']='USD'
  p=prepare(self.command(account_id='11',account_amount='0.01'),self.s,'123')
  self.assertEqual(p['balances']['11'],Decimal('2.01'));self.assertEqual(p['refund_original_amount'],Decimal('0.01'))
 def test_currency_echo_and_parent_relation_are_both_verified(self):
  p=prepare(self.command(),self.s,'123');after=copy.deepcopy(self.s)
  child={'id':101,'userid':'123','bookid':1,'type':20,'money':Decimal('0.07'),'status':2,'cateid':None,'time':1792281600,'createtime':1792281600,'assetid':10,'extra':{'refundsid':100,'curr':loads(p['params']['v'])['currency']}}
  after['bills'].append(child);after['bills'][0]['extra']['rfds']={'101':Decimal('0.07')};after['assets'][0]['money']=Decimal('0.93')
  self.assertEqual(verify(p,after)['object_id'],'101')
  child['extra']['curr']['sv']=Decimal('0.02')
  with self.assertRaisesRegex(ValueError,'native_currency_not_verified'):verify(p,after)
 def test_negative_legacy_refund_cannot_expand_available_amount(self):
  self.source['extra'].pop('curr');self.source['money']=Decimal('.02')
  child={'id':101,'userid':'123','bookid':1,'type':20,'money':Decimal('-.01'),'status':2,'cateid':None,'time':1792281600,'createtime':1792281600,'assetid':10,'extra':{'refundsid':100}}
  self.s['bills'].append(child);self.source['extra']['rfds']={'101':Decimal('-.01')}
  with self.assertRaises(ValueError):prepare({'action':'refund_create','object_id':'100','account_id':'10','amount':'0.03','time':'2026-10-18T08:00:00+08:00'},self.s,'123')
 def test_refund_must_not_silently_ignore_transfer_fee_conversion_field(self):
  for action in ('refund_create','refund_update'):
   with self.assertRaisesRegex(ValueError,'unexpected_fields'):prepare(self.command(action=action,fee_base_amount='99.00'),self.s,'123')
