import unittest,copy
from decimal import Decimal
from test_business import snapshot
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import digest,loads
from qianji_agent.engine import public_row
class CreditShareTests(unittest.TestCase):
 def setUp(self):
  self.s=snapshot()
  for a in self.s['assets']:a.update(type=2,status=0,credit={'statedate':1,'paydate2':'20','statein':0,'limit':Decimal('2.00')})
  self.child,self.parent=self.s['assets']
 def cmd(self,**kw):return {'action':'account_update','object_id':'10','expected_version':digest(self.child),'shared_limit_account_id':'11','shared_limit_version':digest(self.parent),**kw}
 def test_share_and_clear_preserve_other_fields_and_parent(self):
  p=prepare(self.cmd(),self.s,'123');v=loads(p['params']['v']);self.assertEqual(v['credit']['shareid'],11);self.assertEqual(v['money'],self.child['money'])
  after=copy.deepcopy(self.s);after['assets'][0]['credit']=v['credit'];self.assertEqual(verify(p,after)['object_id'],'10')
  after['assets'][1]['money']+=Decimal('.01')
  with self.assertRaises(ValueError):verify(p,after)
  self.child['credit']['shareid']=11
  p=prepare(self.cmd(shared_limit_account_id='-1',shared_limit_version=None),self.s,'123');self.assertNotIn('shareid',loads(p['params']['v'])['credit'])
 def test_self_cycle_chain_currency_owner_and_stale_refused(self):
  for kw in [{'shared_limit_account_id':'10'},{'shared_limit_version':'stale'}]:
   with self.assertRaises(ValueError):prepare(self.cmd(**kw),self.s,'123')
  for change in [{'currency':'USD'},{'userid':'other'},{'credit':{**self.parent['credit'],'shareid':10}}]:
   old=copy.deepcopy(self.parent);self.parent.update(change)
   with self.assertRaises(ValueError):prepare(self.cmd(),self.s,'123')
   self.parent.clear();self.parent.update(old)
 def test_member_cannot_silently_change_own_limit_and_root_cannot_be_deleted(self):
  self.child['credit']['shareid']=11
  with self.assertRaises(ValueError):prepare({'action':'account_update','object_id':'10','expected_version':digest(self.child),'limit':'3.00'},self.s,'123')
  with self.assertRaises(ValueError):prepare({'action':'account_delete','object_id':'11','expected_version':digest(self.parent)},self.s,'123')
 def test_shared_reference_is_public_string_id(self):
  self.child['credit']['shareid']=9007199254740993123
  self.assertEqual(public_row(self.child)['credit']['shareid'],'9007199254740993123')
 def test_clear_limit_and_share_are_not_silently_combined(self):
  with self.assertRaises(ValueError):prepare(self.cmd(clear_credit_limit=True),self.s,'123')
 def test_unconfigured_root_cannot_supply_a_verified_shared_limit(self):
  self.parent['credit']['limit']=-1
  with self.assertRaises(ValueError):prepare(self.cmd(),self.s,'123')
