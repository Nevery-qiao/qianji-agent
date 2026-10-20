"""Account-level safety metadata in the existing operation journal, no finance API."""
import time
from .codec import dumps,loads,digest
from .continuation import BALANCE_CONFLICTS

def install(c):
 c.execute('CREATE TABLE IF NOT EXISTS continuation_policy (singleton INTEGER PRIMARY KEY CHECK(singleton=1), data TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS account_halts (cause_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, request_id TEXT, reason TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS account_watchpoints (account_id TEXT PRIMARY KEY, data TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS continuation_events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, data TEXT NOT NULL)')

def event(c,kind,data):c.execute('INSERT INTO continuation_events(kind,data) VALUES (?,?)',(kind,dumps(data)))

def policy(c):
 row=c.execute('SELECT data FROM continuation_policy WHERE singleton=1').fetchone()
 return loads(row[0]) if row else None

def plan_accounts(plan):
 # Plan fields are produced by our builders, never supplied as public account-scope hints.
 if plan.get('collection')=='uploads':return []
 ids=set(str(k) for k in plan.get('balances',{}));contract=plan.get('installment_contract') or {}
 ids.update(str(k) for k in plan.get('task_balance_ids',[]) if str(k) not in {'-1','0','None'})
 ids.update(str(plan.get('task_data',{}).get(k)) for k in ('fromid','targetid') if plan.get('task_data',{}).get(k) not in (None,-1,0))
 if plan.get('collection') in {'repeat','installment'} and plan.get('object_id'):
  task_key=plan['collection']+':'+str(plan['object_id'])
  ids.update(aid for aid,point in plan.get('watch_context',{}).get('before_points',{}).items() if task_key in point['tasks'])
 if contract.get('account'):ids.add(str(contract['account']))
 if plan.get('collection')=='assets' and plan.get('object_id'):ids.add(str(plan['object_id']))
 if plan.get('collection')=='assets' and plan.get('object_id'):
  oid=str(plan['object_id']);before=plan.get('watch_context',{}).get('before_points',{})
  ids.update(aid for aid,point in before.items() if oid in point['structure'].get('credit_members',{}))
  parent=(plan.get('expected',{}).get('credit') or {}).get('shareid')
  if parent not in (None,-1,0,''):ids.add(str(parent))
 ids.update(str(a['id']) for a in plan.get('related_credit_accounts',[]))
 if ids:return sorted(ids)
 # Finite catalog mutations have no account scope, not an unknown owner scope.
 if plan.get('object_id') and plan.get('action','').startswith(('book_','category_')):return []
 return ['*']

def cause(c,rid,plan,reason='pending_operation'):
 for account in plan_accounts(plan):
  key='request:'+rid+':'+account
  inserted=c.execute('INSERT OR IGNORE INTO account_halts VALUES (?,?,?,?,?,?)',(key,account,rid,reason,'active',dumps({'created_at':int(time.time())}))).rowcount
  if inserted:event(c,'halt_started',{'cause_id':key,'account_id':account,'request_id':rid,'reason':reason})

def activate(c,version):
 result=policy(c)
 if result is None:
  records=c.execute("SELECT request_id,plan,receipt FROM operations WHERE state='pending_verification' ORDER BY created_at,request_id").fetchall();historical=[]
  for rid,raw,receipt in records:
   plan=loads(raw)
   if plan.get('collection')=='uploads':continue
   proof=loads(receipt) if receipt else {}
   if proof.get('verification_code') in BALANCE_CONFLICTS:cause(c,rid,plan,'existing_balance_conflict')
   else:historical.append(rid)
  result={'version':version,'activated_at':int(time.time()),'historical_requests':historical}
  c.execute('INSERT INTO continuation_policy VALUES(1,?)',(dumps(result),));event(c,'policy_activated',result)
 elif result['version']!=version:raise ValueError('continuation_policy_version_conflict')
 sync(c,result);return result

def sync(c,p=None):
 p=p or policy(c)
 if p is None:return
 historical=set(p['historical_requests'])
 for rid,raw,receipt,state in c.execute('SELECT request_id,plan,receipt,state FROM operations').fetchall():
  plan=loads(raw)
  if plan.get('collection')=='uploads':continue
  if state=='pending_verification':
   proof=loads(receipt) if receipt else {}
   if rid not in historical or proof.get('verification_code') in BALANCE_CONFLICTS:cause(c,rid,plan)
  elif state in {'verified','failed'}:
   changed=c.execute("UPDATE account_halts SET state='resolved' WHERE request_id=? AND state='active'",(rid,)).rowcount
   if changed:event(c,'request_halt_resolved',{'request_id':rid,'result':state})

def active(c):
 sync(c)
 rows=c.execute("SELECT cause_id,account_id,request_id,reason,state FROM account_halts WHERE state='active' ORDER BY cause_id").fetchall()
 return [dict(zip(('cause_id','account_id','request_id','reason','state'),r)) for r in rows]

def watch_state(c):
 return {'watchpoints':{a:loads(data) for a,data in c.execute('SELECT account_id,data FROM account_watchpoints')},'policy':policy(c)}

def store_review(c,receipt,watchpoints):
 event(c,'account_review',receipt)
 for account in receipt.get('accounts',[]):
  if account.get('state')!='halted':continue
  aid=account['account_id'];reason=account['code']
  if c.execute("SELECT 1 FROM account_halts WHERE account_id=? AND reason=? AND state='active'",(aid,reason)).fetchone():continue
  sources=account.get('request_ids',[])
  if reason!='account_drift_unexplained' and not sources:continue
  for rid in sources or [None]:
   key='request:'+rid+':'+aid if rid else 'review:'+receipt['review_id']+':'+aid
   added=c.execute('INSERT OR IGNORE INTO account_halts VALUES (?,?,?,?,?,?)',(key,aid,rid,reason,'active',dumps({'review_id':receipt['review_id'],'observed_at':receipt['observed_at']}))).rowcount
   if added:event(c,'halt_started',{'cause_id':key,'account_id':aid,'reason':reason})
 for aid,data in watchpoints.items():
  if c.execute("SELECT 1 FROM account_halts WHERE account_id IN (?, '*') AND state='active'",(aid,)).fetchone():continue
  if data is None:c.execute('DELETE FROM account_watchpoints WHERE account_id=?',(aid,))
  else:c.execute('INSERT INTO account_watchpoints VALUES (?,?) ON CONFLICT(account_id) DO UPDATE SET data=excluded.data',(aid,dumps(data)))

def finish(c,rid,receipt,watchpoints=None):
 if policy(c) is None:return
 if receipt['state'] in {'verified','failed'}:
  changed=c.execute("UPDATE account_halts SET state='resolved' WHERE request_id=? AND state='active'",(rid,)).rowcount
  if changed:event(c,'request_halt_resolved',{'request_id':rid,'result':receipt['state']})
 if watchpoints:
  if receipt['state']!='verified':raise ValueError('unverified_watchpoint')
  store_review(c,{'review_id':'verified:'+rid,'observed_at':int(time.time()),'accounts':[]},watchpoints)
  plan=loads(c.execute('SELECT plan FROM operations WHERE request_id=?',(rid,)).fetchone()[0])
  event(c,'continuation_verified',{'request_id':rid,'accounts':list(watchpoints),'historical_refs':plan.get('continuation',{}).get('historical_refs',[])})

def points(snapshot):
 """Partition evidence by actual account references; unrelated bills never enter a point."""
 assets=list({str(a['id']):a for a in snapshot.get('relationship_assets',[])+snapshot['assets']}.values());bills=snapshot['bills'];result={}
 if len({str(a['id']) for a in assets})!=len(assets) or len({str(b['id']) for b in bills})!=len(bills):raise ValueError('incomplete_sync')
 for asset in assets:
  from decimal import Decimal
  aid=str(asset['id']);money=format(Decimal(str(asset['money'])).normalize(),'f')
  structure={k:v for k,v in asset.items() if k not in {'money','updatetime','lastpaytime'}}
  if asset.get('type')==2:
   related=snapshot.get('relationship_assets',assets)
   structure['credit_members']={str(a['id']):{k:a.get(k) for k in ('type','status','currency','credit')} for a in related if str((a.get('credit') or {}).get('shareid'))==aid}

  related={str(b['id']):digest(b) for b in bills if aid in {str(b.get(k)) for k in ('assetid','fromid','targetid')}}
  tasks={}
  for collection in ('repeat','installment'):
   for task in snapshot.get(collection,[]):
    data=task.get('data') or {};data=loads(data) if isinstance(data,str) else data
    refs={str(task.get('assetid'))}|{str(data.get(k)) for k in ('fromid','targetid')}
    if aid in refs:tasks[collection+':'+str(task['id'])]=digest(task)
  result[aid]={'balance':money,'structure':structure,'bills':related,'tasks':tasks}
 return result

def review(snapshot,watch_state,pending,policy):
 from .continuation import classify_pending
 current=points(snapshot);halting={};sources={};history=set(policy.get('historical_requests',[]))
 for h in watch_state.get('halts',[]):
  halting[h['account_id']]=h['reason']
  if h.get('request_id'):sources.setdefault(h['account_id'],set()).add(h['request_id'])
 for record in pending:
  scope=classify_pending(record,snapshot)
  if scope['kind']=='upload':continue
  if not scope['complete']:
   halting['*']=scope.get('reason') or 'dependency_scope_unknown';sources.setdefault('*',set()).add(record['request_id'])
  elif record['request_id'] not in history:
   for aid in scope['account_ids']:
    halting[aid]='pending_operation';sources.setdefault(aid,set()).add(record['request_id'])
 observed=int(time.time());accounts=[];initial={};old=watch_state['watchpoints']
 for aid,point in current.items():
  code=halting.get('*') or halting.get(aid)
  if not code and aid in old and point!=old[aid]:code='account_drift_unexplained'
  if code:accounts.append({'account_id':aid,'state':'halted','code':code,'request_ids':sorted(sources.get(aid,set()))})
  else:
   accounts.append({'account_id':aid,'state':'matched','code':None})
   if aid not in old:initial[aid]=point
 if '*' in halting:accounts.append({'account_id':'*','state':'halted','code':halting['*'],'request_ids':sorted(sources.get('*',set()))})
 # A monitored account that disappeared is a change in that account, not all others.
 for aid in (set(old)|set(halting))-set(current)-{'*'}:
  accounts.append({'account_id':aid,'state':'halted','code':halting.get(aid,'account_drift_unexplained'),'request_ids':sorted(sources.get(aid,set())),'available':False})
 receipt={'contract':policy['version'],'scope_account_ids':sorted({a['account_id'] for a in accounts}),'review_id':'review-'+digest([observed,current,len(pending),time.time_ns()])[:24], 'observed_at':observed,
          'state':'matched' if all(a['state']=='matched' for a in accounts) else 'halted',
          'ready':all(a['state']=='matched' for a in accounts),'current':True,'accounts':accounts,
          'historical_count':sum(r['request_id'] in history for r in pending)}
 return {'receipt':receipt,'initial':initial,'points':current}

def verify_after(before_point,snapshot,plan):
 current=points(snapshot);accounts=plan.get('continuation',{}).get('accounts',[])
 if plan.get('action')!='bill_create' or len(accounts)!=1:raise ValueError('continuation_not_adapted')
 aid=accounts[0];after=current[aid];oid=str(plan['row']['id']);other={k:v for k,v in after['bills'].items() if k!=oid}
 from .continuation import ordinary_metadata_matches
 row=next((b for b in snapshot['bills'] if str(b['id'])==oid),None)
 if row is None or not ordinary_metadata_matches(row,plan['row']):raise ValueError('record_relationship_conflict')
 if after['structure']!=before_point['structure'] or after['tasks']!=before_point['tasks'] or other!=before_point['bills'] or oid not in after['bills']:raise ValueError('account_drift_unexplained')
 return {aid:after}


def verify_known_update(before,snapshot,plan,proof):
 """Advance only changes covered by a normally verified operation, preserving unrelated points."""
 current=points(snapshot);bill_ids={str(r['id']) for r in plan.get('rows',[])}|set(str(i) for i in proof.get('related_bill_ids',[]))|set(str(i) for i in plan.get('deleted_ids',[]))
 if plan.get('collection')=='bills' and proof.get('object_id'):bill_ids.add(str(proof['object_id']))
 if plan.get('row',{}).get('id'):bill_ids.add(str(plan['row']['id']))
 if plan.get('refund_source'):bill_ids.add(str(plan['refund_source']))
 asset_ids={str(proof['object_id'])} if plan.get('collection')=='assets' and proof.get('object_id') else set()
 task_ids={plan['collection']+':'+str(proof['object_id'])} if plan.get('collection') in {'repeat','installment'} and proof.get('object_id') else set()
 affected=set(plan_accounts(plan)) - {'*'};affected|=asset_ids
 for b in snapshot['bills']:
  if str(b['id']) in bill_ids:affected.update(str(b[k]) for k in ('assetid','fromid','targetid') if b.get(k) not in (None,-1,0))
 result={}
 for aid in affected:
  previous=before.get(aid);now=current.get(aid)
  if previous is None:
   if aid in asset_ids:
    if now is None or plan.get('object_id') or aid in plan.get('before_ids',[]):raise ValueError('account_drift_unexplained')
    result[aid]=now
   continue
  if now is None:
   if aid in asset_ids and plan.get('delete'):result[aid]=None;continue
   raise ValueError('account_drift_unexplained')
  checked_balances=set(plan.get('balances',{}))|{str(a['id']) for a in plan.get('related_credit_accounts',[])}
  if plan.get('task_data'):checked_balances.update(plan.get('task_baseline',{}))
  if aid not in checked_balances and now['balance']!=previous['balance']:raise ValueError('account_drift_unexplained')
  from copy import deepcopy
  from .operations import native_equal
  expected_structure=deepcopy(previous['structure'])
  # Only fields already checked by the native verifier may move the watchpoint.
  if aid in asset_ids:
   for key,value in plan.get('expected',{}).items():
    if key not in {'money','updatetime','lastpaytime'}:expected_structure[key]=value
  history=plan.get('debt_history') or {}
  if str(history.get('id'))==aid:
   for key in ('loan','status','stype'):expected_structure[key]=history[key]
  # A verified child edit changes its parent's member projection, not arbitrary
  # parent fields or other children. Use only the child's verified field deltas.
  for child in asset_ids:
   old_child=before.get(child)
   if old_child is None or 'credit_members' not in expected_structure:continue
   wanted=deepcopy(old_child['structure'])
   wanted.update({k:v for k,v in plan.get('expected',{}).items() if k not in {'money','updatetime','lastpaytime'}})
   members=expected_structure['credit_members'];members.pop(child,None)
   if not plan.get('delete') and str((wanted.get('credit') or {}).get('shareid'))==aid:
    members[child]={k:wanted.get(k) for k in ('type','status','currency','credit')}
  if not native_equal(now['structure'],expected_structure):raise ValueError('account_drift_unexplained')
  for key,allowed in (('bills',bill_ids),('tasks',task_ids)):
   if {k:v for k,v in now[key].items() if k not in allowed}!={k:v for k,v in previous[key].items() if k not in allowed}:raise ValueError('account_drift_unexplained')
  result[aid]=now
 return result
