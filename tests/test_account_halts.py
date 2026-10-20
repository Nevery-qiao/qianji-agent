"""Breaks caught: reclassification after restart, lost cause and partial DB commits."""
import tempfile,unittest,copy,sqlite3
from pathlib import Path
from qianji_agent.journal import Journal
from qianji_agent.codec import dumps
from test_business import snapshot,expense
from qianji_agent.operations import prepare

class AccountHaltTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'state';self.j=Journal(self.path,'123')
  self.assertTrue(callable(getattr(self.j,'activate_continuation',None)),'Missing durable unique continuation policy')
  self.plan=prepare(expense(),snapshot(),'123',bill_id='100')
 def activate(self):
  with self.j.lock():return self.j.activate_continuation('continuation-v1')
 def test_unique_history_set_does_not_include_new_pending_after_restart(self):
  self.j.start('historical','h',self.plan);p=self.activate()
  self.assertEqual(p['historical_requests'],['historical'])
  self.j.start('newer','n',self.plan);other=Journal(self.path,'123')
  self.assertEqual(other.activate_continuation('continuation-v1')['historical_requests'],['historical'])
  self.assertIn('newer',[h['request_id'] for h in other.active_halts()])
 def test_old_version_insert_after_activation_is_not_historical(self):
  self.activate()
  with self.j.db() as c:c.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',('old-process','h','pending_verification',dumps(self.plan),None,1))
  other=Journal(self.path,'123');self.assertEqual(other.activate_continuation('continuation-v1')['historical_requests'],[])
  self.assertEqual(other.active_halts()[0]['account_id'],'10')
 def test_multiple_halts_resolve_only_original_request(self):
  self.activate();self.j.start('one','1',self.plan);self.j.start('two','2',self.plan)
  self.j.finish('one',{'state':'verified','request_id':'one'})
  self.assertEqual([h['request_id'] for h in self.j.active_halts()],['two'])
 def test_unknown_scope_has_owner_halt(self):
  self.activate();self.j.start('unclear','h',{'action':'installment_create','collection':'installment'})
  self.assertEqual(self.j.active_halts()[0]['account_id'],'*')
 def test_historical_balance_conflict_keeps_stop_not_history_exemption(self):
  self.j.start('bad','h',self.plan);self.j.finish('bad',{'state':'pending_verification','verification_code':'balance_not_verified'})
  p=self.activate();self.assertEqual(p['historical_requests'],[]);self.assertEqual(self.j.active_halts()[0]['account_id'],'10')
 def test_policy_activation_preserves_original_plan_bytes(self):
  self.j.start('old','h',self.plan)
  with self.j.db() as c:before=c.execute('SELECT * FROM operations').fetchall()
  self.activate()
  with self.j.db() as c:self.assertEqual(c.execute('SELECT * FROM operations').fetchall(),before)
 def test_start_operation_and_halt_roll_back_together_on_storage_failure(self):
  self.activate()
  with self.j.db() as c:c.execute("CREATE TRIGGER deny_halt BEFORE INSERT ON account_halts BEGIN SELECT RAISE(ABORT,'disk fault'); END")
  with self.assertRaises(sqlite3.DatabaseError):self.j.start('fail','h',self.plan)
  self.assertIsNone(self.j.get('fail'));self.assertEqual(self.j.active_halts(),[])
 def test_finish_receipt_and_halt_roll_back_together_on_failure(self):
  self.activate();self.j.start('one','h',self.plan)
  with self.j.db() as c:c.execute("CREATE TRIGGER deny_end BEFORE UPDATE ON account_halts BEGIN SELECT RAISE(ABORT,'disk fault'); END")
  with self.assertRaises(sqlite3.DatabaseError):self.j.finish('one',{'state':'verified','request_id':'one'})
  self.assertEqual(self.j.get('one')['state'],'pending_verification');self.assertEqual(len(self.j.active_halts()),1)
 def test_drift_cause_survives_independent_request_success(self):
  self.activate();self.j.start('one','h',self.plan)
  self.j.record_account_review({'review_id':'review1','observed_at':1,'accounts':[{'account_id':'10','state':'halted','code':'account_drift_unexplained'}]}, {})
  self.j.finish('one',{'state':'verified','request_id':'one'})
  h=self.j.active_halts();self.assertEqual(len(h),1);self.assertEqual(h[0]['reason'],'account_drift_unexplained')

 def crash_child(self,phase):
  import subprocess,sys
  code="""import os,signal,sys
from pathlib import Path
from qianji_agent.journal import Journal
from qianji_agent import account_watch
from qianji_agent.codec import loads
j=Journal(Path(sys.argv[1]),'123')
phase=sys.argv[2]
name='cause' if phase=='start' else 'finish'
original=getattr(account_watch,name)
def crash(*a,**kw):
 original(*a,**kw)
 os.kill(os.getpid(),signal.SIGKILL)
setattr(account_watch,name,crash)
if phase=='start':j.start('crash','h',loads(sys.argv[3]))
else:j.finish('crash',{'state':'verified','request_id':'crash'})
"""
  result=subprocess.run([sys.executable,'-c',code,str(self.path),phase,dumps(self.plan)],capture_output=True,text=True,timeout=5)
  self.assertEqual(result.returncode,-9,result.stderr)
 def test_process_dies_during_start_no_partial_operation_or_cause(self):
  self.activate();self.crash_child('start')
  self.assertIsNone(self.j.get('crash'));self.assertEqual(self.j.active_halts(),[])
 def test_process_dies_during_finish_keeps_pending_and_stop(self):
  self.activate();self.j.start('crash','h',self.plan);self.crash_child('finish')
  self.assertEqual(self.j.get('crash')['state'],'pending_verification');self.assertEqual(len(self.j.active_halts()),1)
