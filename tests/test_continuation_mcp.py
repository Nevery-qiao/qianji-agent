"""Breaks caught: stale readiness, missing MCP contract and dropped account-only follow-up."""
import tempfile,unittest
from pathlib import Path
from decimal import Decimal
from mcp import Client
from qianji_agent.engine import Engine
from qianji_agent.server import build_server,LocalService
from test_account_review import FullBackend
from test_business import expense

class ContinuationMCPTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.b=FullBackend();self.e=Engine(self.b,'123',Path(self.tmp.name)/'state')
 async def test_review_is_normal_nondestructive_mcp_without_financial_dispatch(self):
  async with Client(build_server(self.e)) as c:
   tools={t.name:t for t in (await c.list_tools()).tools};self.assertIn('qianji_account_review',set(tools));self.assertEqual(len(tools),10)
   self.assertFalse(tools['qianji_account_review'].annotations.destructive_hint)
   r=(await c.call_tool('qianji_account_review',{})).structured_content;self.assertEqual(r['state'],'read');self.assertTrue(r['account_review']['current']);self.assertTrue(r['account_review']['ready']);self.assertEqual(self.b.writes,0)
 async def test_cached_summary_never_claims_current_readiness(self):
  self.e.account_review()
  async with Client(build_server(self.e)) as c:
   r=(await c.call_tool('qianji_connection',{})).structured_content
   self.assertFalse(r['account_review']['current']);self.assertFalse(r['account_review']['ready']);self.assertGreater(r['account_review']['observed_at'],0)
 async def test_account_only_halt_keeps_schedule_after_operation_queue_empty(self):
  self.e.account_review();self.b.data['assets'][0]['money']-=Decimal('0.10');self.e.account_review()
  async with Client(build_server(self.e)) as c:
   r=(await c.call_tool('qianji_recovery_list',{})).structured_content
   self.assertEqual(r['recovery']['open'],0);self.assertGreater(r['recovery']['account_halt_count'],0);self.assertTrue(r['tracking']['desired_active']);self.assertEqual(r['tracking']['action'],'ensure');self.assertEqual(self.b.writes,0)
 async def test_review_never_reopens_old_verification_or_consumes_budget(self):
  self.b.lose=True;self.e.execute('old',expense());self.b.lose=False;self.b.fail_read=False
  before=self.e.recovery_list()['records'][0]
  async with Client(build_server(self.e)) as c:
   await c.call_tool('qianji_account_review',{})
   after=(await c.call_tool('qianji_recovery_list',{})).structured_content['records'][0]
  self.assertEqual(before,after);self.assertEqual(self.b.writes,1)
 async def test_review_failure_does_not_use_previously_ready_cache(self):
  self.e.account_review();self.b.fail_read=True
  async with Client(build_server(self.e)) as c:
   r=(await c.call_tool('qianji_account_review',{})).structured_content
   self.assertEqual(r['state'],'not_executed');self.assertFalse(r['account_review']['ready']);self.assertFalse(r['account_review']['current'])
 async def test_no_public_scope_override_or_halt_clear_argument(self):
  async with Client(build_server(self.e)) as c:
   tools={t.name for t in (await c.list_tools()).tools};self.assertIn('qianji_account_review',tools)
   self.assertFalse({'force_clear','account_halt_clear','raw_request'}&tools)
   self.e.account_review();self.b.data['assets'][0]['money']-=Decimal('0.10');self.e.account_review();before=self.e.journal.active_halts()
   try:r=await c.call_tool('qianji_account_review',{'force':True})
   except Exception:pass
   else:self.assertFalse(r.structured_content['account_review']['ready'])
   self.assertEqual(self.e.journal.active_halts(),before);self.assertEqual(self.b.writes,0)
