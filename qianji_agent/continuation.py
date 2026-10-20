"""Dependency decisions from immutable plans; never a replay or ledger API."""
from .codec import loads
from .operations import native_equal,normalize

POLICY_VERSION='continuation-v1'
BALANCE_CONFLICTS={'balance_not_verified','task_balance_not_verified','shared_credit_parent_changed'}

def _id(value):
 if value is None or isinstance(value,bool):return None
 value=str(value)
 return value if value and value not in {'-1','0','None'} else None

def _object(value):
 if isinstance(value,str):value=loads(value)
 return value if isinstance(value,dict) else {}

def _scope(kind,accounts=(),objects=(),catalogs=(),complete=True,reason=None):
 return {'kind':kind,'account_ids':sorted(set(accounts)), 'object_refs':sorted(set(objects)),
         'catalog_refs':sorted(set(catalogs)),'complete':complete,'reason':reason}

def ordinary_metadata_matches(observed,expected):
 """A plain bill cannot silently gain a pack, refund, task or currency relation."""
 got=normalize(observed);want=normalize(expected)
 if not native_equal(got['packid'],want['packid']):return False
 actual=dict(got['extra'] or {});planned=dict(want['extra'] or {})
 for data in (actual,planned):
  if data.get('flag')==0:data.pop('flag')
 if set(actual)!=set(planned):return False
 for key,value in planned.items():
  if key=='tags':
   if {str(t['id']) for t in actual[key]}!={str(t['id']) for t in value}:return False
  elif not native_equal(actual[key],value):return False
 return True

def classify_pending(record,snapshot):
 """Recover only finite supported scopes; missing legacy facts are not empty scope."""
 p=record.get('plan') or {};a=p.get('action','');kind='relation'
 try:
  if p.get('collection')=='uploads':return _scope('upload')
  if a=='installment_create':
   c=p.get('installment_contract') or {};v=_object(p.get('params',{}).get('v'));d=_object(v.get('data'));asset=_object(d.get('asset'))
   account=_id(c.get('account'));cat=_id(c.get('category'));book=str(c['book'])
   if not account or not cat or not c.get('owner') or account!=_id(v.get('assetid')) or account!=_id(asset.get('id')) or str(v.get('userid'))!=str(c['owner']) or str(asset.get('userid'))!=str(c['owner']) or cat!=_id(d.get('cateid')):raise ValueError()
   return _scope('installment_create',[account],['installment:'+str(p['object_id'])] if p.get('object_id') else [],['book:'+book,'category:'+cat])
  if a=='bill_create':
   row=p.get('row') or {};extra=_object(row.get('extra'));account=_id(row.get('assetid'))
   if row.get('type') not in {0,1} or not account or set(p.get('balances',{}))!={account} or _id(row.get('fromid')) or _id(row.get('targetid')) or _id(row.get('packid')) or set(extra)-{'flag','tags'} or extra.get('tags') or any(p.get(k) for k in ('refund_source','scheduled_task','installment_contract','rows')):raise ValueError()
   oid=_id(row.get('id'));book=str(row['bookid']);category=_id(row.get('cateid'))
   if not oid or not category or not row.get('userid'):raise ValueError()
   for current in snapshot.get('bills',[]):
    if str(current.get('id'))==oid and (any(not native_equal(current.get(k),row.get(k)) for k in ('userid','bookid','type','assetid','fromid','targetid','money')) or not ordinary_metadata_matches(current,row)):
     return _scope('plain_bill',[account],['bill:'+oid],complete=False,reason='record_relationship_conflict')
    related=_object(current.get('extra'))
    if any(str(related.get(k))==oid for k in ('refundsid','presid','pretid','preinstallid')):raise ValueError()
   return _scope('plain_bill',[account],['bill:'+oid],['book:'+book,'category:'+category])
  if a.startswith('book_'):
   oid=_id(p.get('object_id'))
   if not oid:raise ValueError()
   return _scope('catalog',catalogs=['book:'+oid])
  if a.startswith('category_'):
   oid=_id(p.get('object_id'));params=p.get('params') or {};book=params.get('bookid',(p.get('expected') or {}).get('bookid'))
   if not oid or book is None:raise ValueError()
   ids={oid};changed=True
   while changed:
    children={str(r['id']) for r in snapshot.get('categories',[]) if str(r.get('parentid')) in ids};changed=not children.issubset(ids);ids|=children
   return _scope('catalog',catalogs=['category:'+i for i in ids])
  if a.startswith('tag_'):
   # First-release new bills have no tags, but unknown group scope is not guessed.
   raise ValueError()
  if a.startswith('account_'):
   oid=_id(p.get('object_id'))
   if not oid:raise ValueError()
   accounts={oid};v=_object(p.get('params',{}).get('v'));parent=_id(_object(v.get('credit')).get('shareid'))
   if parent:accounts.add(parent)
   for asset in snapshot.get('relationship_assets',snapshot.get('assets',[])):
    parent=_id(_object(asset.get('credit')).get('shareid'))
    if str(asset.get('id')) in accounts and parent:accounts.add(parent)
    if parent in accounts:accounts.add(str(asset['id']))
   accounts.update(str(x['id']) for x in p.get('related_credit_accounts',[]))
   if not set(p.get('balances',{})).issubset(accounts) or not any(str(x.get('id'))==oid for x in snapshot.get('relationship_assets',snapshot.get('assets',[]))):raise ValueError()
   return _scope('account',accounts,['account:'+i for i in accounts])
  # Relationship actions lacking a saved before-image or contract remain explicit gaps.
  accounts={str(k) for k in p.get('balances',{})};objects=[]
  if p.get('object_id'):objects.append(str(p.get('collection'))+':'+str(p['object_id']))
  if not accounts or a not in {'bill_update','bill_delete','bill_copy','refund_create','refund_update','debt_pay','debt_add','debt_finish','repeat_update','repeat_toggle','repeat_delete','installment_delete','installment_config','installment_prepay'}:raise ValueError()
  # balances can omit source objects; only a complete stored relationship scope suffices.
  scope=p.get('dependency_scope')
  if not isinstance(scope,dict) or set(scope.get('account_ids',[]))!=accounts or not scope.get('complete'):raise ValueError()
  return _scope(kind,accounts,objects,scope.get('catalog_refs',[]))
 except (ValueError,KeyError,TypeError,AttributeError):
  return _scope(kind,complete=False,reason='dependency_scope_unknown')

def _account_code(account,snapshot):
 assets=snapshot.get('relationship_assets',snapshot.get('assets',[]));found=[a for a in assets if str(a.get('id'))==account]
 if len(found)!=1:return 'dependency_scope_unknown'
 a=found[0]
 if a.get('currency','CNY')!='CNY' or a.get('loan') or a.get('status') not in {None,0,-1}:return 'account_dependency_not_adapted'
 if a.get('type')==1 and not a.get('credit'):return None
 if a.get('type')!=2 or not isinstance(a.get('credit'),dict):return 'account_dependency_not_adapted'
 if _id(a['credit'].get('shareid')) or any(_id(_object(x.get('credit')).get('shareid'))==account for x in assets):return 'credit_dependency_not_adapted'
 return None

def decide(records,command,snapshot,policy,halts):
 account=command.get('account_id');result={'allowed':False,'code':'previous_result_unknown','historical_refs':[],'affected_accounts':[account] if account else []}
 def reject(code):return {**result,'code':code}
 if any(h.get('state','active')=='active' and h.get('account_id') in ('*',account) for h in halts):return reject('account_halted')
 if not records and not halts:return {**result,'allowed':True,'code':None}
 forbidden={'to_account_id','fee','discount','tag_ids','image_keys','account_amount','base_amount','fee_base_amount'}
 if command.get('action')!='bill_create' or command.get('kind') not in {'expense','income'} or command.get('currency','CNY')!='CNY' or forbidden.intersection(command):return reject('continuation_not_adapted')
 code=_account_code(account,snapshot)
 if code:return reject(code)
 history=set(policy.get('historical_requests',[]))
 for record in records:
  dispatch=record.get('dispatch') or {}
  if dispatch.get('outcome')=='backend_error' and dispatch.get('error_code') in {'backend_rejected','feature_unavailable','reconnect_required'}:return reject('dependency_conflict')
  scope=classify_pending(record,snapshot)
  if scope['kind']=='upload':continue
  if not scope['complete']:return reject(scope.get('reason') or 'dependency_scope_unknown')
  receipt=record.get('receipt') or {}
  if receipt.get('verification_code') in BALANCE_CONFLICTS and account in scope['account_ids']:return reject('account_halted')
  # Catalog-only mutations intersect explicit new references, not all accounts.
  refs={'book:'+str(command.get('book_id')),'category:'+str(command.get('category_id'))}
  for c in snapshot.get('categories',[]):
   if str(c.get('id'))==command.get('category_id') and _id(c.get('parentid')):refs.add('category:'+str(c['parentid']))
  if scope['kind']=='catalog':
   if refs.intersection(scope['catalog_refs']):return reject('dependency_conflict')
   continue
  if account in scope['account_ids']:
   if record.get('request_id') not in history or scope['kind'] not in {'plain_bill','installment_create'}:return reject('dependency_conflict')
   result['historical_refs'].append(record['request_id'])
 return {**result,'allowed':True,'code':None}
