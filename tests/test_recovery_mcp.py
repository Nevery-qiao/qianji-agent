import unittest,tempfile,io,json
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from mcp import Client
from qianji_agent.server import build_server
from qianji_agent.engine import Engine
from test_recovery_integration import AccountBackend
from test_business import expense

class RecoveryMCPTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.backend=AccountBackend();self.engine=Engine(self.backend,'123',Path(self.tmp.name)/'state')
 async def test_recovery_tools_are_discoverable_with_appropriate_annotations(self):
  async with Client(build_server(self.engine)) as c:
   tools={t.name:t for t in (await c.list_tools()).tools}
   self.assertIn('qianji_recovery_list',tools);self.assertIn('qianji_recovery_ack',tools);self.assertIn('qianji_recovery_scheduler',tools)
   self.assertTrue(tools['qianji_recovery_list'].annotations.read_only_hint);self.assertFalse(tools['qianji_recovery_ack'].annotations.destructive_hint)
   self.assertNotIn('force_clear',tools);self.assertNotIn('raw_request',tools)
 async def test_pending_is_reported_on_existing_tools_and_survives_native_resolution_until_ack(self):
  async with Client(build_server(self.engine)) as c:
   self.backend.lose=True;result=(await c.call_tool('qianji_execute',{'request_id':'unknown','command':expense()})).structured_content
   self.assertEqual(result['state'],'pending_verification');self.assertEqual(result['recovery']['open'],1);self.assertEqual(result['tracking']['action'],'ensure')
   self.backend.lose=False;self.backend.fail_read=False
   result=(await c.call_tool('qianji_operation_status',{'request_id':'unknown'})).structured_content;self.assertEqual(result['state'],'verified');self.assertEqual(result['recovery']['awaiting_ack'],1)
   queue=(await c.call_tool('qianji_recovery_list',{})).structured_content;row=queue['records'][0]
   result=(await c.call_tool('qianji_recovery_ack',{'request_id':'unknown','expected_version':row['version'],'disposition':'recorded','completion_reference':'ledger:done'})).structured_content
   self.assertEqual(result['state'],'acknowledged');self.assertEqual(result['recovery']['open'],0);self.assertEqual(self.backend.writes,1)
 async def test_scheduler_contract_reports_host_readback_without_dispatching(self):
  self.engine.journal.start('unknown','h',{'action':'bill_create','collection':'bills'})
  async with Client(build_server(self.engine)) as c:
   status=(await c.call_tool('qianji_recovery_scheduler',{})).structured_content;g=status['tracking']['generation']
   bound=(await c.call_tool('qianji_recovery_scheduler',{'action':'record','observation':{'expected_generation':g,'mode':'dedicated','job_id':'host-job','observed_state':'active','observation_reference':'official:view'}})).structured_content
   self.assertTrue(bound['tracking']['registered']);self.assertEqual(bound['tracking']['readback_source'],'host_reported');self.assertEqual(self.backend.writes,0)
 async def test_shared_transfer_is_available_through_strict_mcp_schema(self):
  self.engine.journal.start('unknown','h',{'action':'bill_create','collection':'bills'})
  async with Client(build_server(self.engine)) as c:
   g=(await c.call_tool('qianji_recovery_scheduler',{})).structured_content['tracking']['generation']
   base={'expected_generation':g,'mode':'shared','job_id':'daily','observed_state':'active','observation_reference':'official:daily'}
   await c.call_tool('qianji_recovery_scheduler',{'action':'record','observation':base})
   base.update(mode='dedicated',job_id='followup',observation_reference='official:followup',replaces_shared_job_id='daily')
   r=(await c.call_tool('qianji_recovery_scheduler',{'action':'record','observation':base})).structured_content
   self.assertEqual(r['tracking']['job_id'],'followup');self.assertEqual(r['tracking']['generation'],g+1);self.assertTrue(r['tracking']['registered']);self.assertEqual(self.backend.writes,0)
 async def test_malformed_schedule_observation_and_extra_fields_are_rejected(self):
  async with Client(build_server(self.engine)) as c:
   tools={t.name for t in (await c.list_tools()).tools};self.assertIn('qianji_recovery_scheduler',tools)
   for observation in [{'expected_generation':'1','mode':'dedicated','job_id':'x','observed_state':'active','observation_reference':'ref'},{'expected_generation':0,'mode':'dedicated','job_id':'x','observed_state':'active','observation_reference':'ref','utoken':'private'}]:
    try:r=await c.call_tool('qianji_recovery_scheduler',{'action':'record','observation':observation})
    except Exception:continue
    self.assertTrue(r.is_error)
   self.assertEqual(self.backend.writes,0)
 async def test_runtime_identity_and_empty_tracking_are_returned_on_connection(self):
  from qianji_agent import __version__
  async with Client(build_server(self.engine)) as c:
   r=(await c.call_tool('qianji_connection',{})).structured_content;self.assertEqual(r['runtime_version'],__version__);self.assertEqual(r['recovery']['open'],0)
 async def test_unknown_ack_cannot_close_queue_or_send_a_financial_request(self):
  self.engine.journal.start('unknown','h',{'action':'bill_create','collection':'bills'})
  async with Client(build_server(self.engine)) as c:
   tools={t.name for t in (await c.list_tools()).tools};self.assertIn('qianji_recovery_ack',tools)
   row=(await c.call_tool('qianji_recovery_list',{})).structured_content['records'][0]
   r=(await c.call_tool('qianji_recovery_ack',{'request_id':'unknown','expected_version':row['version'],'disposition':'recorded','completion_reference':'ledger:fake'})).structured_content
   self.assertEqual(r['code'],'recovery_result_unresolved');self.assertEqual(r['recovery']['open'],1);self.assertEqual(self.backend.writes,0)
 async def test_existing_operation_status_accepts_bounded_automatic_review(self):
  self.engine.journal.start('unknown','h',{'action':'bill_create','collection':'bills'})
  async with Client(build_server(self.engine)) as c:
   r=(await c.call_tool('qianji_operation_status',{'request_id':'unknown','automatic':True})).structured_content
   self.assertEqual(r['code'],'recovery_not_due');self.assertEqual(self.backend.writes,0)

class RecoveryCLITests(unittest.TestCase):
 def test_existing_backup_command_still_returns_a_verified_private_backup(self):
  from qianji_agent.cli import main
  from qianji_agent.server import LocalService
  with tempfile.TemporaryDirectory() as tmp:
   e=Engine(AccountBackend(),'123',Path(tmp)/'state');service=LocalService();target=Path(tmp)/'copy.sqlite3';stream=io.StringIO()
   with patch.object(service,'get',return_value=e),patch('qianji_agent.cli.LocalService',return_value=service),patch('sys.argv',['qianji-agent','backup',str(target)]),redirect_stdout(stream):
    main()
   r=json.loads(stream.getvalue());self.assertTrue(r['backup_created']);self.assertEqual(r['state'],'verified');self.assertTrue(target.is_file());self.assertEqual(target.stat().st_mode&0o777,0o600)
 def test_cli_lists_the_same_durable_queue_without_financial_dispatch(self):
  from qianji_agent.cli import main
  with tempfile.TemporaryDirectory() as tmp:
   b=AccountBackend();e=Engine(b,'123',Path(tmp)/'state');e.journal.start('unknown','h',{'action':'bill_create','collection':'bills'})
   stream=io.StringIO()
   with patch('qianji_agent.cli.LocalService',return_value=e),patch('sys.argv',['qianji-agent','recovery-list']),redirect_stdout(stream):
    exit_code=0
    try:main()
    except SystemExit as result:exit_code=result.code
   self.assertEqual(exit_code,0);r=json.loads(stream.getvalue());self.assertEqual(r['records'][0]['request_id'],'unknown');self.assertEqual(b.writes,0)
