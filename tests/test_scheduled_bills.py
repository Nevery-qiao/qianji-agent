import unittest,copy
from decimal import Decimal
from test_business import snapshot,expense
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import digest
class ScheduledBillTests(unittest.TestCase):
 def setUp(self):
  self.s=snapshot();self.row=prepare(expense(),self.s,'123',bill_id='100')['row'];self.row['packid']=300;self.s['bills']=[self.row]
  self.task={'id':30,'userid':'123','packid':300,'type':0,'count':1,'status':1,'data':{'bookid':1,'money':Decimal('.10')}};self.s['repeat']=[self.task]
 def command(self,a,**kw):return {'action':'scheduled_bill_'+a,'object_id':'100','expected_version':digest(self.row),'related_id':'30','related_version':digest(self.task),**kw}
 def test_edit_keeps_link_and_requires_parent_unchanged(self):
  p=prepare(self.command('update',amount='0.20'),self.s,'123');self.assertEqual(p['row']['packid'],300);self.assertEqual(p['balances']['10'],Decimal('.90'))
  after=copy.deepcopy(self.s);after['bills']=[p['row']];after['assets'][0]['money']=Decimal('.90');self.assertEqual(verify(p,after)['object_id'],'100')
  after['repeat'][0]['count']=2
  with self.assertRaises(ValueError):verify(p,after)
 def test_copy_detaches_new_bill_from_schedule(self):
  p=prepare(self.command('copy'),self.s,'123',bill_id='101');self.assertEqual(p['row']['packid'],-1);self.assertEqual(p['object_id'],'101');self.assertEqual(self.row['packid'],300)
 def test_delete_does_not_delete_or_decrement_task(self):
  p=prepare(self.command('delete'),self.s,'123');after=copy.deepcopy(self.s);after['bills']=[];after['deletes']=[100];after['assets'][0]['money']=Decimal('1.10');self.assertTrue(verify(p,after)['deleted'])
  after['repeat']=[]
  with self.assertRaises(ValueError):verify(p,after)
 def test_wrong_parent_and_stale_versions_cannot_bypass_generic_guard(self):
  for c in [self.command('update',related_version='stale',amount='0.20'),self.command('delete',related_id='31')]:
   with self.assertRaises(ValueError):prepare(c,self.s,'123')
  with self.assertRaises(ValueError):prepare({'action':'bill_delete','object_id':'100','expected_version':digest(self.row)},self.s,'123')
