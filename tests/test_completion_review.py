"""Findings from the one fresh review of the local completion increment."""
import copy,tempfile,unittest
from pathlib import Path
from decimal import Decimal
from test_business import snapshot
from test_engine import Backend
from qianji_agent.operations import prepare
from qianji_agent.engine import Engine
from qianji_agent.codec import digest

class CompletionReviewTests(unittest.TestCase):
 def test_fee_paid_is_not_subtracted_from_remaining_installment_principal(self):
  s=snapshot();s['assets'][1].update(type=2,stype=200)
  task={'id':30,'userid':'123','assetid':11,'type':1,'count':1,'totalcount':2,'status':1,'money':Decimal('5.00'),'fee':Decimal('.01'),'totalmoney':Decimal('10.01'),'totalfee':Decimal('0.03'),'packid':300,'data':{'cateid':20,'feetype':'ave','lefttype':'first'}}
  s['installment']=[task];s['bills']=[{'id':100,'userid':'123','bookid':1,'cateid':20,'assetid':11,'packid':300,'type':0,'money':Decimal('5.03'),'extra':{'fee':Decimal('0.02')}}]
  c={'action':'installment_prepay','object_id':'30','expected_version':digest(task),'book_id':'1','account_id':'10','amount':'5.00','fee':'0.00','time':'2026-10-18T00:00:00+08:00'}
  p=prepare(c,s,'123');self.assertEqual(p['prepay']['principal'],Decimal('5.00'))
  with self.assertRaises(ValueError):prepare({**c,'amount':'4.98'},s,'123')
 def test_incomplete_account_list_does_not_claim_complete(self):
  with tempfile.TemporaryDirectory() as root:
   b=Backend();b.read=lambda route,p:{'list':[{'id':10,'status':0}],'hasmore':1}
   r=Engine(b,'123',Path(root)/'state').query('accounts')
   self.assertEqual(r['state'],'not_executed');self.assertEqual(r['code'],'incomplete_sync')
 def test_malformed_fee_cannot_increase_remaining_principal(self):
  s=snapshot();s['assets'][1].update(type=2,stype=200)
  task={'id':30,'userid':'123','assetid':11,'type':1,'count':1,'totalcount':2,'status':1,'money':Decimal('5.00'),'fee':Decimal('.01'),'totalmoney':Decimal('10.01'),'totalfee':Decimal('0.03'),'packid':300,'data':{'cateid':20,'feetype':'ave','lefttype':'first'}}
  s['installment']=[task];s['bills']=[{'id':100,'userid':'123','bookid':1,'cateid':20,'assetid':11,'packid':300,'type':0,'money':Decimal('5.03'),'extra':{'fee':Decimal('5.04')}}]
  c={'action':'installment_prepay','object_id':'30','expected_version':digest(task),'book_id':'1','account_id':'10','amount':'10.02','fee':'0.00','time':'2026-10-18T00:00:00+08:00'}
  with self.assertRaises(ValueError):prepare(c,s,'123')

class AccountReadBarrierTests(unittest.TestCase):
 def test_incomplete_account_snapshot_blocks_write(self):
  from test_business import expense
  with tempfile.TemporaryDirectory() as root:
   b=Backend();read=b.read
   def incomplete(route,p):
    d=read(route,p)
    if route=='asset/list':d['hasmore']=1
    return d
   b.read=incomplete;r=Engine(b,'123',Path(root)/'state').execute('incomplete',expense())
   self.assertEqual(r['state'],'not_executed');self.assertEqual(b.writes,0)

class FeePolicyAndReadCompletenessTests(unittest.TestCase):
 def test_fee_bearing_prepay_requires_explicit_early_payment_fee(self):
  s=snapshot();s['assets'][1].update(type=2,stype=200)
  task={'id':30,'userid':'123','assetid':11,'type':1,'status':1,'money':Decimal('.02'),'fee':Decimal(0),'totalmoney':Decimal('0.05'),'totalfee':Decimal('0.03'),'totalcount':2,'count':1,'packid':300,'data':{'cateid':20,'feetype':'first','lefttype':'first'}}
  s['installment']=[task];s['bills']=[{'id':100,'userid':'123','bookid':1,'cateid':20,'type':0,'assetid':11,'packid':300,'money':Decimal('0.06'),'extra':{'fee':Decimal('0.03')}}]
  c={'action':'installment_prepay','object_id':'30','expected_version':digest(task),'book_id':'1','account_id':'10','amount':'0.02','time':'2026-10-18T00:00:00+08:00'}
  with self.assertRaises(ValueError):prepare(c,s,'123')
  self.assertEqual(prepare({**c,'fee':'0.00'},s,'123')['prepay']['principal'],Decimal('0.02'))
 def test_hidden_and_finished_truncation_never_claims_all_accounts(self):
  for status,broken_route in [('hidden','asset/list'),('finished','asset/listloan'),('all','asset/listloan')]:
   with self.subTest(status=status),tempfile.TemporaryDirectory() as root:
    b=Backend()
    def read(route,p):return {'list':[],'hasmore':1 if route==broken_route else 0}
    b.read=read;r=Engine(b,'123',Path(root)/'state').query('accounts',{'status':status})
    self.assertEqual(r['code'],'incomplete_sync')
