import unittest,tempfile
from pathlib import Path
from mcp import Client
from test_engine import Backend
from test_business import expense
from qianji_agent.engine import Engine
try:from qianji_agent.server import build_server
except ImportError:build_server=None

class MCPTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.assertIsNotNone(build_server,'Product MCP entry required')
  self.d=tempfile.TemporaryDirectory();self.addCleanup(self.d.cleanup);self.b=Backend();self.e=Engine(self.b,'123',Path(self.d.name)/'state')
 async def test_mcp_write_verified_and_duplicate_shared_with_direct_core(self):
  async with Client(build_server(self.e)) as c:
   r=await c.call_tool('qianji_execute',{'request_id':'mcp1','command':expense()})
   self.assertEqual(r.structured_content['state'],'verified')
   self.assertEqual(self.e.execute('mcp1',expense())['state'],'verified');self.assertEqual(self.b.writes,1)
 async def test_preview_is_readonly_and_unknown_route_not_exposed(self):
  async with Client(build_server(self.e)) as c:
   listing=await c.list_tools();tools={t.name:t for t in listing.tools}
   self.assertTrue(tools['qianji_preview'].annotations.read_only_hint)
   self.assertTrue(tools['qianji_execute'].annotations.destructive_hint)
   self.assertNotIn('raw_request',tools)
   r=await c.call_tool('qianji_preview',{'command':expense()});self.assertEqual(r.structured_content['state'],'preview');self.assertEqual(self.b.writes,0)
 async def test_numeric_amount_rejected(self):
  async with Client(build_server(self.e)) as c:
   try:r=await c.call_tool('qianji_execute',{'request_id':'invalid','command':expense(amount=0.1)})
   except Exception:pass
   else:self.assertTrue(r.is_error)
   self.assertEqual(self.b.writes,0)
 async def test_capabilities_include_connection_and_all_48_group_limits(self):
  async with Client(build_server(self.e)) as c:
   r=(await c.call_tool('qianji_capabilities',{})).structured_content
   self.assertTrue(r['compatible']);self.assertIn('attachment_upload',r['operations']);self.assertEqual(len(r['capabilities']),48)
   blocked=next(g for g in r['capabilities'] if g['id']=='L05');self.assertEqual(blocked['status'],'blocked')
