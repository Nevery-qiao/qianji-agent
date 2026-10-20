import unittest
from qianji_agent.operations import prepare
from qianji_agent.codec import loads,digest
from test_business import snapshot

# Mirrors the observed native CreditInfo string convention: plain fixed day,
# suffix d for days after statement. Prefix d is not a native date.
def native_date(raw):
 return ('after_statement',int(raw[:-1])) if raw.endswith('d') else ('fixed',int(raw))

class CreditDateTests(unittest.TestCase):
 def setUp(self):
  self.s=snapshot();self.row=self.s['assets'][0];self.row.update(type=2,credit={'statedate':1,'paydate2':'20','limit':100,'statein':0})
 def command(self,**kw):return {'action':'account_update','object_id':'10','expected_version':digest(self.row),**kw}
 def test_new_credit_fixed_day_can_be_parsed_by_native_reader(self):
  p=prepare({'action':'account_create','name':'Card','account_kind':'credit','payment_day':21},self.s,'123');raw=loads(p['params']['v'])['credit']['paydate2'];self.assertEqual(raw,'21');self.assertEqual(native_date(raw),('fixed',21))
 def test_fixed_day_31_and_statement_day_31_supported(self):
  p=prepare(self.command(statement_day=31,payment_day=31),self.s,'123');credit=loads(p['params']['v'])['credit'];self.assertEqual(credit['statedate'],31);self.assertEqual(native_date(credit['paydate2']),('fixed',31))
 def test_relative_day_and_statement_inclusion_have_distinct_semantics(self):
  p=prepare(self.command(payment_after_statement_days=20,statement_inclusive=True),self.s,'123');credit=loads(p['params']['v'])['credit'];self.assertEqual(credit['paydate2'],'20d');self.assertEqual(credit['statein'],1);self.assertEqual(native_date(credit['paydate2']),('after_statement',20))
 def test_conflicting_date_modes_and_invalid_days_rejected(self):
  for kw in [{'payment_day':2,'payment_after_statement_days':3},{'payment_day':32},{'statement_day':0},{'payment_after_statement_days':0},{'statement_inclusive':1}]:
   with self.assertRaises(ValueError):prepare(self.command(**kw),self.s,'123')
 def test_unset_limit_does_not_invent_one_yuan_credit_line(self):
  p=prepare({'action':'account_create','name':'Card','account_kind':'credit'},self.s,'123');self.assertEqual(loads(p['params']['v'])['credit']['limit'],-1)
 def test_created_credit_is_selected_by_nested_values_not_dict_print_order(self):
  from qianji_agent.operations import verify
  p=prepare({'action':'account_create','name':'Card','account_kind':'credit','limit':'2.00','payment_day':31,'statement_day':31},self.s,'123')
  self.s['assets'].append({'id':12,'userid':'123','name':'Card','money':0,'type':2,'stype':200,'incount':1,'currency':'CNY','credit':{'statedate':31,'paydate2':'31','statein':0,'limit':2}})
  self.assertEqual(verify(p,self.s)['object_id'],'12')
 def test_clear_limit_uses_native_unset_value_and_refuses_conflict(self):
  p=prepare(self.command(clear_credit_limit=True),self.s,'123');self.assertEqual(loads(p['params']['v'])['credit']['limit'],-1)
  for kw in [{'clear_credit_limit':False},{'clear_credit_limit':True,'limit':'2.00'}]:
   with self.assertRaises(ValueError):prepare(self.command(**kw),self.s,'123')
