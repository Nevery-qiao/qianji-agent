import copy,io,json,tempfile,unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from mcp import Client
from test_business import snapshot,expense
from test_engine import Backend
from qianji_agent.auth import Session
from qianji_agent.codec import digest,loads
from qianji_agent.engine import Engine
from qianji_agent.operations import prepare,verify,make_row,balance_effect
from qianji_agent.server import build_server,LocalService
from qianji_agent.transport import Transport

class ReviewEngineTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.backend=Backend();self.engine=Engine(self.backend,'123',Path(self.temp.name)/'state')
 def test_unknown_backend_error_keeps_barrier_until_delayed_effect_verified(self):
  class Reply(io.BytesIO):status=200
  class Opener:
   def open(self,*a,**k):return Reply(b'{"ec":8888,"em":"unrecognized-private-error"}')
  pending=[]
  def delayed(route,params):
   self.backend.writes+=1;pending.append(loads(loads(params['v'])['bills']['changelist'])[0])
   Transport(Session('123',{},('a','b','c'),'1580')).write(route,params)
  self.backend.write=delayed
  with patch('qianji_agent.transport.urllib.request.build_opener',return_value=Opener()):r=self.engine.execute('late',expense())
  self.assertEqual(r['state'],'pending_verification');self.assertEqual(self.engine.execute('new',expense())['code'],'previous_result_unknown')
  row=pending[0];self.backend.data['bills']=[row];self.backend.data['assets'][0]['money']-=row['money']
  self.assertEqual(self.engine.operation('late')['state'],'verified');self.assertEqual(self.backend.writes,1)
 def test_task_bound_bill_update_and_copy_blocked_at_engine_entry(self):
  row=prepare(expense(),self.backend.data,'123',bill_id='100')['row'];row['packid']=300;self.backend.data['bills']=[row]
  read=self.backend.read
  for task_route in ('repeat_task/list','installment/list'):
   def related(route,params):return {'list':[{'id':30,'packid':300}]} if route==task_route else read(route,params)
   self.backend.read=related
   for action in ('bill_update','bill_copy'):
    command={'action':action,'object_id':'100','expected_version':digest(row),'remark':'changed'}
    with self.subTest(task=task_route,action=action):
     self.assertEqual(self.engine.preview(command)['state'],'not_executed');self.assertEqual(self.engine.execute(task_route.replace('/','-')+action,command)['state'],'not_executed');self.assertEqual(self.backend.writes,0)
 def test_existing_foreign_or_unknown_repeat_contract_stops_before_write(self):
  self.backend.data['assets'][0].update(currency='CNY')
  native=loads(prepare({'action':'repeat_create','book_id':'1','account_id':'10','category_id':'20','amount':'0.01','start_date':'2026-10-19','end_count':2,'clock':'08:00'},self.backend.data,'123')['params']['v']);native.update(id=30,count=0,status=1,packid=300)
  read=self.backend.read
  for problem in ('currency','account_currency','type','nested_shape'):
   row=copy.deepcopy(native);self.backend.data['assets'][0]['currency']='USD' if problem=='account_currency' else 'CNY'
   if problem=='currency':row['data']['currency']={'ss':'USD','sv':'1.00','ts':'CNY','tv':'7.00'}
   if problem=='type':row['type']=99
   if problem=='nested_shape':row['data']['future_money_rule']={'amount':'9.99'}
   def tasks(route,params):return {'list':[copy.deepcopy(row)]} if route=='repeat_task/list' else read(route,params)
   self.backend.read=tasks
   command={'action':'repeat_update','object_id':'30','expected_version':digest(row),'amount':'2.00'}
   with self.subTest(problem=problem):self.assertEqual(self.engine.execute('repeat-'+problem,command)['state'],'not_executed');self.assertEqual(self.backend.writes,0)

class ReviewBusinessTests(unittest.TestCase):
 def test_installment_contract_checks_all_first_bill_and_plan_dimensions(self):
  base=snapshot();base['assets'][0].update(type=2,stype=200)
  p=prepare({'action':'installment_create','name':'Plan','account_id':'10','category_id':'20','amount':'0.05','periods':2,'time':'2026-10-18T00:00:00+08:00'},base,'123',now=1792281600);p['owner']='123'
  task=loads(p['params']['v']);task.update(id=30,type=1,count=1,packid=300)
  child=make_row('123','1','100',1792281600,0);child.update(money=Decimal('0.03'),assetid=10,cateid=20,packid=300)
  for key,value in [('type',1),('assetid',11),('money',Decimal('0.99')),('userid','other'),('bookid',2),('cateid',21),('starttime',1792281601),('per_money',Decimal('0.01')),('lefttype','last'),('missing_child',None)]:
   after=copy.deepcopy(base);row=copy.deepcopy(child);t=copy.deepcopy(task)
   if key=='starttime':t['starttime']=value
   elif key=='per_money':t['money']=value
   elif key=='lefttype':t['data']['lefttype']=value
   elif key!='missing_child':row[key]=value
   after.update(installment=[t],bills=[] if key=='missing_child' else [row])
   if key!='missing_child':
    for oid,n in balance_effect(row).items():next(a for a in after['assets'] if str(a['id'])==oid)['money']+=n
   with self.subTest(dimension=key),self.assertRaises(ValueError):verify(p,after)
  after=copy.deepcopy(base);after.update(installment=[task],bills=[child]);after['assets'][0]['money']-=Decimal('0.03');self.assertTrue(verify(p,after)['task_execution_observed'])
 def refund_case(self,action):
  s=snapshot();source=prepare(expense(),s,'123',bill_id='100')['row'];source['extra']={'rfds':{'101':Decimal('0.02')}}
  old=make_row('123','1','101',1792281600,20);old.update(money=Decimal('0.02'),assetid=10,extra={'refundsid':100});s['bills']=[source,old]
  command={'action':action,'object_id':'100','account_id':'10','amount':'0.03','time':'2026-10-18T08:00:00+08:00','remark':'new remark'}
  if action=='refund_update':
   prior=copy.deepcopy(old);prior.update(id=102,money=Decimal('0.01'));source['extra']['rfds']['102']=Decimal('0.01');s['bills'].append(prior);command.update(object_id='102',expected_version=digest(prior))
  p=prepare(command,s,'123');p['owner']='123';after=copy.deepcopy(s)
  child=copy.deepcopy(old);child.update(id=102,money=Decimal('0.03'),remark='new remark')
  after['bills']=[b for b in after['bills'] if b['id']!=102]+[child];after['bills'][0]['extra']['rfds']['102']=Decimal('0.03');after['assets'][0]['money']+=Decimal('0.02') if action=='refund_update' else Decimal('0.03')
  return p,after
 def test_refund_create_and_update_preserve_all_old_relations_and_remark(self):
  for action in ('refund_create','refund_update'):
   p,after=self.refund_case(action);self.assertEqual(verify(p,after)['object_id'],'102')
   for problem in ('drop_old','change_old','remark','child_book','child_owner'):
    broken=copy.deepcopy(after)
    if problem=='drop_old':del broken['bills'][0]['extra']['rfds']['101']
    if problem=='change_old':broken['bills'][0]['extra']['rfds']['101']=Decimal('0.01')
    if problem=='remark':broken['bills'][-1]['remark']='other'
    if problem=='child_book':broken['bills'][-1]['bookid']=2
    if problem=='child_owner':broken['bills'][-1]['userid']='other'
    with self.subTest(action=action,problem=problem),self.assertRaises(ValueError):verify(p,broken)

class ReviewPublicMCPTests(unittest.IsolatedAsyncioTestCase):
 async def test_public_tag_query_supplies_version_for_tag_maintenance(self):
  with tempfile.TemporaryDirectory()as d:
   b=Backend();group={'id':'g','name':'Group','userid':'123','tags':[{'id':'t','userid':'123','groupid':'g','name':'Old','color':'3168C2','status':1,'sort':0}]};read=b.read
   def native_read(route,params):return {'list':copy.deepcopy([group])} if route=='tag/list' else read(route,params)
   def native_write(route,params):
    self.assertEqual(route,'tag/submittag');b.writes+=1;group['tags'][0].update(loads(params['v']));return {}
   b.read=native_read;b.write=native_write;e=Engine(b,'123',Path(d)/'state')
   async with Client(build_server(e))as c:
    data=(await c.call_tool('qianji_query',{'kind':'tags'})).structured_content;tag=data['records'][0]['tags'][0]
    self.assertIn('version',tag);self.assertNotIn('userid',tag)
    direct=(await c.call_tool('qianji_query',{'kind':'tags','filters':{'object_id':tag['id']}})).structured_content
    self.assertEqual(direct['records'][0]['version'],tag['version'])
    result=(await c.call_tool('qianji_execute',{'request_id':'tag-edit','command':{'action':'tag_update','object_id':tag['id'],'expected_version':tag['version'],'name':'New'}})).structured_content
    self.assertEqual(result['state'],'verified');self.assertEqual(b.writes,1)

class QueueOwnerGuardTests(unittest.TestCase):
 def test_account_change_during_preparation_blocks_write(self):
  class NativeBackend(Backend):
   instances=[]
   def __init__(self,session):super().__init__();self.session=session;self.instances.append(self)
  with tempfile.TemporaryDirectory()as d,patch('qianji_agent.transport.Transport',NativeBackend),patch('qianji_agent.auth.load_session',side_effect=[Session('123',{},('a','b','c'),'1580'),Session('123',{},('a','b','c'),'1580'),Session('other',{},('a','b','c'),'1580')]):
   service=LocalService(Path(d)/'state');result=service.execute('queued',expense())
   self.assertEqual(result['state'],'not_executed');self.assertEqual(result['code'],'account_changed');self.assertEqual(sum(b.writes for b in NativeBackend.instances),0)

class HistoricalRelationProjectionTests(unittest.TestCase):
 def test_public_prepay_relation_ids_are_discoverable(self):
  from qianji_agent.engine import public_row
  value=public_row({'id':100,'extra':{'presid':101,'pretid':102,'preinstallid':30}})
  self.assertEqual(value['extra'],{'presid':'101','pretid':'102','preinstallid':'30'})

class QueueCurrencyGuardTests(unittest.TestCase):
 def test_base_currency_change_during_preparation_blocks_write(self):
  class NativeBackend(Backend):
   instances=[]
   def __init__(self,session):super().__init__();self.session=session;self.instances.append(self)
  values=[Session('123',{},('a','b','c'),'1580'),Session('123',{},('a','b','c'),'1580'),Session('123',{},('a','b','c'),'1580','USD')]
  with tempfile.TemporaryDirectory()as d,patch('qianji_agent.transport.Transport',NativeBackend),patch('qianji_agent.auth.load_session',side_effect=values):
   result=LocalService(Path(d)/'state').execute('currency-drift',expense())
   self.assertEqual(result['state'],'not_executed');self.assertEqual(sum(b.writes for b in NativeBackend.instances),0)
