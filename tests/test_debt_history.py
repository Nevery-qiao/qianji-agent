import unittest,copy
from decimal import Decimal
from test_business import snapshot
from qianji_agent.operations import prepare,make_row,verify
from qianji_agent.codec import digest

class DebtHistoryTests(unittest.TestCase):
 def setUp(self):
  self.s=snapshot();self.debt={'id':12,'userid':'123','name':'Debt','type':5,'stype':51,'currency':'CNY','status':0,'money':Decimal('-.04'),'loan':{'money':Decimal('-.06'),'totalpay':Decimal('.02'),'startdate':'2026-10-18','enddate':''}};self.s['assets'].append(self.debt)
  self.row=make_row('123','1','100',1792281600,9);self.row.update(money=Decimal('.02'),assetid=12,fromid=10,status=1);self.s['bills']=[self.row]
 def cmd(self,**kw):return {'action':'debt_bill_update','object_id':'100','expected_version':digest(self.row),'related_id':'12','related_version':digest(self.debt),'amount':'0.01',**kw}
 def test_repayment_edit_updates_balance_and_paid_principal_contract(self):
  p=prepare(self.cmd(),self.s,'123');self.assertEqual(p['row']['status'],2);self.assertEqual(p['balances']['12'],Decimal('-.05'));self.assertEqual(p['balances']['10'],Decimal('1.01'));self.assertEqual(p['debt_history']['loan']['totalpay'],Decimal('.01'))
 def test_borrow_and_lend_original_principal_change_loan_total(self):
  for typ,subtype,sign in [(6,51,-1),(7,52,1)]:
   self.row.update(type=typ,money=Decimal('.06'),fromid=10 if typ==7 else -1,targetid=10 if typ==6 else -1)
   self.debt.update(stype=subtype,money=Decimal('.04')*sign);self.debt['loan']['money']=Decimal('.06')*sign
   p=prepare(self.cmd(amount='0.07'),self.s,'123');self.assertEqual(p['debt_history']['loan']['money'],Decimal('.07')*sign)
 def test_overpayment_sign_flip_stale_debt_and_linked_extra_refused(self):
  for c in [self.cmd(amount='0.07'),self.cmd(related_version='stale')]:
   with self.assertRaises(ValueError):prepare(c,self.s,'123')
  self.row['extra']={'unknown':1}
  with self.assertRaises(ValueError):prepare(self.cmd(),self.s,'123')
 def test_finished_debt_amount_change_refused_but_metadata_keeps_principal(self):
  self.debt.update(status=1,money=Decimal('0'));self.debt['loan']['totalpay']=Decimal('.06')
  with self.assertRaises(ValueError):prepare(self.cmd(),self.s,'123')
  c=self.cmd(remark='memo');del c['amount'];p=prepare(c,self.s,'123');self.assertEqual(p['debt_history']['loan'],self.debt['loan'])
 def test_verification_checks_loan_totals_as_well_as_visible_balance(self):
  p=prepare(self.cmd(),self.s,'123');after=copy.deepcopy(self.s);after['bills']=[p['row']]
  for aid,m in p['balances'].items():next(a for a in after['assets'] if str(a['id'])==aid)['money']=m
  with self.assertRaises(ValueError):verify(p,after)
  after['assets'][-1]['loan']['totalpay']=Decimal('.01');self.assertEqual(verify(p,after)['object_id'],'100')
