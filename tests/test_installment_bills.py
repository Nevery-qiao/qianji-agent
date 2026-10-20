import copy,unittest
from decimal import Decimal
from test_business import snapshot,expense
from qianji_agent.operations import prepare,verify
from qianji_agent.codec import digest,loads
from qianji_agent.models import Command

class InstallmentBillTests(unittest.TestCase):
 def setUp(self):
  self.s=snapshot();self.s['assets'][1].update(type=2,stype=200,money=Decimal('-.06'))
  self.task={'id':30,'userid':'123','name':'Plan','assetid':11,'type':1,'count':1,'totalcount':2,'totalmoney':Decimal('.05'),'totalfee':Decimal('.03'),'money':Decimal('.02'),'fee':Decimal('0'),'status':1,'packid':300,'data':{'cateid':20,'feetype':'first','lefttype':'first'}}
  self.row=prepare(expense(account_id='11',amount='0.06'),self.s,'123',bill_id='100')['row'];self.row.update(packid=300,extra={'fee':Decimal('.03')});self.s.update(installment=[self.task],bills=[self.row])
 def cmd(self,action,**kw):return {'action':'installment_bill_'+action,'object_id':'100','expected_version':digest(self.row),'related_id':'30','related_version':digest(self.task),**kw}
 def test_update_preserves_plan_and_fee_and_verifies_fee_readback(self):
  c=self.cmd('update',amount='0.07',include_budget=False);Command(**c);p=prepare(c,self.s,'123');self.assertEqual(p['row']['extra']['fee'],Decimal('.03'));self.assertEqual(p['row']['packid'],300)
  after=copy.deepcopy(self.s);after['bills']=[p['row']];after['assets'][1]['money']=Decimal('-.07');self.assertTrue(verify(p,after)['balances_verified'])
  after['bills'][0]['extra']['fee']=Decimal('.02')
  with self.assertRaises(ValueError):verify(p,after)
 def test_copy_detaches_total_without_installment_fee_split(self):
  p=prepare(self.cmd('copy'),self.s,'123',bill_id='101');self.assertEqual(p['row']['packid'],-1);self.assertNotIn('fee',p['row']['extra'] or {});self.assertEqual(p['row']['money'],Decimal('.06'));self.assertEqual(self.row['extra']['fee'],Decimal('.03'))
  after=copy.deepcopy(self.s);after['bills'].append(p['row']);after['assets'][1]['money']=Decimal('-.12');self.assertTrue(verify(p,after)['balances_verified'])
  after['installment'][0]['count']=2
  with self.assertRaises(ValueError):verify(p,after)
 def test_delete_keeps_original_plan_and_count(self):
  p=prepare(self.cmd('delete'),self.s,'123');after=copy.deepcopy(self.s);after['bills']=[];after['deletes']=[100];after['assets'][1]['money']=Decimal('0');self.assertTrue(verify(p,after)['deleted'])
  after['installment'][0]['count']=0
  with self.assertRaises(ValueError):verify(p,after)
 def test_guard_latest_parent_and_bill_versions_ambiguity_and_fee_floor(self):
  for c in [self.cmd('update',amount='0.02'),self.cmd('delete',related_version='stale'),self.cmd('update',amount='0.07',expected_version='stale'),self.cmd('update',fee='0.01'),self.cmd('copy',amount='0.01')]:
   with self.subTest(command=c),self.assertRaises(ValueError):prepare(c,self.s,'123')
  self.s['repeat']=[{'id':31,'packid':300}]
  with self.assertRaises(ValueError):prepare(self.cmd('delete'),self.s,'123')
 def test_linked_refund_and_prepay_bill_cannot_bypass_relations(self):
  for extra in [{'fee':Decimal('.03'),'rfds':{'102':Decimal('.01')}},{'fee':Decimal('.03'),'preinstallid':30}]:
   self.row['extra']=extra
   with self.assertRaises(ValueError):prepare(self.cmd('update',remark='Edited'),self.s,'123')
 def test_wrong_parent_kind_and_prepayed_task_are_refused(self):
  self.task['type']=0
  with self.assertRaises(ValueError):prepare(self.cmd('delete'),self.s,'123')
  self.task['type']=1;self.task['data']['prepay']=1
  with self.assertRaises(ValueError):prepare(self.cmd('delete'),self.s,'123')
 def test_prepay_uses_unchanged_schedule_after_history_edit_or_delete(self):
  for changed in ['edit','delete']:
   s=copy.deepcopy(self.s)
   if changed=='edit':s['bills'][0]['money']=Decimal('.07')
   else:s['bills']=[]
   c={'action':'installment_prepay','object_id':'30','expected_version':digest(self.task),'book_id':'1','account_id':'10','amount':'0.02','fee':'0.00','time':'2026-10-18T08:00:00+08:00'}
   self.assertEqual(prepare(c,s,'123')['prepay']['principal'],Decimal('.02'))
   with self.assertRaises(ValueError):prepare({**c,'amount':'0.01'},s,'123')
 def test_schedule_principal_remainder_last_and_unknown_shape(self):
  from qianji_agent.linked import installment_remaining
  self.task.update(totalmoney=Decimal('.05'),totalfee=Decimal(0),money=Decimal('.03'));self.task['data'].update(lefttype='last',feetype='ave');self.assertEqual(installment_remaining(self.task,self.s,'123'),Decimal('.03'))
  self.task['data']['lefttype']='unknown'
  with self.assertRaises(ValueError):installment_remaining(self.task,self.s,'123')
 def test_missing_schedule_fields_and_wrong_next_amount_are_rejected(self):
  from qianji_agent.linked import installment_remaining
  for key in ('userid','type','status','money','fee'):
   task=copy.deepcopy(self.task);task.pop(key)
   with self.subTest(missing=key),self.assertRaises(ValueError):installment_remaining(task,self.s,'123')
  for key in ('lefttype','feetype'):
   task=copy.deepcopy(self.task);task['data'].pop(key)
   with self.subTest(missing=key),self.assertRaises(ValueError):installment_remaining(task,self.s,'123')
  for key in ('money','fee'):
   task=copy.deepcopy(self.task);task[key]=Decimal('.99')
   with self.assertRaises(ValueError):installment_remaining(task,self.s,'123')
 def test_copy_unexpected_fee_or_link_is_never_verified(self):
  p=prepare(self.cmd('copy'),self.s,'123',bill_id='101')
  for extra in [{'fee':Decimal('.03')},{'preinstallid':30},{'refundsid':102}]:
   after=copy.deepcopy(self.s);copied=copy.deepcopy(p['row']);copied['extra']=extra;after['bills'].append(copied);after['assets'][1]['money']=Decimal('-.12')
   with self.subTest(extra=extra),self.assertRaises(ValueError):verify(p,after)
 def test_missing_owners_or_wrong_account_owner_refused_for_delete(self):
  for target in ('task','bill','account'):
   s=copy.deepcopy(self.s);row=s['installment'][0]if target=='task'else s['bills'][0]if target=='bill'else s['assets'][1];row.pop('userid')
   c=self.cmd('delete',expected_version=digest(s['bills'][0]),related_version=digest(s['installment'][0]))
   with self.subTest(missing_owner=target),self.assertRaises(ValueError):prepare(c,s,'123')
  self.s['assets'][1]['userid']='other'
  with self.assertRaises(ValueError):prepare(self.cmd('delete'),self.s,'123')
 def test_completed_plan_not_exposed_as_active_maintenance(self):
  self.task['count']=2
  with self.assertRaises(ValueError):prepare(self.cmd('delete'),self.s,'123')
 def test_detached_fee_and_normal_markers_can_delete_but_refund_cannot(self):
  self.s['installment']=[];self.row['extra']['flag']=3
  c={'action':'bill_delete','object_id':'100','expected_version':digest(self.row)}
  p=prepare(c,self.s,'123');self.assertEqual(p['balances']['11'],Decimal(0))
  self.row['extra']['rfds']={'102':Decimal('.01')}
  with self.assertRaises(ValueError):prepare({**c,'expected_version':digest(self.row)},self.s,'123')
 def test_all_prepay_commands_require_explicit_current_fee(self):
  self.task.update(totalfee=Decimal(0),fee=Decimal(0));self.task['data']['feetype']='ave'
  c={'action':'installment_prepay','object_id':'30','expected_version':digest(self.task),'book_id':'1','account_id':'10','amount':'0.02','time':'2026-10-18T08:00:00+08:00'}
  with self.assertRaises(ValueError):prepare(c,self.s,'123')
  self.assertEqual(prepare({**c,'fee':'0.00'},self.s,'123')['prepay']['principal'],Decimal('.02'))
