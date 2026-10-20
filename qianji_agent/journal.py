"""Private local operation journal, shared by stdio/CLI processes for one owner.

No official App database access. A pending dispatch is never sent again.
"""
import fcntl,os,sqlite3,hashlib,json,time
from pathlib import Path
from contextlib import contextmanager
from .codec import dumps,loads

class Journal:
 def __init__(self,root,owner):
  self.root=Path(root).expanduser().absolute()
  if self.root.is_symlink():raise ValueError('unsafe_state_path')
  self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
  if self.root.stat().st_uid!=os.getuid() or self.root.stat().st_mode&0o077:raise ValueError('unsafe_state_permissions')
  self.path=self.root/'operations.sqlite3'
  fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
  try:
   if os.fstat(fd).st_uid!=os.getuid() or os.fstat(fd).st_mode&0o077:raise ValueError('unsafe_state_permissions')
  finally:os.close(fd)
  self.owner=hashlib.sha256(owner.encode()).hexdigest()
  with self.lock(),self.db() as c:
   c.execute('CREATE TABLE IF NOT EXISTS identity (owner TEXT NOT NULL)')
   row=c.execute('SELECT owner FROM identity').fetchone()
   if row is not None and row[0]!=self.owner:raise ValueError('account_changed')
   if row is None:c.execute('INSERT INTO identity VALUES (?)',(self.owner,))
   c.execute('CREATE TABLE IF NOT EXISTS storage_evidence (request_id TEXT PRIMARY KEY, proof TEXT NOT NULL)')
   c.execute('CREATE TABLE IF NOT EXISTS operations (request_id TEXT PRIMARY KEY, hash TEXT NOT NULL, state TEXT NOT NULL, plan TEXT NOT NULL, receipt TEXT, created_at INTEGER NOT NULL)')
   c.execute('CREATE TABLE IF NOT EXISTS dispatch_evidence (request_id TEXT PRIMARY KEY, proof TEXT NOT NULL)')
   from .account_watch import install as install_watch
   install_watch(c)
   from .recovery import install
   install(c)
 def __repr__(self):return '<Journal: private local state>'
 @contextmanager
 def db(self):
  c=sqlite3.connect(self.path,timeout=30)
  try:
   c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA journal_mode=DELETE')
   with c:yield c
  finally:c.close()
 @contextmanager
 def lock(self):
  fd=os.open(self.root/'account.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
  try:
   if os.fstat(fd).st_uid!=os.getuid() or os.fstat(fd).st_mode&0o077:raise ValueError('unsafe_state_permissions')
   fcntl.flock(fd,fcntl.LOCK_EX);yield
  finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
 def get(self,request_id):
  with self.db() as c:r=c.execute('SELECT hash,state,plan,receipt FROM operations WHERE request_id=?',(request_id,)).fetchone()
  return None if r is None else {'hash':r[0],'state':r[1],'plan':loads(r[2]),'receipt':loads(r[3]) if r[3] else None}
 def unresolved(self):
  with self.db() as c:found=c.execute("SELECT request_id,plan FROM operations WHERE state='pending_verification' ORDER BY created_at").fetchall()
  return next((rid for rid,plan in found if loads(plan).get('collection')!='uploads'),None)
 def pending_financial(self):
  with self.db() as c:
   rows=c.execute("SELECT o.request_id,o.plan,d.proof FROM operations o LEFT JOIN dispatch_evidence d USING(request_id) WHERE o.state='pending_verification' ORDER BY o.created_at,o.request_id").fetchall()
  return [{'request_id':rid,'plan':loads(plan),'dispatch':loads(proof) if proof else None,'receipt':self.get(rid)['receipt']} for rid,plan,proof in rows if loads(plan).get('collection')!='uploads']
 def record_dispatch(self,request_id,proof):
  from .dispatch import private_response,ERROR_CODES
  if not isinstance(proof,dict) or set(proof)-{'outcome','response','error_code','exception_type'}:raise ValueError('invalid_dispatch_evidence')
  if proof.get('outcome') not in {'response_received','backend_error','transport_unknown'}:raise ValueError('invalid_dispatch_evidence')
  if proof['outcome']=='response_received':
   if set(proof)!={'outcome','response'}:raise ValueError('invalid_dispatch_evidence')
  elif proof.get('error_code') not in ERROR_CODES:raise ValueError('invalid_dispatch_evidence')
  with self.db() as c:
   if c.execute('SELECT 1 FROM operations WHERE request_id=?',(request_id,)).fetchone() is None:raise ValueError('request_not_found')
   try:c.execute('INSERT INTO dispatch_evidence VALUES (?,?)',(request_id,dumps(private_response(proof))))
   except sqlite3.IntegrityError:raise ValueError('dispatch_evidence_already_recorded') from None
 def dispatch_evidence(self,request_id):
  with self.db() as c:r=c.execute('SELECT proof FROM dispatch_evidence WHERE request_id=?',(request_id,)).fetchone()
  return loads(r[0]) if r else None
 def observe(self,request_id,proof):
  if set(proof)!={'key','hash'} or not all(isinstance(v,str) for v in proof.values()):raise ValueError('invalid_storage_proof')
  with self.db() as c:c.execute('INSERT OR REPLACE INTO storage_evidence VALUES (?,?)',(request_id,dumps(proof)))
 def evidence(self,request_id):
  with self.db() as c:r=c.execute('SELECT proof FROM storage_evidence WHERE request_id=?',(request_id,)).fetchone()
  return loads(r[0]) if r else None
 def start(self,request_id,fingerprint,plan):
  try:
   with self.db() as c:
    c.execute('INSERT INTO operations VALUES (?,?,?,?,?,?)',(request_id,fingerprint,'pending_verification',dumps(plan),None,int(time.time())))
    from .recovery import start
    start(c,request_id)
    from .account_watch import policy,cause
    if policy(c) is not None:cause(c,request_id,plan)
  except sqlite3.IntegrityError as error:
   if error.sqlite_errorcode in {sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY,sqlite3.SQLITE_CONSTRAINT_UNIQUE}:raise ValueError('request_already_recorded') from None
   raise
 def finish(self,request_id,receipt,reviewed=False,*,watchpoints=None):
  if receipt['state'] not in ('verified','failed','pending_verification'):raise ValueError('invalid_receipt')
  with self.db() as c:
   c.execute('UPDATE operations SET state=?,receipt=? WHERE request_id=?',(receipt['state'],dumps(receipt),request_id))
   from .recovery import observe
   observe(c,request_id,receipt,reviewed)
   from .account_watch import finish
   finish(c,request_id,receipt,watchpoints)
 def verified_images(self):
  with self.db() as c:records=c.execute("SELECT receipt FROM operations WHERE state='verified' AND receipt IS NOT NULL").fetchall()
  return [r['image_key'] for (raw,) in records if (r:=loads(raw)).get('image_key')]
 def backup(self,destination):
  p=Path(destination)
  if p.exists() or p.is_symlink():raise ValueError('backup_destination_exists')
  fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
  with self.lock(),self.db() as source:
   dest=sqlite3.connect(p)
   try:source.backup(dest)
   finally:dest.close()

 def activate_continuation(self,policy_version):
  from .account_watch import activate
  with self.db() as c:return activate(c,policy_version)
 def active_halts(self):
  from .account_watch import active
  with self.db() as c:return active(c)
 def watch_state(self):
  from .account_watch import watch_state
  with self.db() as c:
   from .account_watch import active
   result=watch_state(c);result['halts']=active(c);return result
 def record_account_review(self,receipt,watchpoints):
  from .account_watch import store_review
  with self.db() as c:store_review(c,receipt,watchpoints)

 def continuation_context(self,request_id):
  with self.db() as c:
   rows=c.execute("SELECT data FROM continuation_events WHERE kind='continuation_verified'").fetchall()
   return any(request_id in loads(raw).get('historical_refs',[]) for (raw,) in rows)
