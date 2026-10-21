import json, tempfile, threading, time, unittest, urllib.request, urllib.error, socket
from pathlib import Path
import uvicorn
from qianji_agent.remote import build_remote_app, ReadOnlyService

TOKEN='synthetic-test-token-0123456789-abcdef'
class Fake:
 def __init__(self): self.calls=[]
 def query(self,kind,filters=None):self.calls.append(('query',kind));return {'state':'read','total':1,'records':[]}
 def recovery_list(self,*a):self.calls.append(('list',a));return {'state':'read','records':[],'total':0,'next_offset':None}
 def account_review(self):self.calls.append(('review',));return {'state':'read','account_review':{'current':True,'contract':'continuation-v1','scope_id':'same-original-scope','accounts':[]}}
 def account_review_summary(self):return {'current':False}
 def recovery_scheduler(self,*a,**kw):return {'state':'read','recovery':{},'tracking':{'action':'none'}}
 def execute(self,*a):raise AssertionError('write reached backend')
 def preview(self,*a):raise AssertionError('preview reached backend')
 def operation(self,*a):raise AssertionError('status reached backend')
 def recovery_ack(self,*a):raise AssertionError('ack reached backend')

class RemoteTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'token';self.path.write_text(TOKEN);self.path.chmod(0o600);self.fake=Fake()
  self.app=build_remote_app(self.fake,self.path,'https://readonly.example.com')
  sock=socket.socket();sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
  self.server=uvicorn.Server(uvicorn.Config(self.app,log_level='critical',access_log=False,proxy_headers=False))
  self.thread=threading.Thread(target=self.server.run,kwargs={'sockets':[sock]},daemon=True);self.thread.start()
  self.addCleanup(self.stop)
  for _ in range(100):
   if self.server.started:break
   time.sleep(.01)
  self.assertTrue(self.server.started)
 def stop(self):self.server.should_exit=True;self.thread.join(3)
 def request(self,body=None,token=TOKEN,host='readonly.example.com',origin=None,method='POST'):
  headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','Host':host}
  if token is not None:headers['Authorization']='Bearer '+token
  if origin is not None:headers['Origin']=origin
  data=json.dumps(body).encode() if body is not None else None
  try:
   with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{self.port}/mcp',data=data,headers=headers,method=method),timeout=3) as r:return r.status,json.loads(r.read() or b'{}')
  except urllib.error.HTTPError as e:return e.code,e.read().decode()
 def rpc(self,method,params=None):return self.request({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
 def test_missing_wrong_and_revoked_auth(self):
  for token in [None,'wrong']:
   self.assertEqual(self.request({},token=token)[0],401)
  self.path.unlink();self.assertEqual(self.request({})[0],401);self.assertEqual(self.fake.calls,[])
 def test_host_and_origin_protection(self):
  self.assertEqual(self.request({},host='evil.example.com')[0],421)
  self.assertEqual(self.request({},origin='https://evil.example.com')[0],403)
  self.assertEqual(self.fake.calls,[])
 def test_initialize_and_exact_five_tools(self):
  status,r=self.rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'test','version':'1'}});self.assertEqual(status,200)
  status,r=self.rpc('tools/list');self.assertEqual(status,200)
  self.assertEqual({t['name'] for t in r['result']['tools']},{'qianji_connection','qianji_capabilities','qianji_query','qianji_recovery_list','qianji_account_review'})
 def test_forged_mutating_tools_cannot_reach_backend(self):
  for name in ['qianji_execute','qianji_preview','qianji_operation_status','qianji_recovery_ack','qianji_recovery_scheduler','raw_request']:
   status,r=self.rpc('tools/call',{'name':name,'arguments':{}});self.assertEqual(status,200);self.assertTrue(r.get('error') or r.get('result',{}).get('isError'),name)
  self.assertEqual(self.fake.calls,[])
 def test_allowed_calls_and_remote_capabilities_are_readonly(self):
  for name,args in [('qianji_connection',{}),('qianji_query',{'kind':'books','filters':{'limit':1}}),('qianji_recovery_list',{'offset':0,'limit':100}),('qianji_account_review',{})]:
   status,r=self.rpc('tools/call',{'name':name,'arguments':args});self.assertEqual(status,200);self.assertFalse(r['result'].get('isError'),str(r))
  _,r=self.rpc('tools/call',{'name':'qianji_capabilities','arguments':{}})
  self.assertEqual(r['result']['structuredContent']['operations'],[])
  self.assertEqual(r['result']['structuredContent']['access_mode'],'remote_readonly')
 def test_service_refuses_bypass_and_nonstatus_scheduler(self):
  service=ReadOnlyService(self.fake)
  for name in ['execute','preview','operation','recovery_ack']:
   with self.assertRaises(PermissionError):getattr(service,name)('forged')
  with self.assertRaises(PermissionError):service.recovery_scheduler('record')
 def test_private_token_file_required(self):
  self.path.chmod(0o644)
  self.assertEqual(self.request({})[0],401)

class ExistingJournalTests(unittest.TestCase):
 def test_missing_original_journal_never_creates_empty_one(self):
  from qianji_agent.remote import ExistingLocalService
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'missing'
   with self.assertRaises(ValueError):ExistingLocalService(root)
   self.assertFalse(root.exists())
 def test_removed_original_journal_is_rejected_before_auth(self):
  from qianji_agent.remote import ExistingLocalService
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);root.chmod(0o700);db=root/'operations.sqlite3';db.write_bytes(b'synthetic');db.chmod(0o600)
   service=ExistingLocalService(root);db.unlink()
   with self.assertRaises((ValueError,OSError)):service.get()
   self.assertFalse(db.exists())

class JournalRaceTests(unittest.TestCase):
 def test_removed_between_session_load_and_engine_open_never_recreates(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  from qianji_agent.journal import Journal
  from qianji_agent.remote import ExistingLocalService
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);root.chmod(0o700);Journal(root,'123');service=ExistingLocalService(root)
   def session():
    (root/'operations.sqlite3').unlink();return SimpleNamespace(uid='123')
   with patch('qianji_agent.auth.load_session',side_effect=session),patch('qianji_agent.transport.Transport',return_value=object()):
    with self.assertRaises(Exception):service.get()
   self.assertFalse((root/'operations.sqlite3').exists())
 def test_replaced_between_session_load_and_engine_open_is_not_initialized(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  from qianji_agent.journal import Journal
  from qianji_agent.remote import ExistingLocalService
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);root.chmod(0o700);Journal(root,'123');service=ExistingLocalService(root)
   replacement=root/'replacement';replacement.write_bytes(b'');replacement.chmod(0o600)
   def session():replacement.replace(root/'operations.sqlite3');return SimpleNamespace(uid='123')
   with patch('qianji_agent.auth.load_session',side_effect=session),patch('qianji_agent.transport.Transport',return_value=object()):
    with self.assertRaises(Exception):service.get()
   self.assertEqual((root/'operations.sqlite3').stat().st_size,0)
