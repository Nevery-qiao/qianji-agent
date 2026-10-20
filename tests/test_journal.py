import tempfile, unittest, os
from pathlib import Path
try:from qianji_agent.journal import Journal
except ImportError:Journal=None

class JournalTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(Journal,'Durable shared journal required')
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'state';self.j=Journal(self.root,'owner-a')
 def test_dispatch_survives_reopen_and_prevents_duplicate(self):
  with self.j.lock():self.j.start('req1','hash1',{'route':'bill/syncall','bill_id':'9007199254740993123'})
  other=Journal(self.root,'owner-a')
  with other.lock():
   self.assertEqual(other.get('req1')['state'],'pending_verification')
   self.assertEqual(other.unresolved(),'req1')
   with self.assertRaises(ValueError):other.start('req1','hash1',{})
 def test_private_modes_and_symlink_rejected(self):
  self.assertEqual(os.stat(self.root).st_mode&0o777,0o700)
  self.assertEqual(os.stat(self.root/'operations.sqlite3').st_mode&0o777,0o600)
  bad=Path(self.temp.name)/'bad';bad.symlink_to(self.root,target_is_directory=True)
  with self.assertRaises(ValueError):Journal(bad,'owner-a')
 def test_account_switch_blocked(self):
  with self.assertRaises(ValueError):Journal(self.root,'owner-b')
 def test_final_receipt_persists(self):
  with self.j.lock():
   self.j.start('req2','hash2',{'bill_id':'9007199254740993123'})
   self.j.finish('req2',{'state':'verified','object_id':'9007199254740993123'})
  r=Journal(self.root,'owner-a').get('req2')
  self.assertEqual(r['receipt']['object_id'],'9007199254740993123');self.assertIsNone(self.j.unresolved())
 def test_pending_file_upload_does_not_block_independent_financial_work(self):
  with self.j.lock():
   self.j.start('image','h',{'collection':'uploads'})
   self.assertIsNone(self.j.unresolved())
   self.j.start('bill','h2',{'collection':'bills'})
   self.assertEqual(self.j.unresolved(),'bill')
 def test_storage_evidence_survives_restart_without_login_secret(self):
  with self.j.lock():
   self.j.observe('file',{'key':'a'*32,'hash':'content-hash'})
  self.assertEqual(Journal(self.root,'owner-a').evidence('file'),{'key':'a'*32,'hash':'content-hash'})
