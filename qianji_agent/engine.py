"""One execution core for every Agent entry point. No blind write retry."""
import re,time
from decimal import Decimal
from pathlib import Path
from .readers import pull_bills,read_accounts
from .codec import digest,dumps,timestamp,loads
from .journal import Journal
from .operations import prepare,verify,tags
from .transport import QianjiError
from .dispatch import dispatch_success,dispatch_error,verification_code,REJECTIONS

SAFE_CODES=set('unsupported_operation unexpected_fields object_missing_or_ambiguous owner_mismatch version_conflict invalid_text unsupported_bill_shape specialized_bill_operation_required category_mismatch currency_adapter_required unsupported_bill_kind invalid_transfer repayment_requires_credit refund_requires_cny_expense refund_exceeds_remaining unknown_refund_shape not_refund name_ambiguous default_book_delete_forbidden object_has_references object_has_task_references account_shape_requires_adapter unsupported_account_kind invalid_credit_day invalid_replacement category_has_children invalid_category_kind invalid_icon_reference invalid_category_parent tag_group_not_empty invalid_color invalid_amount invalid_id invalid_time explicit_offset_whole_seconds_required adapter_update_required reconnect_required feature_unavailable backend_rejected read_unavailable invalid_response transport_failure incomplete_sync invalid_filter invalid_request_id account_changed linked_bill_delete_requires_reconciliation'.split())

SAFE_CODES.update({'unsafe_state_path','backend_result_unknown','unsupported_task_shape','repeat_contract_requires_adapter','installment_fee_schedule_adapter_required','category_move_required','unsupported_prepay_relation','remove_installment_before_record_cleanup','book_visibility_state_conflict','app_login_required','app_not_installed','app_access_denied','app_state_unreadable','unexpected_destination','invalid_currency','base_currency_adapter_required','current_adapter_requires_cny_base_and_account','default_book_rename_requires_adapter','restore_account_before_delete','account_visibility_state_conflict','prepay_remaining_mismatch','prepay_requires_cny_accounts','repeat_kind_not_yet_verified','debt_finish_requires_zero_principal','tag_not_active','unverified_image_reference','image_path_must_be_absolute_regular_file','supported_image_required','currency_edit_requires_conversion','bill_id_collision','invalid_transfer_fee','finished_debt_amount_edit_requires_adapter','conflicting_credit_dates','unsupported_task_bill_relation','scheduled_task_changed','invalid_shared_credit','shared_limit_member_uses_parent','shared_limit_has_members','shared_credit_parent_changed','invalid_credit_limit','fee_conversion_inconsistent','historical_schedule_bill_changed','invalid_schedule_values','installment_bill_below_fee'})

SAFE_CODES.update({'dependency_scope_unknown','dependency_conflict','record_relationship_conflict','account_halted','account_drift_unexplained','continuation_not_adapted','credit_dependency_not_adapted','account_dependency_not_adapted','historical_balance_context_unattributed'})

SAFE_CODES.update({'invalid_image_content','image_pixel_limit_exceeded','animated_image_unsupported'})

def snapshot_digest(s):
 s={**s,'tags':[{k:v for k,v in g.items() if k!='createtime'} for g in s.get('tags',[])]}
 return digest(s)

def safe_code(e):
 c=e.code if isinstance(e,QianjiError) else str(e)
 return c if c in SAFE_CODES else ('missing_required_fields' if isinstance(e,KeyError) else 'validation_or_connection_failed')

def rows(data,key='list'):
 if not isinstance(data,dict) or not isinstance(data.get(key),list) or not all(isinstance(r,dict) for r in data[key]):raise QianjiError('invalid_response')
 return data[key]

def account_templates(data):
 output=[]
 for row in rows(data):
  model=row.get('type')
  if isinstance(model,dict) and {'name','type','stype','icon'}<=set(model):output.append(model)
 return output

def flatten(items):
 out=[]
 for r in items:
  if not isinstance(r,dict):raise QianjiError('invalid_response')
  out.append(r)
  if r.get('sublist'):
   if not isinstance(r['sublist'],list):raise QianjiError('invalid_response')
   out.extend(flatten(r['sublist']))
 return out

PUBLIC_FIELDS=set('visible id bookid name type stype money currency status incount icon color sort parentid level groupid tags assetid fromid targetid cateid time createtime updatetime remark packid extra images totalcount count totalmoney totalfee fee starttime data loan credit editable c symbol sign iscommon baseprice pricetime logo'.split())
NESTED_FIELDS=set('presid pretid preinstallid refundsid rfds refundid refundv bxid bxmoney bxstate bxs bxdid billflag currency tags flag curr ss sv ts tv bs bv baoxiaoed baoxiaotime baoxiaov bxsid feemoney transfee money rate frommoney tomoney start end date count repeat type value cateid fromid targetid remark images bookid fee time billflag totalpay startdate enddate accountId limit statedate paydate2 statein shareid prepay feetype lefttype feeincount'.split())
ID_FIELDS=set('presid pretid preinstallid id bookid assetid fromid targetid cateid packid parentid groupid refundsid refundid accountId shareid'.split())
MONEY_FIELDS=set('sv tv bv money totalmoney totalfee fee bxmoney feemoney transfee frommoney tomoney limit totalpay'.split())

def public_value(k,v,nested=False):
 if k in ID_FIELDS and v is not None:return str(v)
 if k in MONEY_FIELDS and v is not None:return format(Decimal(str(v)),'f')
 if isinstance(v,Decimal):return format(v,'f')
 if isinstance(v,dict):
  if k=='rfds':return {str(i):format(Decimal(str(n)),'f') for i,n in v.items()}
  return {a:public_value(a,b,True) for a,b in v.items() if a in NESTED_FIELDS or a in PUBLIC_FIELDS}
 if isinstance(v,list):return [public_value('',i,True) for i in v]
 return v

def public_row(row):
 out={k:public_value(k,loads(v) if k in ('extra','data','images') and isinstance(v,str) and v else v) for k,v in row.items() if k in PUBLIC_FIELDS}
 if isinstance(row.get('tags'),list):out['tags']=[public_row(t) for t in row['tags']]
 out['version']=digest(row);return out

class Engine:
 def __init__(self,transport,owner,state_dir=None,session_guard=None):
  self.transport=transport;self.owner=owner;self.session_guard=session_guard;self._last_account_review=None
  self.journal=Journal(state_dir or Path.home()/'Library/Application Support/qianji-agent',owner)
  with self.journal.lock():self.journal.activate_continuation('continuation-v1')
 def __repr__(self):return '<Engine: private connection omitted>'
 def snapshot(self,extended=False):
  books=rows(self.transport.read('book/list',{'t':-1}));assets=read_accounts(self.transport)
  bills,deletes=pull_bills(self.transport)
  categories=[]
  for book in books:categories.extend(flatten(rows(self.transport.read('category/listv2',{'bookid':str(book['bookid'])}))))
  result={'books':books,'assets':assets,'bills':bills,'deletes':deletes,'categories':categories,'tags':[],'repeat':[],'installment':[]}
  if extended:
   result['tags']=rows(self.transport.read('tag/list',{'status':-2,'lasttime':0}))
   for key,route,params in [('repeat','repeat_task/list',{'page':1,'flts':'{}'}),('installment','installment/list',{'flts':'{}'})]:
    d=self.transport.read(route,params);result[key]=rows(d)
    if d.get('hasmore',0) not in (0,False):raise QianjiError('incomplete_sync')
  return result
 def query(self,kind,filters=None):
  try:
   f={k:v for k,v in (filters or {}).items() if v is not None}
   if set(f)-{'book_id','account_id','category_id','object_id','kind','since','until','offset','limit','keyword','status'}:raise QianjiError('invalid_filter')
   allowed={'books':{'book_id','object_id','keyword'},'accounts':{'object_id','keyword','status'},'account_types':{'keyword'},'categories':{'book_id','object_id','keyword'},'tags':{'object_id','keyword'},'bills':{'book_id','account_id','category_id','object_id','kind','since','until','keyword'},'repeat':{'book_id','account_id','category_id','object_id','kind','keyword'},'installments':{'object_id','account_id','category_id','keyword'},'currencies':{'keyword'}}
   if kind not in allowed or set(f)-allowed[kind]-{'limit','offset'}:raise QianjiError('invalid_filter')
   limit=f.get('limit',100);offset=f.get('offset',0)
   if type(limit) is not int or not 1<=limit<=1000 or type(offset) is not int or offset<0:raise QianjiError('invalid_filter')
   routes={'books':('book/list',{'t':-1}),'accounts':('asset/list',{'status':0}),'categories':('category/listv2',{'bookid':f.get('book_id','-1')}),'tags':('tag/list',{'status':-2,'lasttime':0}),'repeat':('repeat_task/list',{'page':1,'flts':'{}'}),'installments':('installment/list',{'flts':'{}'}),'currencies':('currency/listv2',{})}
   if kind=='accounts':items=read_accounts(self.transport,f.get('status','active'))
   elif kind=='account_types':items=account_templates(self.transport.read('asset/typelist',{}))
   elif kind=='bills':items=self.snapshot()['bills']
   elif kind in routes:
    data=self.transport.read(*routes[kind]);items=rows(data)
    if data.get('hasmore',0) not in (0,False):raise QianjiError('incomplete_sync')
    if kind=='categories':items=flatten(items)
   else:raise QianjiError('invalid_filter')
   if kind=='accounts' and 'status' not in f and f.get('object_id') and not any(str(a.get('id'))==f['object_id'] for a in items):
    r=self.transport.read('asset/info',{'did':f['object_id']})
    if not isinstance(r,dict) or str(r.get('id'))!=f['object_id'] or str(r.get('userid'))!=self.owner:raise QianjiError('invalid_response')
    items=[r]
   if kind=='tags' and f.get('object_id') and not any(str(r.get('id'))==f['object_id'] for r in items):items=tags({'tags':items})
   def field_value(r,k):
    if k in r:return r[k]
    d=r.get('data') or {};d=loads(d) if isinstance(d,str) else d
    return d.get(k) if isinstance(d,dict) else None
   for field,native in [('book_id','bookid'),('category_id','cateid'),('object_id','bookid' if kind=='books' else 'id')]:
    if field in f:items=[r for r in items if str(field_value(r,native))==f[field]]
   if 'account_id' in f:items=[r for r in items if f['account_id'] in [str(field_value(r,k)) for k in ('assetid','fromid','targetid')]]
   if 'kind' in f:
    typ={'expense':0,'income':1,'transfer':2,'repayment':3,'reimburse_advance':5,'refund':20,'lend_collect':4,'borrow':6,'lend':7,'borrow_repay':9,'interest_expense':10,'interest_income':11}.get(f['kind'])
    if typ is None:raise QianjiError('invalid_filter')
    items=[r for r in items if r.get('type')==typ]
   if 'since' in f:items=[r for r in items if r.get('time',0)>=timestamp(f['since'])]
   if 'until' in f:items=[r for r in items if r.get('time',0)<timestamp(f['until'])]
   if 'keyword' in f:items=[r for r in items if f['keyword'] in (field_value(r,'remark') or r.get('name') or r.get('c') or '')]
   selected=items[offset:offset+limit]
   return {'state':'read','records':[public_row(r) for r in selected],'total':len(items),'next_offset':offset+limit if offset+limit<len(items) else None,'complete_source':True}
  except Exception as e:return {'state':'not_executed','code':safe_code(e)}
 def prepare(self,command,before):
  if getattr(getattr(self.transport,'session',None),'base_currency','CNY')!='CNY':raise QianjiError('base_currency_adapter_required')
  extra=[];needed=[]
  if command['action'].startswith('account_') and command.get('object_id'):needed.append(command['object_id'])
  if command['action']=='debt_bill_update':needed.append(command.get('related_id'))
  if command['action'] in ('bill_delete','debt_bill_update','scheduled_bill_update','scheduled_bill_copy','scheduled_bill_delete','installment_bill_update','installment_bill_copy','installment_bill_delete'):
   selected=[b for b in before['bills'] if str(b['id'])==command.get('object_id')]
   if len(selected)==1:
    row=selected[0];needed.extend(str(row.get(k)) for k in ('assetid','fromid','targetid') if isinstance(row.get(k),int) and row[k]>0)
  for oid in set(needed)-{None}: 
   if not any(str(a['id'])==oid for a in before['assets']):
    r=self.transport.read('asset/info',{'did':oid})
    if not isinstance(r,dict) or str(r.get('id'))!=oid or str(r.get('userid'))!=self.owner:raise QianjiError('invalid_response')
    before['assets']=before['assets']+[r];extra.append(oid)
  if command.get('currency','CNY')!='CNY':
   currencies=rows(self.transport.read('currency/listv2',{}))
   if not any(r.get('symbol')==command['currency'] for r in currencies):raise QianjiError('invalid_currency')
  if command['action']=='account_create' and command.get('account_kind','cash') not in ('cash','credit'):
   before={**before,'account_templates':account_templates(self.transport.read('asset/typelist',{}))}
  if command.get('image_keys'):before={**before,'uploaded_keys':self.journal.verified_images()}
  planning={**before,'relationship_assets':read_accounts(self.transport,'all')} if command['action'] in ('account_update','account_delete','account_rename') else before
  plan=prepare(command,planning,self.owner)
  for related in plan.get('related_credit_accounts',[]):
   if not any(str(a['id'])==str(related['id']) for a in before['assets']):extra.append(str(related['id']))
  plan['extra_asset_ids']=extra
  if command['action']=='account_delete' and extra:
   r=next(a for a in before['assets'] if str(a['id'])==command['object_id'])
   if r.get('type')!=5 or r.get('status')!=1:raise QianjiError('restore_account_before_delete')
   plan['closed_debt_subtype']=r['stype']
  return plan
 def _extended(self,c):return bool(c.get('tag_ids')) or c['action'] in ('bill_update','bill_copy','bill_delete') or not (c['action'].startswith('bill_') or c['action'].startswith('refund_'))
 def preview(self,command):
  try:
   plan=self.prepare(command,self.snapshot(self._extended(command)))
   return {'state':'preview','action':plan['action'],'expected_balances':{i:format(v,'f') for i,v in plan['balances'].items()},'requires_version':command.get('expected_version') is not None,'writes_sent':False}
  except Exception as e:return {'state':'unsupported' if safe_code(e)=='unsupported_operation' else 'not_executed','code':safe_code(e)}
 def execute(self,request_id,command):
  if not isinstance(request_id,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',request_id):return {'state':'not_executed','code':'invalid_request_id'}
  started=False
  try:
   fingerprint=digest(command)
   with self.journal.lock():
    if self.session_guard:self.transport=self.session_guard()
    old=self.journal.get(request_id)
    if old:
     if old['hash']!=fingerprint:return {'state':'not_executed','code':'request_conflict','request_id':request_id}
     if old['state']!='pending_verification':return old['receipt']
     from .recovery import RecoveryStore
     error=RecoveryStore(self.journal).begin_review(request_id)
     if error:return error
     if old['plan']['collection']=='uploads':
      try:self.journal.observe(request_id,self.transport.upload(old['plan']))
      except Exception:pass
     return self._reconcile(request_id,old['plan'])
    pending=self.journal.pending_financial();watch=self.journal.watch_state();guarded=True
    before=self.snapshot(True if guarded else self._extended(command));reviewed=None
    if guarded:
     before=self._relationship_snapshot(before)
     reviewed=self._review_accounts(before,pending,watch)
     from .continuation import decide
     decision=decide(pending,command,before,watch['policy'],self.journal.active_halts())
     if not decision['allowed']:
      # Preserve the original stop code for existing callers; expose finite detail separately.
      blocking=self.journal.active_halts();account=command.get('account_id')
      pending_cause=any(h['account_id'] in {'*',account} and (h['request_id'] is not None or h['reason']=='dependency_scope_unknown') for h in blocking)
      # Legacy callers already stop on this code while a newer unknown remains.
      pending_cause=pending_cause or any(r['request_id'] not in watch['policy']['historical_requests'] for r in pending)
      compatibility=pending and (decision['code'] in {'dependency_conflict','dependency_scope_unknown','account_dependency_not_adapted'} or (decision['code']=='account_halted' and pending_cause))
      return {'state':'not_executed','code':'previous_result_unknown' if compatibility else decision['code'],'request_id':request_id,'account_review':reviewed['receipt'],'continuation':{'contract':'continuation-v1','decision_code':decision['code']}}

    plan=self.prepare(command,before)
    if guarded and command['action']=='bill_create' and command.get('kind') in {'expense','income'}:
     aid=command['account_id'];plan['continuation']={'contract':'continuation-v1','accounts':[aid],'historical_refs':decision['historical_refs'],'before_point':reviewed['points'][aid]}
    elif guarded:
     # prepare may read an exact hidden/finished target into the before image.
     from .account_watch import points
     plan['watch_context']={'before_points':points(before)}
    from .isolation import annotate
    annotate(plan,before)
    plan['extended']=True if guarded else self._extended(command);plan['before_digest']=snapshot_digest(before);plan['owner']=self.owner
    if self.session_guard:self.transport=self.session_guard()
    if getattr(getattr(self.transport,'session',None),'base_currency','CNY')!='CNY':raise QianjiError('base_currency_adapter_required')
    self.journal.start(request_id,fingerprint,plan)
    started=True
    if plan['collection']=='uploads':
     try:self.journal.observe(request_id,self.transport.upload(plan))
     except Exception:pass
    else:
     try:response=self.transport.write(plan['route'],plan['params'])
     except Exception as e:dispatch=dispatch_error(e)
     else:dispatch=dispatch_success(response)
     self.journal.record_dispatch(request_id,dispatch)
    after=None
    try:
     after=self.snapshot(plan['extended']) if plan['collection']!='uploads' else None
     if guarded and after is not None:after=self._relationship_snapshot(after)
     proof=self.verify(plan,after,request_id)
     receipt={'state':'verified','request_id':request_id,'action':plan['action'],**proof}
     watchpoints=self._verified_watchpoints(plan,after,receipt)
    except Exception as e:receipt=self._pending(request_id,plan,e,after);watchpoints=None
    self.journal.finish(request_id,receipt,watchpoints=watchpoints);return receipt
  except Exception as e:
   if started:return self._pending(request_id,plan,e)
   return {'state':'unsupported' if safe_code(e)=='unsupported_operation' else 'not_executed','code':safe_code(e),'request_id':request_id}
 def _relationship_snapshot(self,snapshot):
  result={**snapshot}
  state=self.journal.watch_state();known=set(state['watchpoints'])|{h['account_id'] for h in state['halts'] if h['account_id']!='*'}
  missing=known-{str(a['id']) for a in snapshot['assets']}
  result['relationship_assets']=read_accounts(self.transport,'all') if missing or any(a.get('type')==2 for a in snapshot['assets']) else snapshot['assets']
  return result
 def _review_accounts(self,snapshot,pending=None,watch=None):
  from .account_watch import review
  pending=self.journal.pending_financial() if pending is None else pending;watch=self.journal.watch_state() if watch is None else watch
  result=review(snapshot,watch,pending,watch['policy'])
  self.journal.record_account_review(result['receipt'],result['initial']);self._last_account_review=result['receipt'];return result
 def account_review_summary(self):
  previous=self._last_account_review
  if previous is None:return {'state':'unavailable','ready':False,'current':False,'observed_at':None,'accounts':[]}
  return {**previous,'state':'cached','source':'cached','readiness_at_observation':previous['ready'],'current':False,'ready':False}
 def account_review(self):
  try:
   with self.journal.lock():
    if self.session_guard:self.transport=self.session_guard()
    snapshot=self._relationship_snapshot(self.snapshot(True));result=self._review_accounts(snapshot)
    return {'state':'read','account_review':result['receipt']}
  except Exception as error:
   return {'state':'not_executed','code':safe_code(error),'account_review':{'state':'unavailable','ready':False,'current':False,'observed_at':None,'accounts':[]}}
 def _verified_watchpoints(self,plan,after,receipt):
  if plan.get('collection')=='uploads':return None
  if not plan.get('continuation'):
   if plan.get('watch_context'):
    from .account_watch import verify_known_update
    return verify_known_update(plan['watch_context']['before_points'],after,plan,receipt)
   return None
  from .account_watch import verify_after
  points=verify_after(plan['continuation']['before_point'],after,plan)
  receipt['continuation']={'contract':'continuation-v1','account_id':plan['continuation']['accounts'][0],'historical_count':len(plan['continuation']['historical_refs']),'history_unreconciled':bool(plan['continuation']['historical_refs']),'observed_at':int(time.time())}
  return points
 def verify(self,plan,after,request_id):
  if plan['collection']=='uploads':
   from .attachments import verify_upload
   observed=self.journal.evidence(request_id)
   try:
    proof=verify_upload(plan)
    if observed=={'key':plan['storage_key'],'hash':plan['etag']}:proof['storage_hash_verified']=True
    return proof
   except Exception:
    if observed and observed=={'key':plan['storage_key'],'hash':plan['etag']}:return {'object_id':plan['storage_key'],'image_key':plan['storage_key'],'storage_hash_verified':True,'file_content_verified':False,'image_pixels_verified':False}
    raise
  if plan['action'] in ('debt_finish','account_archive','account_restore'):
   r=self.transport.read('asset/info',{'did':plan['object_id']})
   if not isinstance(r,dict) or str(r.get('id'))!=plan['object_id'] or str(r.get('userid'))!=self.owner:raise QianjiError('invalid_response')
   self._merge_observed_asset(after,r)
  if plan.get('closed_debt_subtype'):
   closed=rows(self.transport.read('asset/listloan',{'t':plan['closed_debt_subtype'],'status':1}))
   if any(str(r['id'])==plan['object_id'] for r in closed):raise QianjiError('deletion_not_verified')
  if plan.get('extra_asset_ids') and (plan['collection']!='assets' or not plan.get('delete')):
   for oid in plan['extra_asset_ids']:
    if not any(str(a['id'])==oid for a in after['assets']):
     r=self.transport.read('asset/info',{'did':oid})
     if not isinstance(r,dict) or str(r.get('id'))!=oid or str(r.get('userid'))!=self.owner:raise QianjiError('invalid_response')
     self._merge_observed_asset(after,r)
  return verify(plan,after)
 def _merge_observed_asset(self,snapshot,row):
  # Native verification and watchpoints must consume the SAME latest read.
  for field in ('assets','relationship_assets'):
   if field in snapshot:snapshot[field]=[a for a in snapshot[field] if str(a['id'])!=str(row['id'])]+[row]
 def _pending(self,request_id,plan,error,after=None):
  result={'state':'pending_verification','request_id':request_id,'action':plan['action'],'code':'result_unknown','safe_to_resend':False}
  if plan['collection']=='uploads':return result
  unavailable=False
  try:evidence=self.journal.dispatch_evidence(request_id)
  except Exception:evidence=None;unavailable=True
  result.update(dispatch_state=evidence['outcome'] if evidence else ('unavailable' if unavailable else 'not_recorded'),verification_code=verification_code(error))
  try:
   if result['verification_code'] in {'balance_not_verified','task_balance_not_verified'} and self.journal.continuation_context(request_id):result['verification_code']='historical_balance_context_unattributed'
  except Exception:pass
  if evidence and evidence.get('error_code'):result['dispatch_error_code']=evidence['error_code']
  if evidence and evidence['outcome']=='backend_error' and evidence.get('error_code') in REJECTIONS and isinstance(after,dict):
   try:
    if snapshot_digest(after)==plan.get('before_digest'):result.update(state='failed',code='backend_rejected_no_effect_verified')
   except Exception:pass
  return result
 def _reconcile(self,request_id,plan):
  after=None
  try:
   after=self.snapshot(plan.get('extended',False)) if plan['collection']!='uploads' else None
   if (plan.get('continuation') or plan.get('watch_context')) and after is not None:after=self._relationship_snapshot(after)
   proof=self.verify(plan,after,request_id);r={'state':'verified','request_id':request_id,'action':plan['action'],**proof}
   watchpoints=self._verified_watchpoints(plan,after,r)
  except Exception as e:r=self._pending(request_id,plan,e,after);watchpoints=None
  try:self.journal.finish(request_id,r,watchpoints=watchpoints)
  except Exception as e:return self._pending(request_id,plan,e)
  return r
 def operation(self,request_id,automatic=False):
  with self.journal.lock():
   if self.session_guard:self.transport=self.session_guard()
   r=self.journal.get(request_id)
   if r is None:return {'state':'not_executed','code':'request_not_found'}
   if r['state']=='pending_verification':
    from .recovery import RecoveryStore
    error=RecoveryStore(self.journal).begin_review(request_id,automatic)
    if error:return error
   return self._reconcile(request_id,r['plan']) if r['state']=='pending_verification' else r['receipt']
 def recovery_list(self,include_closed=False,offset=0,limit=100):
  from .recovery import RecoveryStore
  return RecoveryStore(self.journal).list(include_closed,offset,limit)
 def recovery_ack(self,request_id,expected_version,disposition,completion_reference):
  from .recovery import RecoveryStore
  return RecoveryStore(self.journal).ack(request_id,expected_version,disposition,completion_reference)
 def recovery_scheduler(self,action='status',**kwargs):
  from .recovery import RecoveryStore
  store=RecoveryStore(self.journal)
  if action=='status' and not kwargs:return store.scheduler()
  if action=='record':return store.scheduler_record(**kwargs)
  return {'state':'not_executed','code':'invalid_recovery_schedule'}
