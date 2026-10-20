"""Native three-period plans expose remaining totals, not the next instalment.

The 9.00/0.60 fixture reproduces the independently observed 2026-10-19
failure: after the first 3.20 bill, the task reports money=6.00, fee=0.40.
All identities and account data here are synthetic.
"""
import copy
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from qianji_agent.codec import digest, loads
from qianji_agent.engine import Engine
from qianji_agent.linked import installment_remaining
from qianji_agent.operations import prepare, verify
from test_business import expense, snapshot
from test_engine import Backend


class InstallmentRemainingSummaryTests(unittest.TestCase):
 def fixture(self, *, rounding=False, zero_fee=False, fee_method='average'):
  before=snapshot();before['assets'][0].update(type=2)
  command={'action':'installment_create','name':'Three periods','account_id':'10',
           'category_id':'20','amount':'10.00' if rounding else '9.00',
           'fee':'0.00' if zero_fee else '0.03' if rounding else '0.60','periods':3,
           'fee_method':'last' if rounding and not zero_fee else fee_method,
           'remainder':'last','time':'2026-10-19T00:00:00+08:00'}
  plan=prepare(command,before,'123');plan.update(owner='123',extended=True)
  task=loads(plan['params']['v'])
  task.update(id=30,type=1,count=1,packid=300,
              money=Decimal('6.67' if rounding else '6.00'),
              fee=Decimal('0.00' if zero_fee else '0.03' if rounding else '0.40'))
  child=prepare(expense(),before,'123',bill_id='100')['row']
  child.update(packid=300,money=Decimal('3.33' if rounding else '3.00' if zero_fee else '3.20'),
               extra=None if zero_fee or rounding else {'fee':Decimal('0.20')})
  after=copy.deepcopy(before);after.update(installment=[task],bills=[child])
  after['assets'][0]['money']=Decimal('-2.33' if rounding else '-2.00' if zero_fee else '-2.20')
  return command,plan,after

 def test_create_verifies_remaining_principal_and_fee_after_first_of_three(self):
  _,plan,after=self.fixture()
  self.assertEqual(verify(plan,after)['related_bill_ids'],['100'])

 def test_prepay_accepts_remaining_summary_and_returns_all_remaining_principal(self):
  _,_,after=self.fixture()
  self.assertEqual(installment_remaining(after['installment'][0],after,'123'),Decimal('6.00'))

 def test_remaining_totals_include_last_period_rounding_and_deferred_fee(self):
  _,plan,after=self.fixture(rounding=True)
  self.assertEqual(verify(plan,after)['object_id'],'30')
  self.assertEqual(installment_remaining(after['installment'][0],after,'123'),Decimal('6.67'))

 def test_next_period_values_are_not_accepted_as_remaining_totals(self):
  _,plan,after=self.fixture()
  after['installment'][0].update(money=Decimal('3.00'),fee=Decimal('0.20'))
  with self.assertRaises(ValueError):verify(plan,after)
  with self.assertRaises(ValueError):installment_remaining(after['installment'][0],after,'123')

 def test_remaining_fee_corruption_is_not_ignored(self):
  _,plan,after=self.fixture()
  after['installment'][0]['fee']=Decimal('0.39')
  with self.assertRaises(ValueError):verify(plan,after)
  with self.assertRaises(ValueError):installment_remaining(after['installment'][0],after,'123')

 def test_pending_creation_is_reconciled_by_reading_without_another_write(self):
  command,plan,after=self.fixture()
  backend=Backend();backend.data=after
  original_read=backend.read
  def read(route,params):
   if route=='installment/list':return {'list':copy.deepcopy(after['installment']),'hasmore':0}
   return original_read(route,params)
  backend.read=read
  with tempfile.TemporaryDirectory() as directory:
   engine=Engine(backend,'123',Path(directory)/'journal')
   engine.journal.start('original-request',digest(command),plan)
   result=engine.operation('original-request')
   self.assertEqual(result['state'],'verified')
   self.assertEqual(result['object_id'],'30')
   self.assertEqual(engine.operation('original-request')['object_id'],'30')
   self.assertEqual(backend.writes,0)

 def test_zero_fee_creation_accepts_omitted_fee_allocation_only(self):
  for method in ('average','first','last'):
   with self.subTest(method=method):
    _,plan,after=self.fixture(zero_fee=True,fee_method=method)
    after['installment'][0]['data'].pop('feetype')
    self.assertEqual(verify(plan,after)['object_id'],'30')

 def test_zero_fee_prepay_accepts_native_omitted_fee_allocation(self):
  _,_,after=self.fixture(zero_fee=True)
  after['installment'][0]['data'].pop('feetype')
  self.assertEqual(installment_remaining(after['installment'][0],after,'123'),Decimal('6.00'))

 def test_native_ten_zero_fee_last_remainder_combination(self):
  _,plan,after=self.fixture(rounding=True,zero_fee=True)
  after['installment'][0]['data'].pop('feetype')
  self.assertEqual(verify(plan,after)['related_bill_ids'],['100'])
  self.assertEqual(installment_remaining(after['installment'][0],after,'123'),Decimal('6.67'))

 def test_nonzero_fee_still_requires_allocation_metadata(self):
  _,plan,after=self.fixture()
  after['installment'][0]['data'].pop('feetype')
  with self.assertRaises(ValueError):verify(plan,after)
  with self.assertRaises(ValueError):installment_remaining(after['installment'][0],after,'123')

 def test_zero_fee_does_not_accept_an_explicit_unknown_allocation(self):
  _,plan,after=self.fixture(zero_fee=True)
  after['installment'][0]['data']['feetype']='unknown'
  with self.assertRaises(ValueError):verify(plan,after)
  with self.assertRaises(ValueError):installment_remaining(after['installment'][0],after,'123')

 def test_missing_zero_fee_metadata_cannot_hide_missing_financial_values(self):
  for field in ('totalfee','fee','money'):
   with self.subTest(field=field):
    _,plan,after=self.fixture(zero_fee=True)
    task=after['installment'][0];task['data'].pop('feetype');task.pop(field)
    with self.assertRaises(ValueError):verify(plan,after)
    with self.assertRaises(ValueError):installment_remaining(task,after,'123')


if __name__=='__main__':unittest.main()
