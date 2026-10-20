"""Real stdio boundary and cross-process shared journal, synthetic backend only."""
import asyncio,sys,tempfile,unittest,qianji_agent
from pathlib import Path
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from qianji_agent.codec import dumps
from test_business import snapshot,expense

class ContinuationStdioTests(unittest.IsolatedAsyncioTestCase):
 async def test_two_stdio_processes_share_review_request_and_delivery_without_resend(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'native.json').write_text(dumps(snapshot()))
   package_root=Path(qianji_agent.__file__).resolve().parent.parent
   params=StdioServerParameters(command=sys.executable,args=[str(Path(__file__).with_name('stdio_continuation_driver.py')),tmp],cwd=Path(__file__).resolve().parent.parent,env={'QIANJI_TEST_PACKAGE_ROOT':str(package_root)})
   async with Client(params) as first,Client(params) as second:
    names={t.name for t in (await first.list_tools()).tools};self.assertEqual(len(names),10);self.assertIn('qianji_account_review',names)
    loaded=(root/'runtime-files.log').read_text().splitlines();self.assertEqual(len(loaded),2)
    self.assertTrue(all(Path(path).is_relative_to(package_root/'qianji_agent') for path in loaded),loaded)
    review=(await first.call_tool('qianji_account_review',{})).structured_content;self.assertTrue(review['account_review']['current'])
    results=await asyncio.gather(*(c.call_tool('qianji_execute',{'request_id':'stable','command':expense()}) for c in (first,second)))
    self.assertEqual([r.structured_content['state'] for r in results],['verified','verified'])
    self.assertEqual((root/'dispatch.log').read_text().splitlines(),['synthetic-dispatch'])
    row=(await second.call_tool('qianji_recovery_list',{})).structured_content['records'][0]
    ack=(await second.call_tool('qianji_recovery_ack',{'request_id':'stable','expected_version':row['version'],'disposition':'recorded','completion_reference':'synthetic:ledger:stable'})).structured_content
    self.assertEqual(ack['state'],'acknowledged')
    empty=(await first.call_tool('qianji_recovery_list',{})).structured_content;self.assertEqual(empty['recovery']['open'],0);self.assertEqual(empty['recovery']['account_halt_count'],0)
