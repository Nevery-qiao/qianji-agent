"""Durable follow-up metadata. Never dispatches financial or scheduler writes."""
import re,time,secrets
from .codec import dumps,loads,digest
from .dispatch import ERROR_CODES,VERIFY_CODES

OPEN={'inflight','waiting','needs_attention','awaiting_ack'}
CODES=ERROR_CODES|VERIFY_CODES|{'legacy_result_unknown','interrupted','verification_incomplete','backend_rejected_no_effect_verified'}
REFERENCE=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,179}\Z')

def now():return int(time.time())
def event(c,rid,kind,data=None):
 c.execute('INSERT INTO recovery_events(request_id,event,created_at,data) VALUES(?,?,?,?)',(rid,kind,now(),dumps(data or {})))
def put(c,rid,phase,data):
 c.execute('INSERT INTO recovery_items VALUES(?,?,?) ON CONFLICT(request_id) DO UPDATE SET phase=excluded.phase,data=excluded.data',(rid,phase,dumps(data)))
def schedule(c):return loads(c.execute('SELECT data FROM recovery_schedule WHERE id=1').fetchone()[0])
def save_schedule(c,s):c.execute('UPDATE recovery_schedule SET data=? WHERE id=1',(dumps(s),))
def sync_schedule(c):
 from .account_watch import active as active_halts
 active=bool(active_halts(c)) or c.execute("SELECT 1 FROM recovery_items WHERE phase!='closed' LIMIT 1").fetchone() is not None
 s=schedule(c)
 if s['desired_active']!=active:
  s.update(desired_active=active,generation=s['generation']+1);save_schedule(c,s)
  event(c,None,'schedule_desired',{'active':active,'generation':s['generation']})
 return s

def install(c):
 c.execute('CREATE TABLE IF NOT EXISTS recovery_items(request_id TEXT PRIMARY KEY,phase TEXT NOT NULL,data TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS recovery_events(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT,event TEXT NOT NULL,created_at INTEGER NOT NULL,data TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS recovery_schedule(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)')
 c.execute('INSERT OR IGNORE INTO recovery_schedule VALUES(1,?)',(dumps({'generation':0,'desired_active':False,'mode':'unbound','job_id':None,'observed_state':'unknown','observed_at':None,'observation_reference':None}),))
 s=schedule(c)
 if 'scope_id' not in s:s['scope_id']='qj-'+secrets.token_hex(8);save_schedule(c,s)
 if 'observed_generation' not in s:s['observed_generation']=None;save_schedule(c,s)
 discover(c)
 for rid,raw in c.execute("SELECT request_id,data FROM recovery_items WHERE phase='inflight'").fetchall():
  d=loads(raw);d.update(ever_pending=True,revision=d['revision']+1,last_code='interrupted');put(c,rid,'waiting',d);event(c,rid,'interrupted')
 sync_schedule(c)

def discover(c):
 for rid,created in c.execute("SELECT request_id,created_at FROM operations WHERE state='pending_verification' AND request_id NOT IN(SELECT request_id FROM recovery_items)").fetchall():
  data={'revision':1,'ever_pending':True,'checks':0,'created_at':created,'next_check_at':None,'last_checked_at':None,'last_code':'legacy_result_unknown'}
  put(c,rid,'needs_attention',data);event(c,rid,'legacy_discovered')

def start(c,rid):
 put(c,rid,'inflight',{'revision':1,'ever_pending':False,'checks':0,'created_at':now(),'next_check_at':now()+60,'last_checked_at':None,'last_code':None})
 event(c,rid,'started');sync_schedule(c)

def observe(c,rid,receipt,reviewed=False):
 row=c.execute('SELECT phase,data FROM recovery_items WHERE request_id=?',(rid,)).fetchone()
 if row is None:return
 phase,d=row[0],loads(row[1]);state=receipt['state'];d['revision']+=1
 if reviewed:
  d['checks']+=1;d['last_checked_at']=now()
 code=receipt.get('verification_code') or receipt.get('code');d['last_code']=code if code in CODES else None
 if state=='pending_verification':
  d['ever_pending']=True
  if phase=='needs_attention' or d['checks']>=3 or now()-d['created_at']>=86400:
   phase='needs_attention';d['next_check_at']=None
  else:
   phase='waiting';d['next_check_at']=now()+[60,300,1800][min(d['checks'],2)]
 elif state in {'verified','failed'}:
  phase='awaiting_ack';d['next_check_at']=None
 put(c,rid,phase,d);event(c,rid,'reviewed' if reviewed else 'observed',{'state':state,'phase':phase});sync_schedule(c)

class RecoveryStore:
 def __init__(self,journal):self.journal=journal
 def _refresh(self,c):
  discover(c)
  for rid,phase,raw,state in c.execute("SELECT r.request_id,r.phase,r.data,o.state FROM recovery_items r JOIN operations o USING(request_id) WHERE r.phase NOT IN('closed','awaiting_ack') AND o.state IN('verified','failed')").fetchall():
   d=loads(raw);phase='awaiting_ack';d.update(revision=d['revision']+1,next_check_at=None)
   put(c,rid,phase,d);event(c,rid,'external_terminal_observed',{'state':state})
  # Called under the account lock, so an inflight row here has no active dispatch.
  for rid,raw in c.execute("SELECT request_id,data FROM recovery_items WHERE phase='inflight'").fetchall():
   d=loads(raw);d.update(ever_pending=True,revision=d['revision']+1,last_code='interrupted');put(c,rid,'waiting',d);event(c,rid,'interrupted')
  for rid,raw in c.execute("SELECT request_id,data FROM recovery_items WHERE phase IN('waiting','inflight')").fetchall():
   d=loads(raw)
   if now()-d['created_at']>=86400:
    d.update(revision=d['revision']+1,ever_pending=True,next_check_at=None);put(c,rid,'needs_attention',d);event(c,rid,'age_escalated')
  return sync_schedule(c)
 def _summary(self,c):
  counts={p:n for p,n in c.execute('SELECT phase,count(*) FROM recovery_items GROUP BY phase')}
  due=c.execute("SELECT count(*) FROM recovery_items WHERE phase='waiting' AND CAST(json_extract(data,'$.next_check_at') AS INTEGER)<=?",(now(),)).fetchone()[0]
  from .account_watch import active as active_halts
  return {'account_halt_count':len(active_halts(c)),'open':sum(counts.get(p,0) for p in OPEN),'waiting':counts.get('waiting',0),'needs_attention':counts.get('needs_attention',0),'awaiting_ack':counts.get('awaiting_ack',0),'due':due}
 def _tracking(self,c):
  s=schedule(c);fresh=s['observed_at'] is not None and now()-s['observed_at']<=3600
  registered=s['observed_state']=='active' and bool(s['job_id']) and fresh and s.get('observed_generation')==s['generation']
  if s['desired_active']:
   action='none' if registered else ('inspect' if s['job_id'] and s['observed_state']=='active' else 'ensure')
  else:action='cancel' if s['mode']=='dedicated' and s['job_id'] and s['observed_state'] not in {'absent','paused'} else 'none'
  return {**s,'action':action,'registered':registered,'readback_source':'host_reported','ready':(not s['desired_active'] and action=='none') or (s['desired_active'] and registered)}
 def _result(self,c,**extra):return {'state':'read','recovery':self._summary(c),'tracking':self._tracking(c),**extra}
 def _public(self,row):
  rid,phase,raw,state,planraw,receipt_raw,fingerprint=row;d=loads(raw);plan=loads(planraw)
  return {'request_id':rid,'action':plan.get('action','unknown'),'phase':phase,'operation_state':state,
   'checks':d['checks'],'created_at':d['created_at'],'next_check_at':d['next_check_at'],'last_checked_at':d['last_checked_at'],
   'last_code':d['last_code'],'account_ids':sorted(str(i) for i in plan.get('balances',{})),
   'safe_to_resend':False,'version':digest([rid,phase,d,state,receipt_raw,fingerprint]),**({'disposition':d['disposition']} if 'disposition' in d else {})}
 def list(self,include_closed=False,offset=0,limit=100):
  if type(include_closed) is not bool or type(offset) is not int or type(limit) is not int or offset<0 or not 1<=limit<=1000:return {'state':'not_executed','code':'invalid_filter'}
  with self.journal.lock(),self.journal.db() as c:
   self._refresh(c);where='' if include_closed else "WHERE r.phase!='closed'"
   rows=c.execute('SELECT r.request_id,r.phase,r.data,o.state,o.plan,o.receipt,o.hash FROM recovery_items r JOIN operations o USING(request_id) '+where+' ORDER BY o.created_at,r.request_id').fetchall()
   records=[self._public(row) for row in rows[offset:offset+limit]]
   return self._result(c,records=records,total=len(rows),next_offset=offset+limit if offset+limit<len(rows) else None)
 def scheduler(self):
  with self.journal.lock(),self.journal.db() as c:self._refresh(c);return self._result(c)
 def begin_review(self,request_id,automatic=False):
  """Caller holds the account lock; persist the attempt before native reads."""
  with self.journal.db() as c:
   self._refresh(c);row=c.execute('SELECT phase,data FROM recovery_items WHERE request_id=?',(request_id,)).fetchone()
   if row is None:return {'state':'not_executed','code':'request_not_found','request_id':request_id}
   phase,d=row[0],loads(row[1])
   if automatic:
    if phase!='waiting' or d['checks']>=3 or now()-d['created_at']>=86400:return {'state':'not_executed','code':'recovery_requires_attention','request_id':request_id}
    if d.get('next_check_at') is None or d['next_check_at']>now():return {'state':'not_executed','code':'recovery_not_due','request_id':request_id}
   d.update(ever_pending=True,checks=d['checks']+1,revision=d['revision']+1,last_checked_at=now())
   if phase=='needs_attention' or d['checks']>=3 or now()-d['created_at']>=86400:phase='needs_attention';d['next_check_at']=None
   else:phase='waiting';d['next_check_at']=now()+[60,300,1800][min(d['checks'],2)]
   put(c,request_id,phase,d);event(c,request_id,'review_started',{'automatic':automatic,'check':d['checks']});sync_schedule(c)
  return None
 def ack(self,request_id,expected_version,disposition,completion_reference):
  if not isinstance(completion_reference,str) or not REFERENCE.fullmatch(completion_reference):return {'state':'not_executed','code':'invalid_recovery_reference'}
  with self.journal.lock(),self.journal.db() as c:
   row=c.execute('SELECT r.request_id,r.phase,r.data,o.state,o.plan,o.receipt,o.hash FROM recovery_items r JOIN operations o USING(request_id) WHERE r.request_id=?',(request_id,)).fetchone()
   if row is None:return {'state':'not_executed','code':'request_not_found'}
   d=loads(row[2]);signature=digest([expected_version,disposition,completion_reference])
   if row[1]=='closed' and d.get('ack_signature')==signature:return self._result(c,state='acknowledged',request_id=request_id)
   if self._public(row)['version']!=expected_version:return {'state':'not_executed','code':'version_conflict'}
   if row[3] not in {'verified','failed'} or row[1]!='awaiting_ack':return {'state':'not_executed','code':'recovery_result_unresolved'}
   if disposition!=('recorded' if row[3]=='verified' else 'handled_without_recording'):return {'state':'not_executed','code':'recovery_disposition_mismatch'}
   d.update(revision=d['revision']+1,disposition=disposition,completion_reference=completion_reference,ack_signature=signature,next_check_at=None)
   put(c,request_id,'closed',d);event(c,request_id,'acknowledged',{'disposition':disposition});sync_schedule(c)
   return self._result(c,state='acknowledged',request_id=request_id)
 def scheduler_record(self,expected_generation,mode,job_id,observed_state,observation_reference,replaces_shared_job_id=None):
  if type(expected_generation) is not int or expected_generation<0 or mode not in {'shared','dedicated'} or observed_state not in {'active','paused','absent'} or not all(isinstance(v,str) and REFERENCE.fullmatch(v) for v in [job_id,observation_reference]) or (replaces_shared_job_id is not None and (not isinstance(replaces_shared_job_id,str) or not REFERENCE.fullmatch(replaces_shared_job_id))):return {'state':'not_executed','code':'invalid_recovery_schedule'}
  with self.journal.lock(),self.journal.db() as c:
   self._refresh(c);s=schedule(c)
   if s['generation']!=expected_generation:
    # An old cancellation may already have happened externally. Invalidate its old binding.
    if s['job_id']==job_id and observed_state in {'absent','paused'}:
     s.update(observed_state=observed_state,observed_at=now(),observed_generation=expected_generation);save_schedule(c,s)
    return self._result(c,state='not_executed',code='schedule_changed')
   if replaces_shared_job_id is not None:
    if not (s['desired_active'] and s['mode']=='shared' and s['job_id']==replaces_shared_job_id and job_id!=s['job_id'] and mode=='dedicated' and observed_state=='active'):
     return self._result(c,state='not_executed',code='schedule_binding_conflict')
    old_job=s['job_id'];s['generation']+=1;expected_generation=s['generation']
    event(c,None,'shared_binding_transferred',{'preserved_job_id':old_job,'new_job_id':job_id,'generation':expected_generation})
   elif s['job_id'] and ((s['job_id']!=job_id and s['observed_state']=='active') or (s['job_id']==job_id and s['mode']!=mode)):
    return self._result(c,state='not_executed',code='schedule_binding_conflict')
   s.update(mode=mode,job_id=job_id,observed_state=observed_state,observed_at=now(),observed_generation=expected_generation,observation_reference=observation_reference)
   save_schedule(c,s);event(c,None,'schedule_observed',{'generation':expected_generation,'mode':mode,'state':observed_state})
   return self._result(c)
