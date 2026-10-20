"""Native business plans. Callers cannot choose wire routes or owner identity."""
import time,secrets,re
from copy import deepcopy
from decimal import Decimal
from .codec import ident,amount,timestamp,dumps,loads,digest
from .credit import apply_credit,apply_shared,SETTINGS as CREDIT_SETTINGS

FIELDS={'id','userid','bookid','type','money','status','cateid','time','createtime','remark','updatetime','assetid','fromid','targetid','category','extra','fromact','targetact','packid','platform','username','bookname','images'}
DEFAULTS={'remark':None,'updatetime':0,'assetid':-1,'fromid':-1,'targetid':-1,'category':None,'extra':None,'fromact':None,'targetact':None,'packid':-1,'platform':0,'username':None,'bookname':None,'images':None}
COMMON={'action','expected_version'}
BILL_CREATE={'kind','book_id','account_id','to_account_id','category_id','amount','time','remark','currency','include_statistics','include_budget','fee','discount','tag_ids','image_keys','account_amount','base_amount','fee_base_amount'}
ALLOWED={
 'bill_create':BILL_CREATE,'bill_copy':{'object_id','time','remark'},'bill_update':{'book_id','account_id','to_account_id','currency','object_id','amount','time','remark','category_id','include_statistics','include_budget','fee','discount','tag_ids','image_keys','account_amount','base_amount','fee_base_amount'},'bill_delete':{'object_id'},
 'refund_create':{'object_id','account_id','amount','time','remark','currency','account_amount','base_amount'},'refund_update':{'object_id','account_id','amount','time','remark','currency','account_amount','base_amount'},
 'book_archive':{'object_id'},'book_restore':{'object_id'},'book_create':{'name'},'book_rename':{'object_id','name'},'book_delete':{'object_id'},
 'account_create':{'name','account_kind','amount','remark','limit','statement_day','payment_day','payment_after_statement_days','statement_inclusive','include_in_total','currency'},'account_rename':{'object_id','name'},'account_update':{'clear_credit_limit','shared_limit_account_id','shared_limit_version','object_id','name','remark','include_in_total','limit','statement_day','payment_day','payment_after_statement_days','statement_inclusive'},'account_archive':{'object_id'},'account_restore':{'object_id'},'account_delete':{'object_id'},
 'category_promote':{'object_id'},'category_demote':{'object_id','parent_id'},'category_move':{'object_id','parent_id'},'category_create':{'name','book_id','kind','parent_id','icon'},'category_update':{'object_id','name','icon','parent_id'},'category_delete':{'object_id','replacement_id'},
 'tag_group_create':{'name'},'tag_group_rename':{'object_id','name'},'tag_group_delete':{'object_id'},
 'tag_create':{'name','group_id','color'},'tag_update':{'object_id','name','group_id','color'},'tag_archive':{'object_id'},'tag_delete':{'object_id'},
}

def select(rows,value,key='id',uid=None):
 matches=[r for r in rows if str(r.get(key))==value]
 if len(matches)!=1:raise ValueError('object_missing_or_ambiguous')
 r=deepcopy(matches[0])
 if uid is not None and 'userid' in r and str(r['userid'])!=uid:raise ValueError('owner_mismatch')
 return r

def version(c,row):
 if c.get('expected_version')!=digest(row):raise ValueError('version_conflict')

def text(v,maxlen=2000):
 if not isinstance(v,str) or not v.strip() or len(v)>maxlen:raise ValueError('invalid_text')
 return v

def normalize(raw):
 if set(raw)-FIELDS-{'descinfo'} or {'id','userid','bookid','type','money','status','cateid','time','createtime'}-set(raw):raise ValueError('unsupported_bill_shape')
 row={**DEFAULTS,**{k:v for k,v in deepcopy(raw).items() if k!='descinfo'}}
 for k in ('assetid','fromid','targetid','packid'):
  if row[k] is None:row[k]=-1
 if isinstance(row['images'],str):row['images']=loads(row['images']) if row['images'] else None
 if row['images'] is not None and (not isinstance(row['images'],list) or not all(isinstance(i,str) for i in row['images'])):raise ValueError('unsupported_image_shape')
 if row['extra']=='':row['extra']=None
 if isinstance(row['extra'],str):row['extra']=loads(row['extra'])
 if row['extra'] is not None and not isinstance(row['extra'],dict):raise ValueError('unsupported_bill_shape')
 return row

def make_row(uid,book_id,bill_id,now,kind=0):
 return {**DEFAULTS,'id':ident(bill_id),'userid':uid,'bookid':ident(book_id,True),'type':kind,'money':None,'status':2,'cateid':None,'time':now,'createtime':now,'updatetime':now}

def bill_request(row=None,delete=None):return {'v':dumps({'bills':{'dellist':[ident(delete)]} if delete else {'changelist':dumps([row])}})}

def balance_effect(row):
 m=Decimal(str(row['money']));kind=row['type'];effect={}
 extra=row.get('extra') or {};extra=loads(extra) if isinstance(extra,str) else extra
 if extra.get('curr'):
  cur=extra['curr']
  if kind not in (0,1,2,3,5) or cur.get('bs')!='CNY' or not isinstance(cur.get('ts'),str) or not re.fullmatch('[A-Z]{3}',cur['ts']):raise ValueError('currency_adapter_required')
  m=Decimal(str(cur['tv']))
 def add(i,n):
  if i is not None and int(i)>0:effect[str(i)]=effect.get(str(i),Decimal(0))+n
 if kind in (0,5):add(row['assetid'],-m)
 elif kind==1:add(row['assetid'],m)
 elif kind in (2,3):
  extra=row.get('extra') or {};extra=loads(extra) if isinstance(extra,str) else extra
  fee=Decimal(str(extra.get('transfee') or 0))
  if fee<0:raise ValueError('invalid_transfer_fee')
  if extra.get('curr'):
   if Decimal(str(extra['curr']['sv']))!=Decimal(str(row['money']))+fee:raise ValueError('invalid_transfer_fee')
   add(row['fromid'],-Decimal(str(extra['curr']['sv'])));add(row['targetid'],Decimal(str(extra['curr']['tv'])))
  else:add(row['fromid'],-m-fee);add(row['targetid'],m)
 elif kind in (4,6):add(row['assetid'],-m);add(row['targetid'],m)
 elif kind in (7,9):add(row['assetid'],m if kind==7 else m);add(row['fromid'],-m)
 elif kind in (10,11):add(row['assetid'],-m if kind==10 else m)
 else:raise ValueError('specialized_bill_operation_required')
 return effect

def bill_currencies(row):
 cur=(row.get('extra') or {}).get('curr')
 if not cur:return {}
 if row['type'] in (2,3):return {str(row['fromid']):cur['ss'],str(row['targetid']):cur['ts']}
 return {str(row['assetid']):cur['ts']}

def balances(s,effect,currencies=None):
 selected={i:select(s['assets'],i) for i in effect}
 if any((r.get('currency') or 'CNY')!=(currencies or {}).get(i,'CNY') for i,r in selected.items()):raise ValueError('currency_adapter_required')
 return {i:Decimal(str(selected[i]['money']))+n for i,n in effect.items()}

def tags(s):return [t for g in s.get('tags',[]) for t in g.get('tags',[])]

def ensure_empty(s,target,field):
 if any(str(b.get(field))==target for b in s['bills']):raise ValueError('object_has_references')
 if field in ('assetid','cateid','bookid'):
  for task in s.get('repeat',[])+s.get('installment',[]):
   data=task.get('data') or {};data=loads(data) if isinstance(data,str) else data
   refs=[task.get('assetid'),data.get('fromid'),data.get('targetid')] if field=='assetid' else [data.get(field)]
   if target in [str(v) for v in refs]:raise ValueError('object_has_task_references')

def editable_extra(extra):
 if extra and extra.get('curr'):
  cur=extra['curr']
  if not isinstance(cur,dict) or set(cur)!={'ss','sv','ts','tv','bs','bv'} or not isinstance(cur['ts'],str) or not re.fullmatch('[A-Z]{3}',cur['ts']) or cur['bs']!='CNY':return False
 return not extra or all(k in ('flag','transfee','tags','curr') or v in (None,0,False,'',{},[]) for k,v in extra.items())

def prepare(command,s,uid,bill_id=None,now=None):
 c={k:v for k,v in command.items() if v is not None};a=c.get('action')
 if a=='attachment_upload':
  from .attachments import prepare_upload
  return prepare_upload(c,uid)
 if a not in ALLOWED:
  from .linked import prepare_linked
  return prepare_linked(c,s,uid,bill_id,now)
 if set(c)-ALLOWED[a]-COMMON:raise ValueError('unexpected_fields')
 now=now or int(time.time());bill_id=bill_id or str(time.time_ns()//1_000_000)+str(100000+secrets.randbelow(100000))
 p={'action':a,'route':None,'params':{},'balances':{},'collection':None,'expected':{},'before_ids':[],'object_id':c.get('object_id'),'id_key':'id'}
 if a.startswith('bill_'):
  old=select(s['bills'],c['object_id'],uid=uid) if 'object_id' in c else None
  if a in ('bill_update','bill_delete'):version(c,old)
  scheduled=[(collection,t) for collection in ('repeat','installment') for t in s.get(collection,[]) if old and int(old.get('packid') or -1)>0 and t.get('packid')==old.get('packid')]
  if old and (old['type'] not in (0,1,2,3,4,5,6,7,9,10,11,20) or (scheduled and not (a=='bill_delete' and old['type']==20))):raise ValueError('specialized_bill_operation_required')
  if a=='bill_delete':
   row=normalize(old)
   if row['type']==20:
    extra=row['extra'] or {};source=str(extra.get('refundsid'))
    original=select(s['bills'],source,uid=uid);oe=original.get('extra') or {};oe=loads(oe) if isinstance(oe,str) else oe
    if scheduled:
     if len(scheduled)!=1 or original['type']!=0 or original.get('packid')!=row['packid'] or set(extra)-{'refundsid','tags','curr'} or not isinstance(oe.get('rfds'),dict) or Decimal(str(oe['rfds'].get(c['object_id'],'-1')))!=Decimal(str(row['money'])):raise ValueError('unknown_refund_shape')
     collection,task=scheduled[0]
     if str(task.get('userid'))!=uid:raise ValueError('owner_mismatch')
     p['scheduled_task']={'collection':collection,'row':deepcopy(task)}
    p['refund_source']=source;p['removed_refund']=c['object_id'];p['refund_amount']=row['money'];p['original_refunds']=deepcopy(oe.get('rfds',{}))
    effect={str(row['assetid']):-Decimal(str(row['money']))}
   else:
    detached_fee=row['type']==0 and int(row['packid'])>0 and isinstance(row['extra'],dict) and 'fee' in row['extra'] and Decimal(str(row['extra']['fee'])).is_finite() and Decimal(str(row['extra']['fee']))==Decimal(str(row['extra']['fee'])).quantize(Decimal('.01')) and Decimal(0)<=Decimal(str(row['extra']['fee']))<=Decimal(str(row['money'])) and not row['extra'].get('curr') and editable_extra({k:v for k,v in row['extra'].items() if k!='fee'})
    if detached_fee:
     source=select(s['assets'],str(row['assetid']),uid=uid)
     if str(source.get('userid'))!=uid or source.get('currency') not in (None,'CNY'):raise ValueError('owner_mismatch')
    if not editable_extra(row['extra']) and not detached_fee:raise ValueError('linked_bill_delete_requires_reconciliation')
    effect={i:-n for i,n in balance_effect(row).items()}
   p.update(route='bill/syncall',params=bill_request(delete=c['object_id']),collection='bills',delete=True,balances=balances(s,effect,bill_currencies(row)))
   return p
  if old:
   row=normalize(old)
   if row['type'] not in (0,1,2,3,5) or not editable_extra(row['extra']):raise ValueError('specialized_bill_operation_required')
   if a=='bill_copy':
    row.update(id=ident(bill_id),createtime=now,updatetime=now,status=2)
   else:row.update(updatetime=now,status=2)
   if 'amount' in c:row['money']=amount(c['amount'])
   if 'time' in c:row['time']=timestamp(c['time'])
   if 'remark' in c:row['remark']=text(c['remark'])
   if 'book_id' in c:
    select(s['books'],c['book_id'],'bookid',uid);row['bookid']=ident(c['book_id'],True);row['bookname']=None
   if 'account_id' in c:
    select(s['assets'],c['account_id'],uid=uid);row['fromid' if row['type'] in (2,3) else 'assetid']=ident(c['account_id'])
   if 'to_account_id' in c:
    if row['type'] not in (2,3):raise ValueError('invalid_transfer')
    select(s['assets'],c['to_account_id'],uid=uid);row['targetid']=ident(c['to_account_id'])
   if 'category_id' in c:
    if row['type'] in (2,3):raise ValueError('category_mismatch')
    cat=select(s['categories'],c['category_id'],uid=uid)
    if str(cat['bookid'])!=str(row['bookid']) or cat['type']!=(1 if row['type']==1 else 0):raise ValueError('category_mismatch')
    row['cateid']=ident(c['category_id']);row['category']=None
  else:
   kind=c.get('kind','expense');typ={'expense':0,'income':1,'transfer':2,'repayment':3,'reimburse_advance':5}.get(kind)
   if typ is None:raise ValueError('unsupported_bill_kind')
   book=select(s['books'],c['book_id'],'bookid',uid)
   asset=select(s['assets'],c['account_id'],uid=uid)
   if typ==5 and asset.get('currency') not in (None,'CNY'):raise ValueError('currency_adapter_required')
   row=make_row(uid,c['book_id'],bill_id,now,typ);row.update(money=amount(c['amount']),time=timestamp(c['time']),remark=c.get('remark'))
   if typ in (2,3):
    target=select(s['assets'],c['to_account_id'],uid=uid)
    if c['account_id']==c['to_account_id']:raise ValueError('invalid_transfer')
    if typ==3 and target.get('type')!=2:raise ValueError('repayment_requires_credit')
    row.update(fromid=ident(c['account_id']),targetid=ident(c['to_account_id']))
   else:
    cat=select(s['categories'],c['category_id'],uid=uid)
    if str(cat['bookid'])!=c['book_id'] or cat['type']!=(1 if typ==1 else 0):raise ValueError('category_mismatch')
    row.update(assetid=ident(c['account_id']),cateid=ident(c['category_id']))
  select(s['books'],str(row['bookid']),'bookid',uid)
  if row['type'] in (2,3):
   select(s['assets'],str(row['fromid']),uid=uid);target=select(s['assets'],str(row['targetid']),uid=uid)
   if row['fromid']==row['targetid']:raise ValueError('invalid_transfer')
   if row['type']==3 and target.get('type')!=2:raise ValueError('repayment_requires_credit')
  else:
   selected_asset=select(s['assets'],str(row['assetid']),uid=uid);cat=select(s['categories'],str(row['cateid']),uid=uid)
   if cat['bookid']!=row['bookid'] or cat['type']!=(1 if row['type']==1 else 0):raise ValueError('category_mismatch')
   if row['type']==5 and selected_asset.get('currency') not in (None,'CNY'):raise ValueError('currency_adapter_required')
  if a!='bill_update' and (str(row['id']) in {str(r['id']) for r in s['bills']} or str(row['id']) in {str(i) for i in s['deletes']}):raise ValueError('bill_id_collision')
  extra=deepcopy(row.get('extra') or {})
  asset_currency=(select(s['assets'],str(row['assetid']),uid=uid).get('currency') or 'CNY') if row['type'] in (0,1,5) else 'CNY'
  source_currency=c.get('currency','CNY')
  if row['type'] in (2,3) and (source_currency!='CNY' or any((select(s['assets'],str(row[k]),uid=uid).get('currency') or 'CNY')!='CNY' for k in ('fromid','targetid'))):
   src=select(s['assets'],str(row['fromid']),uid=uid).get('currency') or 'CNY';dst=select(s['assets'],str(row['targetid']),uid=uid).get('currency') or 'CNY'
   if c.get('currency',dst)!=dst:raise ValueError('currency_adapter_required')
   if any(k in c for k in ('fee','fee_base_amount')) and not all(k in c for k in ('amount','account_amount','base_amount')):raise ValueError('currency_edit_requires_conversion')
   if any(k in c for k in ('currency','amount','account_amount','base_amount')) or not extra.get('curr'):
    outgoing=amount(c.get('account_amount'));incoming=amount(c.get('amount'));base=amount(c.get('base_amount'))
    if (src==dst and outgoing!=incoming) or (src=='CNY' and outgoing!=base) or (dst=='CNY' and incoming!=base):raise ValueError('currency_adapter_required')
    fee=amount(c.get('fee',format(Decimal(str(extra.get('transfee') or 0)),'.2f')),zero=True)
    fee_base=amount(c.get('fee_base_amount','0.00' if fee==0 else None),zero=True)
    if (src=='CNY' and fee_base!=fee) or (fee==0 and fee_base!=0):raise ValueError('invalid_transfer_fee')
    from .fees import check_fee_conversion
    check_fee_conversion(outgoing,base,fee,fee_base)
    extra['curr']={'ss':src,'sv':outgoing+fee,'ts':dst,'tv':incoming,'bs':'CNY','bv':base+fee_base};row['money']=outgoing;extra['transfee']=fee
  elif source_currency!='CNY' or asset_currency!='CNY' and (a=='bill_create' or any(k in c for k in ('amount','currency','account_amount','base_amount'))):
   if row['type'] not in (0,1) or not isinstance(source_currency,str) or not re.fullmatch('[A-Z]{3}',source_currency):raise ValueError('currency_adapter_required')
   original=amount(c.get('amount'));converted=amount(c.get('account_amount'));base=amount(c.get('base_amount'))
   if (source_currency==asset_currency and original!=converted) or (source_currency=='CNY' and original!=base) or (asset_currency=='CNY' and converted!=base):raise ValueError('current_adapter_requires_cny_base_and_account')
   extra['curr']={'ss':source_currency,'sv':original,'ts':asset_currency,'tv':converted,'bs':'CNY','bv':base};row['money']=converted
  elif a=='bill_update' and extra.get('curr') and 'amount' in c:raise ValueError('currency_edit_requires_conversion')
  if any(k in c for k in ('account_amount','base_amount')) and not extra.get('curr'):
   if amount(c.get('account_amount'))!=row['money'] or amount(c.get('base_amount'))!=row['money']:raise ValueError('currency_adapter_required')
  if extra.get('curr') and extra.get('transfee') and row['type'] not in (2,3):raise ValueError('currency_adapter_required')
  if 'fee_base_amount' in c and (not extra.get('curr') or row['type'] not in (2,3)):raise ValueError('invalid_transfer_fee')
  for key,bit in [('include_statistics',1),('include_budget',2)]:
   if key in c:
    if type(c[key]) is not bool:raise ValueError('invalid_bill_flag')
    oldflag=extra.get('flag') or 0
    if type(oldflag) is not int:raise ValueError('invalid_bill_flag')
    extra['flag']=(oldflag&~bit) if c[key] else (oldflag|bit)
  if 'discount' in c:
   if row['type']!=0 or extra.get('curr') or 'fee' in c:raise ValueError('discount_requires_cny_expense')
   extra['transfee']=-amount(c['discount'],zero=True)
  if 'fee' in c:
   if row['type'] not in (2,3):raise ValueError('fee_requires_transfer')
   extra['transfee']=amount(c['fee'],zero=True)
  if 'tag_ids' in c:
   if not isinstance(c['tag_ids'],list) or len(c['tag_ids'])!=len(set(c['tag_ids'])):raise ValueError('invalid_tag_selection')
   extra['tags']=[]
   for tagid in c['tag_ids']:
    tag=select(tags(s),tagid,uid=uid)
    if tag.get('status')!=1:raise ValueError('tag_not_active')
    extra['tags'].append({k:v for k,v in tag.items() if k in ('id','userid','groupid','name','color','status','createtime','updatetime','sort')})
  row['extra']=extra or None
  if 'image_keys' in c:
   keys=c['image_keys'];known=set(s.get('uploaded_keys',[]))
   for existing in s['bills']:
    old_images=existing.get('images') or [];old_images=loads(old_images) if isinstance(old_images,str) else old_images
    if isinstance(old_images,list):known.update(i for i in old_images if isinstance(i,str))
   if not isinstance(keys,list) or len(keys)>9 or any(not isinstance(k,str) or k not in known for k in keys):raise ValueError('unverified_image_reference')
   row['images']=list(dict.fromkeys(keys)) or None
  account_currencies=bill_currencies({**row,'extra':extra})
  effect=balance_effect(row)
  if a=='bill_update':
   account_currencies={**bill_currencies(normalize(old)),**account_currencies}
   for i,n in balance_effect(normalize(old)).items():effect[i]=effect.get(i,Decimal(0))-n
  p.update(route='bill/syncall',params=bill_request(row),collection='bills',object_id=str(row['id']),row=row,
   expected={k:row[k] for k in ('id','userid','bookid','type','money','cateid','time','createtime','assetid','fromid','targetid','remark')},expected_extra=deepcopy(row['extra']),expected_images=deepcopy(row['images']),balances=balances(s,effect,account_currencies))
  return p
 if a.startswith('refund_'):
  from .refunds import prepare_refund
  return prepare_refund(c,s,uid,p)
 return prepare_object(c,s,uid,p)

def prepare_object(c,s,uid,p):
 a=c['action'];obj=c.get('object_id');name=c.get('name')
 if name is not None:text(name,10 if a.startswith('tag_group') else 40)
 if a.startswith('book_'):
  p.update(collection='books',id_key='bookid');old=select(s['books'],obj,'bookid',uid) if obj else None
  if old:version(c,old)
  if a=='book_rename' and obj=='-1':raise ValueError('default_book_rename_requires_adapter')
  if a in ('book_archive','book_restore'):
   current=1 if a=='book_archive' else 0;target=0 if a=='book_archive' else 1
   if obj=='-1' or old.get('visible')!=current:raise ValueError('book_visibility_state_conflict')
   p.update(route='book/visible',params={'bookid':obj},expected={'visible':target,'name':old['name']})
  elif a=='book_delete':
   if obj=='-1':raise ValueError('default_book_delete_forbidden')
   ensure_empty(s,obj,'bookid');p.update(route='book/delete',params={'bookid':obj},delete=True)
  else:
   if any(r['name']==name and str(r['bookid'])!=obj for r in s['books']):raise ValueError('name_ambiguous')
   v={'name':text(name,40),'cover':old.get('cover','--') if old else '--','type':old.get('type',-1) if old else -1,'range':old.get('range') if old else None}
   if old:v['bookid']=ident(obj,True)
   p.update(route='book/submit',params={'v':dumps(v)},expected={'name':name})
 elif a.startswith('account_'):
  p['collection']='assets';old=select(s['assets'],obj,uid=uid) if obj else None
  if old:version(c,old)
  if a in ('account_archive','account_restore'):
   current=0 if a=='account_archive' else 2;target=2 if a=='account_archive' else 0
   if old.get('status')!=current:raise ValueError('account_visibility_state_conflict')
   p.update(route='asset/visible',params={'did':obj},expected={'status':target,'money':old['money']},balances={obj:Decimal(str(old['money']))})
  elif a=='account_delete':
   if any(str((a.get('credit') or {}).get('shareid'))==obj for a in s.get('relationship_assets',s['assets'])):raise ValueError('shared_limit_has_members')
   for field in ('assetid','fromid','targetid'):ensure_empty(s,obj,field)
   p.update(route='asset/delete',params={'did':obj},delete=True)
  elif a in ('account_rename','account_update'):
   # Do not reconstruct financial/account settings from a sparse object.
   allowed={'id','userid','name','icon','color','money','incount','type','stype','loan','credit','createtime','status','extra','sort','lastpaytime','remark','currency','groupid'}
   if set(old)-allowed:raise ValueError('account_shape_requires_adapter')
   v=deepcopy(old);expected={'money':old['money'],'type':old['type'],'stype':old['stype']}
   if name is not None:v['name']=text(name,40);expected['name']=name
   if 'remark' in c:v['remark']=text(c['remark']);expected['remark']=v['remark']
   if 'include_in_total' in c:
    if type(c['include_in_total']) is not bool:raise ValueError('invalid_total_assets_flag')
    v['incount']=int(c['include_in_total']);expected['incount']=v['incount']
   if CREDIT_SETTINGS.intersection(c):
    if old.get('type')!=2 or not isinstance(old.get('credit'),dict):raise ValueError('repayment_requires_credit')
    v['credit']=apply_credit(c,old['credit']);expected['credit']=v['credit']
   p['related_credit_accounts']=apply_shared(c,s,uid,old,v,expected)
   if a=='account_update' and not set(c).intersection({'name','remark','include_in_total','limit','statement_day','payment_day','payment_after_statement_days','statement_inclusive','shared_limit_account_id','clear_credit_limit'}):raise ValueError('missing_required_fields')
   p.update(route='asset/submit',params={'v':dumps(v)},expected=expected,balances={obj:Decimal(str(old['money']))})
  else:
   if any(r['name']==name for r in s['assets']):raise ValueError('name_ambiguous')
   kind=c.get('account_kind','cash')
   template=None
   if kind not in ('cash','credit'):
    found=[t for t in s.get('account_templates',[]) if t.get('name')==kind and t.get('type') in (1,2,3,4)]
    if len(found)!=1:raise ValueError('unsupported_account_kind')
    template=found[0];kind='credit' if template['type']==2 else 'cash'
   money=amount(c.get('amount','0.00'),zero=True,signed=True)
   v={'id':-1,'userid':uid,'name':text(name,40),'icon':'http://res3.qianjiapp.com/assetv2/asset_icon_'+('cash.png' if kind=='cash' else 'creditother.png'),
    'color':'E45644' if kind=='cash' else '3168C2','money':money,'incount':0,'type':1 if kind=='cash' else 2,'stype':11 if kind=='cash' else 200,
    'loan':None,'credit':None,'createtime':0,'status':0,'extra':None,'sort':0,'lastpaytime':None,'remark':c.get('remark'),'currency':c.get('currency','CNY')}
   if not isinstance(v['currency'],str) or not re.fullmatch('[A-Z]{3}',v['currency']):raise ValueError('invalid_currency')
   if kind=='credit':
    v['credit']=apply_credit(c)
   elif CREDIT_SETTINGS.intersection(c):raise ValueError('repayment_requires_credit')
   if template:v.update(icon=template['icon'],color=template.get('c'),type=template['type'],stype=template['stype'])
   include=c.get('include_in_total',True)
   if type(include) is not bool:raise ValueError('invalid_total_assets_flag')
   v['incount']=1 if include else 0
   p.update(route='asset/submit',params={'v':dumps(v)},expected={**({'credit':v['credit']} if v['type']==2 else {}),'name':name,'money':money,'type':v['type'],'stype':v['stype'],'incount':v['incount'],'currency':v['currency']})
 elif a.startswith('category_'):
  p['collection']='categories';old=select(s['categories'],obj,uid=uid) if obj else None
  if old:version(c,old)
  if a in ('category_promote','category_demote'):
   if any(str(r.get('parentid'))==obj for r in s['categories']):raise ValueError('category_has_children')
   if old.get('level')!=(2 if a=='category_promote' else 1):raise ValueError('invalid_category_parent')
   params={'did':obj};expected={'name':old['name'],'bookid':old['bookid'],'type':old['type'],'level':1,'parentid':-1}
   if a=='category_demote':
    parent=select(s['categories'],c['parent_id'],uid=uid)
    if parent.get('level')!=1 or parent['bookid']!=old['bookid'] or parent['type']!=old['type'] or c['parent_id']==obj:raise ValueError('invalid_category_parent')
    params['parentid']=c['parent_id'];expected.update(level=2,parentid=ident(c['parent_id']))
   p.update(route='category/changelevel',params=params,expected=expected)
  elif a=='category_move':
   parent=select(s['categories'],c['parent_id'],uid=uid)
   if old.get('level')!=2 or parent.get('level')!=1 or parent['bookid']!=old['bookid'] or parent['type']!=old['type'] or c['parent_id']==obj:raise ValueError('invalid_category_parent')
   if any(str(r.get('parentid'))==obj for r in s['categories']):raise ValueError('category_has_children')
   p.update(route='category/movesubcate',params={'did':obj,'parentid':c['parent_id']},expected={'name':old['name'],'bookid':old['bookid'],'type':old['type'],'level':2,'parentid':ident(c['parent_id'])})
  elif a=='category_delete':
   ensure_empty(s,obj,'cateid');target=select(s['categories'],c['replacement_id'],uid=uid)
   if str(target['id'])==obj or target['bookid']!=old['bookid'] or target['type']!=old['type']:raise ValueError('invalid_replacement')
   if any(str(r.get('parentid'))==obj for r in s['categories']):raise ValueError('category_has_children')
   p.update(route='category/deletev2',params={'did':obj,'newcateid':c['replacement_id']},delete=True)
  else:
   book=str(old['bookid']) if old else c['book_id'];select(s['books'],book,'bookid',uid)
   typ=old['type'] if old else {'expense':0,'income':1}.get(c.get('kind','expense'))
   if typ is None:raise ValueError('invalid_category_kind')
   if any(r['name']==name and str(r['bookid'])==book and str(r['id'])!=obj for r in s['categories']):raise ValueError('name_ambiguous')
   icon=c.get('icon',old.get('icon') if old else 'http://res3.qianjiapp.com/cateic_yinshi.png')
   if not isinstance(icon,str) or not icon.startswith(('http://res3.qianjiapp.com/','https://res3.qianjiapp.com/')):raise ValueError('invalid_icon_reference')
   form={'bookid':book,'v':text(name,40),'t':str(typ),'icon':icon}
   if obj:form['did']=obj
   parent_id=c.get('parent_id',str(old.get('parentid',-1)) if old else None)
   if parent_id and parent_id!='-1':
    if parent_id==obj:raise ValueError('invalid_category_parent')
    if obj and any(str(r.get('parentid'))==obj for r in s['categories']):raise ValueError('category_has_children')
    parent=select(s['categories'],parent_id,uid=uid)
    if str(parent['bookid'])!=book or parent['type']!=typ or parent.get('level')!=1:raise ValueError('invalid_category_parent')
    form['parentid']=parent_id
   if old and str(old.get('parentid') or -1)!=str(parent_id or -1):raise ValueError('category_move_required')
   p.update(route='category/submitv2',params=form,expected={'name':name,'bookid':int(book),'type':typ,'level':2 if form.get('parentid') else 1,**({'parentid':int(form['parentid'])} if form.get('parentid') else {})})
 elif a.startswith('tag_group_'):
  p['collection']='tags';old=select(s['tags'],obj,uid=uid) if obj else None
  if old:version(c,old)
  if a=='tag_group_delete':
   if old.get('tags'):raise ValueError('tag_group_not_empty')
   p.update(route='tag/deletegroup',params={'did':obj},delete=True)
  else:
   if any(g['name']==name and str(g['id'])!=obj for g in s['tags']):raise ValueError('name_ambiguous')
   p.update(route='tag/submitgroup',params={'v':text(name,10),**({'did':obj} if obj else {})},expected={'name':name})
 elif a.startswith('tag_'):
  p['collection']='tag_items';old=select(tags(s),obj,uid=uid) if obj else None
  if old:version(c,old)
  if a=='tag_delete':p.update(route='tag/deletetag',params={'did':obj},delete=True)
  elif a=='tag_archive':p.update(route='tag/archivetag',params={'did':obj},status_before=old.get('status'))
  else:
   group=c.get('group_id',str(old['groupid']) if old else None);select(s['tags'],group,uid=uid)
   color=c.get('color',old.get('color','3168C2') if old else '3168C2')
   if not isinstance(color,str) or not re.fullmatch('[0-9A-Fa-f]{6}',color):raise ValueError('invalid_color')
   if any(t['name']==name and str(t['id'])!=obj for t in tags(s)):raise ValueError('name_ambiguous')
   v={'groupid':group,'name':text(name,40),'color':color};p.update(route='tag/submittag',params={'v':dumps(v),**({'did':obj} if obj else {})},expected=v)
 else:raise ValueError('unsupported_operation')
 p['before_ids']=[str(r[p['id_key']]) for r in (tags(s) if p['collection']=='tag_items' else s[p['collection']])]
 return p

def native_equal(got,want):
 if isinstance(want,Decimal):
  try:return got is not None and not isinstance(got,bool) and Decimal(str(got))==want
  except Exception:return False
 if isinstance(want,dict):return isinstance(got,dict) and set(got)==set(want) and all(native_equal(got[k],v) for k,v in want.items())
 if isinstance(want,list):return isinstance(got,list) and len(got)==len(want) and all(native_equal(a,b) for a,b in zip(got,want))
 return str(got)==str(want)

def verify(p,s):
 for bill_id,expected_digest in p.get('preserve_bill_digests',{}).items():
  if digest(select(s['bills'],bill_id,uid=p.get('owner')))!=expected_digest:raise ValueError('historical_schedule_bill_changed')
 for expected_asset in p.get('related_credit_accounts',[]):
  actual=select(s['assets'],str(expected_asset['id']),uid=p.get('owner'))
  if any(not native_equal(actual.get(k),v) for k,v in expected_asset.items()):raise ValueError('shared_credit_parent_changed')
 if p.get('scheduled_task'):
  st=p['scheduled_task'];want=st['row'];got=select(s[st['collection']],str(want['id']),uid=p.get('owner'))
  if not native_equal(got,want):raise ValueError('scheduled_task_changed')
 if p.get('installment_contract',{}).get('principal'):
  p={**p,'expected':{k:v for k,v in p['expected'].items() if k!='money'}}
 for i,want in p.get('balances',{}).items():
  if Decimal(str(select(s['assets'],i)['money']))!=Decimal(str(want)):raise ValueError('balance_not_verified')
 rows=tags(s) if p['collection']=='tag_items' else s[p['collection']];key=p.get('id_key','id');oid=p.get('object_id')
 if p.get('delete'):
  deleted=p.get('deleted_ids',[oid])
  if any(str(r[key]) in deleted for r in rows):raise ValueError('deletion_not_verified')
  if p['collection']=='bills' and not set(deleted)<={str(i) for i in s['deletes']}:raise ValueError('native_deletion_event_missing')
  if p.get('removed_refund'):
   src=normalize(select(s['bills'],p['refund_source']));extra=src['extra'] or {};rfds=extra.get('rfds') or {}
   expected={str(k):v for k,v in p['original_refunds'].items() if str(k)!=oid}
   if {str(k):v for k,v in rfds.items()}!=expected:raise ValueError('refund_markers_not_verified')
  return {'object_id':oid,'deleted':True,'balances_verified':True,**({'related_bill_ids':deleted} if p.get('deleted_ids') else {})}
 if p.get('refund_source'):
  src=normalize(select(s['bills'],p['refund_source'],uid=p.get('refund_owner')));extra=src['extra'] or {};rfds=extra.get('rfds') or {}
  candidates=[normalize(r) for r in rows if (str(r[key])==oid if oid else str(r[key]) not in p['before_ids'])]
  candidates=[r for r in candidates if r['type']==20 and (r['extra'] or {}).get('refundsid')==src['id'] and Decimal(str(r['money']))==p['refund_amount'] and str(r['assetid'])==p['refund_account'] and r['time']==p['refund_time']]
  if len(candidates)!=1:raise ValueError('refund_child_not_verified')
  row=candidates[0];oid=str(row['id'])
  if (row['extra'] or {}).get('curr')!=p.get('refund_currency'):raise ValueError('native_currency_not_verified')
  if row['bookid']!=src['bookid'] or (p.get('refund_owner') is not None and str(row['userid'])!=p['refund_owner']) or (p.get('refund_remark') is not None and row['remark']!=p['refund_remark']):raise ValueError('refund_child_not_verified')
  expected_refunds={str(k):Decimal(str(v)) for k,v in p.get('refunds_before',{}).items()};expected_refunds[oid]=p['refund_amount']
  if {str(k):Decimal(str(v)) for k,v in rfds.items()}!=expected_refunds:raise ValueError('refund_cumulative_relation_not_verified')
  for rid,n in expected_refunds.items():
   existing=normalize(select(s['bills'],rid,uid=p.get('refund_owner')))
   if existing['type']!=20 or (existing['extra'] or {}).get('refundsid')!=src['id'] or Decimal(str(existing['money']))!=n:raise ValueError('refund_cumulative_relation_not_verified')
  if Decimal(str(rfds.get(oid,'-1')))!=p['refund_amount']:raise ValueError('refund_source_relation_not_verified')
 else:
  candidates=[r for r in rows if str(r[key])==oid] if oid else [r for r in rows if str(r[key]) not in p['before_ids'] and all(native_equal(r.get(k),v) for k,v in p['expected'].items())]
  if len(candidates)!=1:raise ValueError('object_not_verified')
  row=candidates[0];oid=str(row[key])
  candidate=normalize(row) if p['collection']=='bills' else row
  for k,v in p.get('expected',{}).items():
   got=candidate.get(k)
   if isinstance(v,Decimal):
    if got is None or Decimal(str(got))!=v:raise ValueError('native_fields_not_verified')
   elif not native_equal(got,v):raise ValueError('native_fields_not_verified')
  if 'expected_images' in p and normalize(row)['images']!=p['expected_images']:raise ValueError('native_images_not_verified')
  if p.get('no_unexpected_bill_extra'):
   observed_extra=normalize(row)['extra'] or {}
   if any(k not in (p.get('expected_extra') or {}) and not (k=='flag' and v==0) for k,v in observed_extra.items()):raise ValueError('unexpected_copy_metadata')
  if p.get('expected_extra') is not None:
   actual_extra=normalize(row)['extra'] or {}
   for k,v in p['expected_extra'].items():
    if k=='tags':
     if {str(t['id']) for t in actual_extra.get('tags',[])}!={str(t['id']) for t in v}:raise ValueError('native_tags_not_verified')
    elif k=='curr':
     if actual_extra.get('curr')!=v:raise ValueError('native_currency_not_verified')
    elif k in ('flag','transfee','fee'):
     if Decimal(str(actual_extra.get(k,0)))!=Decimal(str(v or 0)):raise ValueError('native_flags_or_fee_not_verified')
  if 'status_before' in p and row.get('status')==p['status_before']:raise ValueError('native_transition_not_verified')
 if p.get('owner') is not None and 'userid' in row and str(row['userid'])!=p['owner']:raise ValueError('owner_mismatch')
 if p.get('debt_history'):
  dh=p['debt_history'];d=select(s['assets'],dh['id'],uid=p.get('owner'))
  if d.get('status')!=dh['status'] or d.get('stype')!=dh['stype'] or not native_equal(d.get('loan'),dh['loan']):raise ValueError('debt_history_not_verified')
 proof={'object_id':oid,'balances_verified':True,'native_fields_verified':True}
 if p.get('rows'):
  for expected in p['rows']:
   actual=normalize(select(s['bills'],str(expected['id']),uid=p.get('owner')))
   for k in ('id','type','money','assetid','fromid','targetid','bookid','time'):
    if actual[k]!=expected[k]:raise ValueError('related_native_bill_not_verified')
  proof['related_bill_ids']=[str(r['id']) for r in p['rows']]
 if p.get('debt_origin'):
  d=p['debt_origin'];new=[normalize(r) for r in s['bills'] if str(r['id']) not in d['before_ids']]
  found=[r for r in new if str(r['assetid'])==oid and r['type']==d['type'] and r['bookid']==d['bookid'] and Decimal(str(r['money']))==d['money'] and str(r['targetid'] if d['type']==6 else r['fromid'])==d['cash_id']]
  if len(found)!=1:raise ValueError('debt_origin_not_verified')
  proof['related_bill_ids']=[str(found[0]['id'])]
 if p.get('prepay'):
  d=row.get('data');d=loads(d) if isinstance(d,str) else d
  if not isinstance(d,dict) or not d.get('prepay'):raise ValueError('native_prepay_state_not_verified')
  info=p['prepay'];new=[normalize(b) for b in s['bills'] if str(b['id']) not in info['before_ids']]
  expenses=[b for b in new if b['type']==0 and b['packid']==info['packid'] and str(b['assetid'])==info['credit'] and b['bookid']==info['bookid']]
  payments=[b for b in new if b['type']==3 and str(b['fromid'])==info['cash'] and str(b['targetid'])==info['credit'] and b['bookid']==info['bookid']]
  if sum((Decimal(str(b['money'])) for b in expenses),Decimal(0))!=info['principal'] or len(payments)!=1 or Decimal(str(payments[0]['money']))!=info['principal']:raise ValueError('native_prepay_bills_not_verified')
  if len(expenses)!=1:raise ValueError('native_prepay_bills_not_verified')
  pay,spend=payments[0],expenses[0];pe=pay['extra'] or {};se=spend['extra'] or {}
  expected_fee=info.get('fee')
  if expected_fee is None:expected_fee=loads(p['params']['v']).get('fee',0)
  if Decimal(str(pe.get('transfee') or 0))!=Decimal(str(expected_fee)) or pe.get('presid')!=spend['id'] or se.get('pretid')!=pay['id'] or str(se.get('preinstallid'))!=oid:raise ValueError('native_prepay_bills_not_verified')
  if p.get('owner') is not None and any(str(b['userid'])!=p['owner'] for b in (pay,spend)):raise ValueError('owner_mismatch')
  proof['related_bill_ids']=[str(b['id']) for b in expenses+payments]
 if p.get('task_data'):
  from .linked import zero_fee_method_omitted
  d=row.get('data');d=loads(d) if isinstance(d,str) else d
  if not isinstance(d,dict):raise ValueError('task_data_not_verified')
  for k,v in p['task_data'].items():
   if isinstance(v,Decimal):
    if Decimal(str(d.get(k)))!=v:raise ValueError('task_data_not_verified')
   elif k=='time':
    try:
     if [int(x) for x in d[k].split(':')]!=[int(x) for x in v.split(':')]:raise ValueError()
    except Exception:raise ValueError('task_clock_not_verified') from None
   elif k in ('end','repeat') and isinstance(v,dict):
    actual=d.get(k)
    if k=='repeat' and v.get('type')=='bystep' and isinstance(actual,dict) and actual.get('type')=='bystep':
     av=actual.get('value');ev=v.get('value')
     if isinstance(av,list) and len(av)==1 and isinstance(ev,str) and ev.isdecimal():v={**v,'value':[int(ev)]}
    if k=='repeat' and v.get('type')=='workday' and isinstance(actual,dict) and actual.get('type')=='workday':
     actual={a:b for a,b in actual.items() if a!='value' or b not in (None,[])};v={a:b for a,b in v.items() if a!='value' or b not in (None,[])}
    if not isinstance(actual,dict) or {a:b for a,b in actual.items() if b is not None}!={a:b for a,b in v.items() if b is not None}:raise ValueError('task_data_not_verified')
   elif k=='feetype' and p.get('installment_contract') and zero_fee_method_omitted(row,d):pass
   elif k=='feeincount' and v==0 and d.get(k) is None:pass
   elif d.get(k)!=v:raise ValueError('task_data_not_verified')
  if 'task_baseline' in p:
   children=[normalize(r) for r in s['bills'] if str(r['id']) not in p['before_bill_ids'] and r.get('packid')==row.get('packid') and int(row.get('packid') or 0)>0]
   if p.get('installment_contract'):
    contract=p['installment_contract'];done=row.get('count')
    if type(done)is not int or not 0<=done<=contract['periods'] or len(children)!=done:raise ValueError('installment_child_relation_not_verified')
    if 'principal' in contract:
     # Native task summaries contain all remaining principal and fees.
     remaining=sum(contract['principal'][done:],Decimal(0));remaining_fee=sum(contract['fees'][done:],Decimal(0))
     if not native_equal(row.get('money'),remaining) or not native_equal(row.get('fee'),remaining_fee):raise ValueError('installment_remaining_not_verified')
    ordered=sorted(children,key=lambda b:(b['time'],b['id']))
    for index,child in enumerate(ordered):
     if 'fees' in contract and Decimal(str((child.get('extra') or {}).get('fee') or 0))!=contract['fees'][index]:raise ValueError('installment_child_relation_not_verified')
     expected_money=(contract['principal'][index]+contract['fees'][index]) if 'principal' in contract else contract['per']+(contract['total']-contract['per']*contract['periods'] if index==0 else Decimal(0))
     if child['type']!=0 or str(child['assetid'])!=contract['account'] or child['cateid']!=contract['category'] or child['bookid']!=contract['book'] or str(child['userid'])!=contract['owner'] or Decimal(str(child['money']))!=expected_money:raise ValueError('installment_child_relation_not_verified')
    actual_credit=select(s['assets'],contract['account'],uid=contract['owner'])
    if Decimal(str(actual_credit['money']))!=p['task_baseline'][contract['account']]-sum((Decimal(str(b['money'])) for b in children),Decimal(0)):raise ValueError('task_balance_not_verified')
   effect={i:Decimal(0) for i in p.get('task_balance_ids',[])}
   for child in children:
    if p['collection']=='repeat':
     expected_kind=row['type'];rel=d
     if child['type']!=expected_kind or child['bookid']!=rel['bookid'] or Decimal(str(child['money']))!=Decimal(str(rel['money'])) or (p.get('owner') is not None and str(child['userid'])!=p['owner']):raise ValueError('task_child_relation_not_verified')
     if expected_kind in (2,3):
      if child['fromid']!=rel['fromid'] or child['targetid']!=rel['targetid']:raise ValueError('task_child_relation_not_verified')
     elif child['assetid']!=rel['fromid'] or child['cateid']!=rel['cateid']:raise ValueError('task_child_relation_not_verified')
    for i,n in balance_effect(child).items():effect[i]=effect.get(i,Decimal(0))+n
   for i,n in effect.items():
    if Decimal(str(select(s['assets'],i)['money']))!=p['task_baseline'][i]+n:raise ValueError('task_balance_not_verified')
   proof.update(task_execution_observed=bool(children),related_bill_ids=[str(r['id']) for r in children])
 return proof
