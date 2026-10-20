import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from qianji_agent.auth import Session
from qianji_agent.server import LocalService
from qianji_agent.transport import QianjiError
class ServiceGuardTests(unittest.TestCase):
 def test_current_app_owner_change_blocks_cached_connection(self):
  with tempfile.TemporaryDirectory() as d:
   service=LocalService(Path(d)/'state')
   with patch('qianji_agent.auth.load_session',side_effect=[Session('a',{},('a','b','c'),'1580'),Session('b',{},('a','b','c'),'1580')]):
    service.get()
    with self.assertRaises(QianjiError) as ex:service.get()
    self.assertEqual(ex.exception.code,'account_changed')
 def test_app_update_blocks_cached_connection(self):
  with tempfile.TemporaryDirectory() as d:
   service=LocalService(Path(d)/'state')
   with patch('qianji_agent.auth.load_session',side_effect=[Session('a',{},('a','b','c'),'1580'),QianjiError('adapter_update_required')]):
    service.get()
    with self.assertRaises(QianjiError):service.get()
