import copy, unittest
from decimal import Decimal
import test_installment_bills
from qianji_agent.operations import prepare, verify
from qianji_agent.codec import digest

class ScheduledRefundDeleteTests(unittest.TestCase):
 def setUp(self):
  f=test_installment_bills.InstallmentBillTests();f.setUp();self.s=f.s;self.source=f.row
  self.source['extra']['rfds']={'101':Decimal('.01')}
  self.refund=copy.deepcopy(self.source);self.refund.update(id=101,type=20,assetid=10,money=Decimal('.01'),extra={'refundsid':100,'tags':[]})
  self.s['bills'].append(self.refund);self.s['assets'][0]['money']=Decimal('1.01')
 def command(self):return {'action':'bill_delete','object_id':'101','expected_version':digest(self.refund)}
 def test_refund_delete_checks_relation_and_preserves_schedule(self):
  p=prepare(self.command(),self.s,'123');after=copy.deepcopy(self.s)
  after['bills']=after['bills'][:1];after['bills'][0]['extra'].pop('rfds');after['deletes']=[101];after['assets'][0]['money']=Decimal('1.00')
  self.assertTrue(verify(p,after)['deleted'])
  after['installment'][0]['count']=2
  with self.assertRaisesRegex(ValueError,'scheduled_task_changed'):verify(p,after)
 def test_invalid_relation_and_ambiguous_schedule_refused(self):
  for corruption in ('amount','pack','duplicate','extra'):
   s=copy.deepcopy(self.s)
   if corruption=='amount':s['bills'][0]['extra']['rfds']['101']=Decimal('.02')
   elif corruption=='pack':s['bills'][0]['packid']=301
   elif corruption=='duplicate':s['repeat']=[{'id':31,'packid':300}]
   else:s['bills'][1]['extra']['preinstallid']=30
   with self.subTest(corruption=corruption),self.assertRaises(ValueError):prepare(self.command(),s,'123')
 def test_generic_update_still_refused(self):
  with self.assertRaises(ValueError):prepare({**self.command(),'action':'bill_update','remark':'changed'},self.s,'123')
