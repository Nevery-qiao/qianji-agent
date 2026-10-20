import tempfile,unittest,sqlite3,hashlib
from pathlib import Path
from unittest.mock import patch
from qianji_agent.journal import Journal
from qianji_agent.codec import dumps
try:from qianji_agent.recovery import RecoveryStore
except ImportError:RecoveryStore=None

class RecoveryLifecycleTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(RecoveryStore,'Persistent recovery lifecycle required')
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.clock=patch('qianji_agent.recovery.time.time',return_value=1000);self.now=self.clock.start();self.addCleanup(self.clock.stop)
  self.path=Path(self.tmp.name)/'state';self.j=Journal(self.path,'owner');self.r=RecoveryStore(self.j)
 def pending(self,rid='one',action='bill_create'):
  with self.j.lock():
   self.j.start(rid,'fingerprint',{'action':action,'collection':'bills','balances':{'10':'0.90'},'params':{'token':'do-not-expose'}})
   self.j.finish(rid,{'state':'pending_verification','code':'result_unknown','request_id':rid})
 def item(self,rid='one',closed=False):return next(r for r in self.r.list(include_closed=closed)['records'] if r['request_id']==rid)
 def resolve(self,rid='one',state='verified'):
  with self.j.lock():self.j.finish(rid,{'state':state,'request_id':rid,'object_id':'100'},reviewed=True)
 def ack(self,rid='one',disposition='recorded',version=None):
  return self.r.ack(rid,version or self.item(rid)['version'],disposition,'ledger:row-100')
 def test_pending_survives_restart_and_native_plan_is_preserved(self):
  self.pending();before=self.j.get('one');reopened=Journal(self.path,'owner');r=RecoveryStore(reopened).list()
  self.assertEqual(r['total'],1);self.assertEqual(r['records'][0]['phase'],'waiting')
  self.assertEqual(reopened.get('one'),before);self.assertNotIn('do-not-expose',str(r));self.assertEqual(r['recovery']['open'],1)
 def test_crashed_inflight_is_rediscovered_after_process_restart(self):
  with self.j.lock():self.j.start('crash','h',{'action':'refund_create','collection':'bills'})
  r=RecoveryStore(Journal(self.path,'owner')).list()
  self.assertEqual(r['total'],1);self.assertEqual(r['records'][0]['phase'],'waiting');self.assertFalse(r['records'][0]['safe_to_resend'])
 def test_direct_success_remains_discoverable_until_caller_confirms_delivery(self):
  with self.j.lock():
   self.j.start('fast','h',{'action':'bill_create','collection':'bills'})
   self.j.finish('fast',{'state':'verified','request_id':'fast','object_id':'100'})
  self.assertEqual(self.r.list()['total'],1);self.assertEqual(self.item('fast')['phase'],'awaiting_ack')
  self.ack('fast');self.assertEqual(self.r.list()['total'],0);self.assertEqual(self.r.scheduler()['tracking']['action'],'none')
 def test_missing_finish_is_discovered_in_same_live_agent(self):
  with self.j.lock():self.j.start('crash','h',{'action':'bill_create','collection':'bills'})
  self.now.return_value=1061;r=self.r.list()
  self.assertEqual(r['records'][0]['phase'],'waiting');self.assertEqual(r['recovery']['due'],1)
 def test_new_legacy_writer_unknown_is_discovered_without_restarting_reader(self):
  with self.j.db() as c:c.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',('legacy-late','h','pending_verification',dumps({'action':'debt_pay','collection':'bills'}),None,1000))
  r=self.r.list();self.assertEqual(r['total'],1);self.assertEqual(r['records'][0]['phase'],'needs_attention')
 def test_older_writer_terminal_receipt_still_requires_callers_ack(self):
  self.pending()
  with self.j.db() as c:c.execute('UPDATE operations SET state=?,receipt=? WHERE request_id=?',('verified',dumps({'state':'verified','object_id':'100'}),'one'))
  self.assertEqual(self.item()['phase'],'awaiting_ack')
 def test_verified_unknown_still_needs_callers_completion_ack(self):
  self.pending();self.resolve();r=self.r.list();self.assertEqual(r['records'][0]['phase'],'awaiting_ack')
  self.assertTrue(r['tracking']['desired_active']);self.assertEqual(self.ack()['state'],'acknowledged');self.assertEqual(self.r.list()['total'],0)
 def test_unknown_cannot_be_acknowledged_as_completed(self):
  self.pending();r=self.ack();self.assertEqual(r['code'],'recovery_result_unresolved');self.assertEqual(self.r.list()['total'],1)
 def test_failed_result_is_not_recorded_and_requires_explicit_disposition(self):
  self.pending();self.resolve(state='failed');self.assertEqual(self.ack()['code'],'recovery_disposition_mismatch')
  self.assertEqual(self.ack(disposition='handled_without_recording')['state'],'acknowledged')
  self.assertEqual(self.item(closed=True)['disposition'],'handled_without_recording')
 def test_ack_is_version_checked_and_duplicate_ack_is_idempotent(self):
  self.pending();old=self.item()['version'];self.resolve();self.assertEqual(self.ack(version=old)['code'],'version_conflict')
  version=self.item()['version'];first=self.ack(version=version);second=self.ack(version=version)
  self.assertEqual(first,second);self.assertEqual(self.r.list()['total'],0)
 def test_three_pending_reviews_escalate_without_dropping_the_item(self):
  self.pending()
  for now in [1060,1360,3160]:
   self.now.return_value=now
   with self.j.lock():self.j.finish('one',{'state':'pending_verification','code':'result_unknown'},reviewed=True)
  item=self.item();self.assertEqual(item['phase'],'needs_attention');self.assertEqual(item['checks'],3);self.assertIsNone(item['next_check_at'])
  self.assertEqual(self.r.list()['recovery']['needs_attention'],1);self.assertTrue(self.r.scheduler()['tracking']['desired_active'])
 def test_old_unresolved_operations_migrate_without_new_automatic_budget(self):
  path=Path(self.tmp.name)/'legacy';path.mkdir(mode=0o700);db=path/'operations.sqlite3'
  with sqlite3.connect(db) as c:
   c.execute('CREATE TABLE operations(request_id TEXT PRIMARY KEY,hash TEXT,state TEXT,plan TEXT,receipt TEXT,created_at INTEGER)')
   c.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',('old','h','pending_verification',dumps({'action':'installment_create','collection':'installment'}),None,100))
  db.chmod(0o600);legacy=RecoveryStore(Journal(path,'owner')).list();item=legacy['records'][0]
  self.assertEqual(item['phase'],'needs_attention');self.assertEqual(item['checks'],0);self.assertIsNone(item['next_check_at']);self.assertEqual(item['last_code'],'legacy_result_unknown')
 def test_more_than_one_day_escalates_without_native_calls(self):
  self.pending();self.now.return_value=87401;self.assertEqual(self.item()['phase'],'needs_attention')
 def test_all_action_types_share_the_same_followup_lifecycle(self):
  for i,action in enumerate(['bill_create','refund_create','debt_pay','repeat_update','installment_create','book_rename','attachment_upload']):self.pending(str(i),action)
  self.assertEqual(self.r.list()['total'],7);self.assertEqual(self.r.list(limit=2)['next_offset'],2)
 def test_dedicated_schedule_is_cancelled_only_after_last_completion(self):
  self.pending();self.pending('two');s=self.r.scheduler()['tracking'];g=s['generation']
  bound=self.r.scheduler_record(g,'dedicated','host-job','active','official:view1');self.assertEqual(bound['tracking']['action'],'none')
  self.resolve();self.ack();self.assertEqual(self.r.scheduler()['tracking']['action'],'none')
  self.resolve('two');self.ack('two');self.assertEqual(self.r.scheduler()['tracking']['action'],'cancel')
  s=self.r.scheduler()['tracking'];done=self.r.scheduler_record(s['generation'],'dedicated','host-job','absent','official:deleted')
  self.assertEqual(done['tracking']['action'],'none');self.assertFalse(done['tracking']['desired_active'])
 def test_new_pending_during_cancel_invalidates_stale_confirmation(self):
  self.pending();g=self.r.scheduler()['tracking']['generation'];self.r.scheduler_record(g,'dedicated','job','active','official:view')
  self.resolve();self.ack();cancel=self.r.scheduler()['tracking']['generation'];self.pending('new')
  r=self.r.scheduler_record(cancel,'dedicated','job','absent','official:delete')
  self.assertEqual(r['code'],'schedule_changed');self.assertTrue(r['tracking']['desired_active']);self.assertEqual(r['tracking']['action'],'ensure')
 def test_shared_daily_schedule_is_preserved_after_queue_drains(self):
  self.pending();g=self.r.scheduler()['tracking']['generation'];self.r.scheduler_record(g,'shared','daily','active','official:view')
  self.resolve();self.ack();s=self.r.scheduler()['tracking'];self.assertEqual(s['mode'],'shared');self.assertEqual(s['action'],'none');self.assertEqual(s['job_id'],'daily')
 def test_new_generation_cannot_reuse_active_observation_before_lost_cancellation(self):
  self.pending();g=self.r.scheduler()['tracking']['generation'];self.r.scheduler_record(g,'dedicated','job','active','official:view')
  self.resolve();self.ack();self.pending('new');s=self.r.scheduler()['tracking']
  self.assertFalse(s['ready']);self.assertFalse(s['registered']);self.assertEqual(s['action'],'inspect')
  s=self.r.scheduler_record(s['generation'],'dedicated','job','absent','official:missing')['tracking'];self.assertEqual(s['action'],'ensure')
 def test_external_job_disappearance_requires_repair_not_false_tracking(self):
  self.pending();g=self.r.scheduler()['tracking']['generation'];self.r.scheduler_record(g,'dedicated','job','active','official:view')
  s=self.r.scheduler_record(g,'dedicated','job','absent','official:missing')['tracking'];self.assertEqual(s['action'],'ensure');self.assertFalse(s['registered'])
 def test_host_schedule_identity_is_stable_and_distinguishes_other_journals(self):
  a=self.r.scheduler()['tracking'];self.assertIn('scope_id',a)
  b=RecoveryStore(Journal(self.path,'owner')).scheduler()['tracking'];self.assertEqual(a['scope_id'],b['scope_id'])
  c=RecoveryStore(Journal(Path(self.tmp.name)/'other','other-owner')).scheduler()['tracking'];self.assertNotEqual(a['scope_id'],c['scope_id'])
 def test_invalid_filters_or_references_do_not_mutate_recovery(self):
  self.pending();before=self.r.list()
  self.assertEqual(self.r.list(limit=0)['code'],'invalid_filter')
  self.resolve();self.assertEqual(self.r.ack('one',self.item()['version'],'recorded','token=secret')['code'],'invalid_recovery_reference')
  self.assertEqual(self.r.list()['total'],before['total'])

 def test_shared_to_dedicated_transfer_preserves_daily_and_invalidates_old_callbacks(self):
  self.pending();g=self.r.scheduler()['tracking']['generation'];self.r.scheduler_record(g,'shared','daily','active','official:daily')
  r=self.r.scheduler_record(g,'dedicated','followup','active','official:followup',replaces_shared_job_id='daily')
  self.assertEqual(r['state'],'read');self.assertEqual(r['tracking']['job_id'],'followup');self.assertEqual(r['tracking']['generation'],g+1);self.assertTrue(r['tracking']['registered'])
  old=self.r.scheduler_record(g,'shared','daily','active','official:late-daily');self.assertEqual(old['code'],'schedule_changed');self.assertEqual(old['tracking']['job_id'],'followup')
  self.resolve();self.ack();self.assertEqual(self.r.scheduler()['tracking']['action'],'cancel');self.assertEqual(self.r.scheduler()['tracking']['job_id'],'followup')
 def test_shared_transfer_requires_exact_current_source_and_active_new_job(self):
  self.pending();g=self.r.scheduler()['tracking']['generation'];self.r.scheduler_record(g,'shared','daily','active','official:daily')
  for source,state in [('wrong','active'),('daily','absent')]:
   r=self.r.scheduler_record(g,'dedicated','followup',state,'official:followup',replaces_shared_job_id=source)
   self.assertEqual(r['code'],'schedule_binding_conflict');self.assertEqual(r['tracking']['job_id'],'daily')
 def test_dedicated_cannot_be_relabelled_shared_to_escape_cleanup(self):
  self.pending();g=self.r.scheduler()['tracking']['generation'];self.r.scheduler_record(g,'dedicated','followup','active','official:followup')
  r=self.r.scheduler_record(g,'shared','followup','active','official:relabel');self.assertEqual(r['code'],'schedule_binding_conflict')
 def test_active_dedicated_cannot_be_replaced_using_shared_transfer(self):
  self.pending();g=self.r.scheduler()['tracking']['generation'];self.r.scheduler_record(g,'dedicated','old-job','active','official:old')
  r=self.r.scheduler_record(g,'dedicated','new-job','active','official:new',replaces_shared_job_id='old-job');self.assertEqual(r['code'],'schedule_binding_conflict')
 def test_transfer_rejects_unsafe_source_reference(self):
  r=self.r.scheduler_record(0,'dedicated','new-job','active','official:new',replaces_shared_job_id='token=secret');self.assertEqual(r['code'],'invalid_recovery_schedule')
