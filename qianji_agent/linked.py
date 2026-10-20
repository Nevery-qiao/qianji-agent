"""Native debt and recurring/installment task plans; no synthetic settlements."""
import datetime as dt,time,secrets,re
from copy import deepcopy
from decimal import Decimal,ROUND_DOWN
from .codec import ident,amount,timestamp,dumps,loads,digest
from .operations import select,version,text,make_row,balances,COMMON

SUPPORTED={
 'scheduled_bill_update':{'object_id','related_id','related_version','book_id','account_id','to_account_id','currency','amount','time','remark','category_id','include_statistics','include_budget','fee','discount','tag_ids','image_keys','account_amount','base_amount','fee_base_amount'},
 'scheduled_bill_copy':{'object_id','related_id','related_version','time','remark'},
 'scheduled_bill_delete':{'object_id','related_id','related_version'},
 'debt_bill_update':{'object_id','related_id','related_version','amount','time','remark'},
 'prepay_records_delete':{'object_id','related_id','related_version'},
 'debt_create':{'name','kind','book_id','account_id','amount','start_date','end_date','remark'},
 'debt_add':{'object_id','book_id','account_id','amount','time','remark'},
 'debt_finish':{'object_id','end_date'},
 'debt_pay':{'object_id','book_id','account_id','amount','interest','time','remark'},
 'repeat_create':{'kind','book_id','account_id','to_account_id','category_id','amount','start_date','end_date','end_count','repeat_unit','repeat_value','repeat_values','clock','remark'},
 'repeat_update':{'object_id','amount','start_date','end_date','end_count','clock','remark','book_id','account_id','to_account_id','category_id','repeat_unit','repeat_value','repeat_values'},
 'repeat_toggle':{'object_id'},'repeat_delete':{'object_id'},
 'installment_create':{'name','account_id','category_id','amount','periods','time','fee','remark','fee_method','remainder'},
 'installment_config':{'object_id','include_statistics','fee_include_statistics'},
 'installment_prepay':{'object_id','book_id','account_id','amount','time','fee','remark'},
 'installment_delete':{'object_id'},
}
for _suffix in ('update','copy','delete'):
 SUPPORTED['installment_bill_'+_suffix]=SUPPORTED['scheduled_bill_'+_suffix]-{'currency','account_amount','base_amount','fee_base_amount','fee','discount','to_account_id'}


def _plan(a):return {'action':a,'route':None,'params':{},'balances':{},'collection':None,'expected':{},'before_ids':[],'object_id':None,'id_key':'id'}
def _id():return str(time.time_ns()//1_000_000)+str(100000+secrets.randbelow(100000))
def _date(v):dt.date.fromisoformat(v);return v

def prepare_linked(c,s,uid,bill_id=None,now=None):
 a=c.get('action')
 if a not in SUPPORTED:raise ValueError('unsupported_operation')
 if set(c)-SUPPORTED[a]-COMMON:raise ValueError('unexpected_fields')
 p=_plan(a);now=now or int(time.time());bill_id=bill_id or _id()
 if a=='prepay_records_delete':
  from .operations import normalize,balance_effect
  pay=normalize(select(s['bills'],c['object_id'],uid=uid));spend=normalize(select(s['bills'],c['related_id'],uid=uid));version(c,select(s['bills'],c['object_id']))
  if c.get('related_version')!=digest(select(s['bills'],c['related_id'])):raise ValueError('version_conflict')
  if pay['type']!=3 or spend['type']!=0 or pay['bookid']!=spend['bookid'] or pay['packid']!=spend['packid'] or pay['money']!=spend['money'] or pay['targetid']!=spend['assetid'] or not isinstance(pay['extra'],dict) or set(pay['extra'])-{'presid','transfee'} or pay['extra'].get('presid')!=spend['id'] or set(spend['extra'] or {})!={'pretid','preinstallid'} or spend['extra']['pretid']!=pay['id']:raise ValueError('unsupported_prepay_relation')
  if any(str(t['id'])==str(spend['extra']['preinstallid']) or t.get('packid')==pay['packid'] for t in s.get('installment',[])):raise ValueError('remove_installment_before_record_cleanup')
  effect={}
  for row in (pay,spend):
   clean={**row,'extra':{'transfee':(row.get('extra') or {}).get('transfee',0)} if row['type']==3 else None}
   for i,n in balance_effect(clean).items():effect[i]=effect.get(i,Decimal(0))-n
  p.update(route='bill/syncall',params={'v':dumps({'bills':{'dellist':[pay['id'],spend['id']]}})},collection='bills',object_id=c['object_id'],delete=True,deleted_ids=[c['object_id'],c['related_id']],balances=balances(s,effect));return p
 if a.startswith('installment_bill_'):
  from .installment_bills import prepare_installment_bill
  return prepare_installment_bill(c,s,uid,bill_id,now)
 if a.startswith('scheduled_bill_'):
  from .scheduled_bills import prepare_scheduled
  return prepare_scheduled(c,s,uid,bill_id,now)
 if a=='debt_bill_update':
  from .debt_history import prepare_history
  return prepare_history(c,s,uid,p)
 if a=='debt_finish':
  d=select(s['assets'],c['object_id'],uid=uid);version(c,d)
  if d.get('type')!=5 or Decimal(str(d['money']))!=0:raise ValueError('debt_finish_requires_zero_principal')
  end=_date(c['end_date']);loan=deepcopy(d.get('loan'))
  if not isinstance(loan,dict):raise ValueError('invalid_debt_account')
  loan['enddate']=end
  p.update(route='asset/finish',params={'did':c['object_id'],'v':end},collection='assets',object_id=c['object_id'],expected={'status':1,'money':Decimal('0.00'),'loan':loan},balances={c['object_id']:Decimal('0.00')});return p
 if a.startswith('debt_'):return debt(c,s,uid,p,bill_id,now)
 return task(c,s,uid,p,now)

def debt(c,s,uid,p,bill_id,now):
 a=c['action'];cash=select(s['assets'],c['account_id'],uid=uid);select(s['books'],c['book_id'],'bookid',uid)
 if cash.get('currency') not in (None,'CNY') or cash.get('type')!=1:raise ValueError('debt_requires_cny_cash')
 value=amount(c['amount'],zero=a=='debt_pay')
 if a=='debt_create':
  kind=c.get('kind')
  if kind not in ('borrow','lend'):raise ValueError('invalid_debt_kind')
  name=text(c['name'],40)
  if any(r['name']==name for r in s['assets']):raise ValueError('name_ambiguous')
  start=_date(c['start_date']);end=_date(c['end_date']) if c.get('end_date') else None
  if end and end<start:raise ValueError('invalid_debt_dates')
  signed=-value if kind=='borrow' else value
  v={'id':-1,'userid':uid,'name':name,'icon':None,'color':None,'money':signed,'incount':0,'type':5,'stype':51 if kind=='borrow' else 52,
   'loan':{'accountId':None,'startdate':start,'enddate':end,'remark':c.get('remark'),'money':signed,'totalpay':None},'credit':None,'createtime':0,'status':0,'extra':None,'sort':0,'lastpaytime':None,'remark':c.get('remark'),'currency':'CNY'}
  extra={'bookid':ident(c['book_id'],True),'accountId':ident(c['account_id']),'remark':c.get('remark'),'images':[]}
  p.update(route='asset/submit',params={'v':dumps(v),'extra':dumps(extra)},collection='assets',before_ids=[str(r['id']) for r in s['assets']],
   expected={'name':name,'type':5,'stype':v['stype'],'money':signed,'incount':0},balances=balances(s,{c['account_id']:value if kind=='borrow' else -value}),
   debt_origin={'type':6 if kind=='borrow' else 7,'bookid':ident(c['book_id'],True),'money':value,'cash_id':c['account_id'],'before_ids':[str(r['id']) for r in s['bills']]})
  return p
 d=select(s['assets'],c['object_id'],uid=uid);version(c,d)
 if d.get('type')!=5 or d.get('stype') not in (51,52) or d.get('currency') not in (None,'CNY'):raise ValueError('invalid_debt_account')
 borrow=d['stype']==51;remaining=abs(Decimal(str(d['money'])))
 principal_type=(6 if borrow else 7) if a=='debt_add' else (9 if borrow else 4)
 interest=amount(c.get('interest','0.00'),zero=True)
 if a=='debt_pay' and value>remaining:raise ValueError('principal_exceeds_remaining')
 if value==0 and interest==0:raise ValueError('empty_debt_payment')
 row=make_row(uid,c['book_id'],bill_id,now,principal_type);row.update(money=value,time=timestamp(c['time']),remark=c.get('remark'),assetid=ident(c['object_id']))
 row['targetid' if principal_type in (4,6) else 'fromid']=ident(c['account_id']);items=[row] if value else []
 if interest:
  ir=make_row(uid,c['book_id'],_id(),now,10 if borrow else 11);ir.update(money=interest,time=row['time'],remark=c.get('remark'),assetid=ident(c['account_id']),fromid=ident(c['object_id']));items.append(ir)
 cash_delta=(value if borrow else -value) if a=='debt_add' else (-value-interest if borrow else value+interest)
 debt_delta=(-value if borrow else value) if a=='debt_add' else (value if borrow else -value)
 loan=deepcopy(d.get('loan'))
 if not isinstance(loan,dict):raise ValueError('invalid_debt_account')
 if value:
  if a=='debt_add':loan['money']=Decimal(str(loan['money']))+debt_delta
  else:loan['totalpay']=Decimal(str(loan.get('totalpay') or 0))+value
 p.update(route='bill/syncall',params={'v':dumps({'bills':{'changelist':dumps(items)}})},collection='bills',object_id=str(items[0]['id']),rows=items,
  balances=balances(s,{c['account_id']:cash_delta,c['object_id']:debt_delta}),expected={k:items[0][k] for k in ('id','type','money','bookid','assetid','fromid','targetid','time')},
  debt_history={'id':c['object_id'],'loan':loan,'status':d.get('status'),'stype':d['stype']})
 return p

def task(c,s,uid,p,now):
 a=c['action'];is_repeat=a.startswith('repeat_');collection='repeat' if is_repeat else 'installment';p['collection']=collection
 old=select(s[collection],c['object_id'],uid=uid) if c.get('object_id') else None
 if old:
  version(c,old);p['object_id']=c['object_id']
  if a.endswith('_delete'):
   p.update(route='repeat_task/delete' if is_repeat else 'installment/delete',params={'did':c['object_id']},delete=True);return p
  if a=='repeat_toggle':p.update(route='repeat_task/toggle',params={'did':c['object_id']},status_before=old.get('status'));return p
  if a=='installment_config':
   d=loads(old['data']) if isinstance(old.get('data'),str) else old.get('data') or {}
   config={'incount':old.get('incount',0),'feeincount':d.get('feeincount',0) or 0}
   for field,target in [('include_statistics','incount'),('fee_include_statistics','feeincount')]:
    if field in c:
     if type(c[field]) is not bool:raise ValueError('invalid_bill_flag')
     config[target]=1 if c[field] else 0
   p.update(route='installment/config',params={'did':c['object_id'],'v':dumps(config)},expected={'incount':config['incount']},task_data={'feeincount':config['feeincount']});return p
  if a=='installment_prepay':
   cash=select(s['assets'],c['account_id'],uid=uid);credit=select(s['assets'],str(old['assetid']),uid=uid);select(s['books'],c['book_id'],'bookid',uid)
   if cash.get('type')!=1 or credit.get('type')!=2 or cash.get('currency') not in (None,'CNY') or credit.get('currency') not in (None,'CNY'):raise ValueError('prepay_requires_cny_accounts')
   if 'fee' not in c:raise ValueError('missing_required_fields')
   remaining=installment_remaining(old,s,uid)
   value=amount(c['amount']);fee=amount(c.get('fee','0.00'),zero=True)
   if value!=remaining or remaining<=0:raise ValueError('prepay_remaining_mismatch')
   v={'dataid':ident(c['object_id']),'bookid':ident(c['book_id'],True),'time':timestamp(c['time']),'fee':fee,'money':value,'fromid':ident(c['account_id']),'remark':c.get('remark'),'images':None,'spendCurrency':None,'transferCurrency':None}
   p.update(route='installment/prepay',params={'v':dumps(v)},expected={},balances=balances(s,{c['account_id']:-value-fee,str(old['assetid']):Decimal(0)}),prepay={'fee':fee,'principal':remaining,'cash':c['account_id'],'credit':str(old['assetid']),'bookid':ident(c['book_id'],True),'packid':old['packid'],'before_ids':[str(b['id']) for b in s['bills']]});return p
  if a=='repeat_update':
   allowed={'id','userid','createtime','updatetime','type','count','status','packid','data'}
   if set(old)-allowed-{'bookuid'}:raise ValueError('unsupported_task_shape')
   if not set(c).intersection(SUPPORTED[a]-{'object_id'}):raise ValueError('missing_required_fields')
   if ('to_account_id' in c and old['type'] not in (2,3)) or ('category_id' in c and old['type'] in (2,3)):raise ValueError('unexpected_fields')
   v={k:deepcopy(v) for k,v in old.items() if k in allowed};d=v['data'];d=loads(d) if isinstance(d,str) else d
   validate_repeat_update(old,d,s,uid)
   for key,target in [('amount','money'),('remark','remark'),('clock','time'),('start_date','start')]:
    if key in c:d[target]=amount(c[key]) if key=='amount' else c[key]
   if 'end_date' in c or 'end_count' in c:d['end']={'date':c.get('end_date'),'count':c.get('end_count')}
   for key,target in [('book_id','bookid'),('account_id','fromid'),('to_account_id','targetid'),('category_id','cateid')]:
    if key in c:d[target]=ident(c[key],key=='book_id')
   if 'category_id' in c:d['category']=dumps(select(s['categories'],c['category_id'],uid=uid))
   if ('repeat_value' in c or 'repeat_values' in c) and 'repeat_unit' not in c:raise ValueError('invalid_schedule_values')
   if 'repeat_unit' in c:
    if 'repeat_value' in c and 'repeat_values' in c:raise ValueError('invalid_schedule_values')
    d['repeat']={'type':c['repeat_unit'],'value':[c['repeat_value']] if c['repeat_unit']=='bystep' and type(c.get('repeat_value'))is int else c.get('repeat_values',c.get('repeat_value'))}
   validate_repeat_update(old,d,s,uid)
   if isinstance(d.get('time'),str) and re.fullmatch('[0-9]{1,2}:[0-9]{1,2}',d['time']):d['time']=':'.join(f'{int(x):02d}' for x in d['time'].split(':'))
   if d['repeat'].get('type')=='workday' and d['repeat'].get('value')==[]:d['repeat']['value']=None
   _schedule_check(d);v.update(data=d,updatetime=now)
   original_data=old['data'];original_data=loads(original_data) if isinstance(original_data,str) else original_data
   p.update(task_baseline={str(r['id']):Decimal(str(r['money'])) for r in s['assets']},before_bill_ids=[str(r['id']) for r in s['bills']],task_balance_ids=sorted({str(data[key]) for data in (original_data,d) for key in ('fromid','targetid') if data.get(key) is not None}))
   p.update(route='repeat_task/submit',params={'v':dumps(v)},expected={'type':old['type'],'packid':old.get('packid')},task_data={k:d.get(k) for k in ('bookid','fromid','targetid','cateid','money','remark','start','time','end','repeat')},preserve_bill_digests={str(b['id']):digest(b) for b in s['bills'] if b.get('packid')==old.get('packid') and int(old.get('packid') or 0)>0});return p
 if a=='repeat_create':
  book=select(s['books'],c['book_id'],'bookid',uid);asset=select(s['assets'],c['account_id'],uid=uid);kind=c.get('kind','expense')
  typ={'expense':0,'income':1,'transfer':2,'repayment':3,'reimburse_advance':5}.get(kind)
  if typ is None:raise ValueError('repeat_kind_not_yet_verified')
  if asset.get('currency') not in (None,'CNY'):raise ValueError('currency_adapter_required')
  cat=None;target=None
  if typ in (2,3):
   target=select(s['assets'],c['to_account_id'],uid=uid)
   if c['account_id']==c['to_account_id'] or target.get('currency') not in (None,'CNY'):raise ValueError('invalid_transfer')
   if typ==3 and target.get('type')!=2:raise ValueError('repayment_requires_credit')
  else:
   cat=select(s['categories'],c['category_id'],uid=uid)
   if str(cat['bookid'])!=c['book_id'] or cat['type']!=(1 if kind=='income' else 0):raise ValueError('category_mismatch')
  d={'start':_date(c['start_date']),'end':{'date':c.get('end_date'),'count':c.get('end_count')},'repeat':{'type':c.get('repeat_unit','day'),'value':[c['repeat_value']] if c.get('repeat_unit')=='bystep' and type(c.get('repeat_value')) is int else c.get('repeat_values',c.get('repeat_value'))},
   'cateid':ident(c['category_id']) if cat else None,'fromid':ident(c['account_id']),'targetid':ident(c['to_account_id']) if target else None,'remark':c.get('remark'),'images':None,'bookid':ident(c['book_id'],True),'money':amount(c['amount']),'fee':None,'time':c['clock'],'category':dumps(cat) if cat else None,'billflag':None,'currency':None}
  _schedule_check(d)
  v={'id':None,'userid':uid,'createtime':now,'updatetime':0,'type':typ,'count':None,'status':None,'packid':None,'data':d}
  p.update(route='repeat_task/submit',params={'v':dumps(v)},expected={'type':v['type']},task_data={k:d[k] for k in ('bookid','fromid','targetid','cateid','money','start','time','end','repeat')})
 elif a=='installment_create':
  asset=select(s['assets'],c['account_id'],uid=uid);cat=select(s['categories'],c['category_id'],uid=uid)
  if asset.get('type')!=2 or asset.get('currency') not in (None,'CNY') or cat['type']!=0:raise ValueError('installment_requires_cny_credit')
  count=c['periods']
  if type(count) is not int or not 2<=count<=120:raise ValueError('invalid_periods')
  total=amount(c['amount']);fee=amount(c.get('fee','0.00'),zero=True)
  fee_method=c.get('fee_method','average');remainder=c.get('remainder','first')
  if fee_method not in ('average','first','last') or remainder not in ('first','last'):raise ValueError('unsupported_operation')
  per=(total/Decimal(count)).quantize(Decimal('0.01'),rounding=ROUND_DOWN)
  if per<=0:raise ValueError('installment_amount_too_small')
  perfee=(fee/Decimal(count)).quantize(Decimal('0.01'),rounding=ROUND_DOWN)
  principal=[per]*count;principal[0 if remainder=='first' else -1]+=total-per*count
  fees=[perfee]*count if fee_method=='average' else [Decimal(0)]*count
  if fee_method=='average':fees[0 if remainder=='first' else -1]+=fee-perfee*count
  else:fees[0 if fee_method=='first' else -1]=fee
  value={'id':None,'name':text(c['name'],40),'userid':uid,'assetid':ident(c['account_id']),'type':0,'starttime':timestamp(c['time']),'updatetime':0,'createtime':now,'totalcount':count,'count':0,
   'totalmoney':total,'totalfee':fee,'money':per,'fee':(fee/Decimal(count)).quantize(Decimal('0.01'),rounding=ROUND_DOWN),'status':1,'packid':None,'incount':0,
   'data':{'cateid':cat['id'],'remark':c.get('remark'),'images':None,'feetype':'ave' if fee_method=='average' else fee_method,'lefttype':remainder,'category':dumps(cat),'asset':dumps(asset),'billflag':None,'feeincount':None,'prepay':None,'tags':None}}
  p.update(route='installment/submit',params={'v':dumps(value)},expected={'name':value['name'],'type':1,'assetid':value['assetid'],'starttime':value['starttime'],'money':per,'totalcount':count,'totalmoney':total,'totalfee':fee},task_data={'cateid':cat['id'],'lefttype':remainder,'feetype':'ave' if fee_method=='average' else fee_method},installment_contract={'owner':uid,'book':cat['bookid'],'account':c['account_id'],'category':cat['id'],'total':total,'periods':count,'per':per,'principal':principal,'fees':fees})
 else:raise ValueError('unsupported_operation')
 p['before_ids']=[str(r['id']) for r in s[collection]];p['task_baseline']={str(r['id']):Decimal(str(r['money'])) for r in s['assets']};p['before_bill_ids']=[str(r['id']) for r in s['bills']]
 return p

def _schedule_check(d):
 _date(d['start'])
 if d['end'].get('date'):
  _date(d['end']['date'])
  if d['end']['date']<d['start']:raise ValueError('invalid_task_end')
 if d['end'].get('count') is not None and (type(d['end']['count']) is not int or d['end']['count']<=0):raise ValueError('invalid_task_end')
 if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',d['time']):raise ValueError('invalid_task_time')
 unit=d.get('repeat',{}).get('type');value=d.get('repeat',{}).get('value')
 if unit in ('day','workday'):
  if value is not None:raise ValueError('invalid_schedule_values')
 elif unit in ('week','month'):
  maximum=7 if unit=='week' else 31
  if not isinstance(value,list) or not value or any(type(n) is not int or not 1<=n<=maximum for n in value) or len(set(value))!=len(value):raise ValueError('invalid_schedule_values')
 elif unit=='year':
  if not isinstance(value,list) or not value or not all(isinstance(n,str) for n in value):raise ValueError('invalid_schedule_values')
  for n in value:dt.date.fromisoformat('2000-'+n)
 elif unit=='bystep':
  if not isinstance(value,list) or len(value)!=1 or type(value[0]) is not int or not 1<=value[0]<=3650:raise ValueError('invalid_schedule_values')
 else:raise ValueError('repeat_schedule_adapter_required')


def validate_repeat_update(old,d,s,uid):
 allowed={'start','end','repeat','cateid','fromid','targetid','remark','images','bookid','money','fee','time','category','billflag','currency','tags'}
 if not isinstance(d,dict) or set(d)-allowed or not isinstance(d.get('end'),dict) or set(d['end'])-{'date','count'} or not isinstance(d.get('repeat'),dict) or set(d['repeat'])-{'type','value'}:raise ValueError('unsupported_task_shape')
 if old.get('type') not in (0,1,2,3,5) or d.get('currency') not in (None,'CNY') or d.get('fee') not in (None,0):raise ValueError('repeat_contract_requires_adapter')
 select(s['books'],str(d['bookid']),'bookid',uid)
 source=select(s['assets'],str(d['fromid']),uid=uid)
 if source.get('currency') not in (None,'CNY'):raise ValueError('currency_adapter_required')
 if old['type'] in (2,3):
  target=select(s['assets'],str(d['targetid']),uid=uid)
  if target['id']==source['id'] or target.get('currency') not in (None,'CNY') or (old['type']==3 and target.get('type')!=2):raise ValueError('repeat_contract_requires_adapter')
 else:
  cat=select(s['categories'],str(d['cateid']),uid=uid)
  if str(cat['bookid'])!=str(d['bookid']) or cat['type']!=(1 if old['type']==1 else 0):raise ValueError('category_mismatch')


def zero_fee_method_omitted(task,data):
 """Native omits allocation metadata when both explicit fee totals are zero."""
 if data.get('feetype') is not None or task.get('totalfee') is None or task.get('fee') is None:return False
 try:return _native_amount(task['totalfee'],zero=True)==0 and _native_amount(task['fee'],zero=True)==0
 except Exception:return False


def installment_remaining(task,s,uid):
 """Remaining scheduled principal; native history edits do not change count."""
 pack=task.get('packid');done=task.get('count');periods=task.get('totalcount');data=task.get('data') or {}
 data=loads(data) if isinstance(data,str) else data
 if type(pack)is not int or pack<=0 or type(done)is not int or type(periods)is not int or not 2<=periods<=120 or not 0<=done<periods or not isinstance(data,dict) or data.get('prepay') or type(task.get('status'))is not int or task['status']!=1 or type(task.get('type'))is not int or task['type']!=1 or str(task.get('userid'))!=uid or not {'money','fee'}<=set(task) or not {'lefttype'}<=set(data):raise ValueError('unsupported_task_shape')
 source=select(s['assets'],str(task.get('assetid')),uid=uid)
 if str(source.get('userid'))!=uid or source.get('type')!=2 or source.get('currency') not in (None,'CNY'):raise ValueError('owner_mismatch')
 select(s['categories'],str(data.get('cateid')),uid=uid)
 total=_native_amount(task['totalmoney']);total_fee=_native_amount(task.get('totalfee') or 0,zero=True)
 left=data['lefttype'];fee_type='ave' if zero_fee_method_omitted(task,data) else data.get('feetype')
 if left not in ('first','last') or fee_type not in ('ave','first','last'):raise ValueError('unsupported_task_shape')
 per=(total/Decimal(periods)).quantize(Decimal('.01'),rounding=ROUND_DOWN)
 if per<=0:raise ValueError('unsupported_task_shape')
 principal=[per]*periods;principal[0 if left=='first' else -1]+=total-per*periods
 per_fee=(total_fee/Decimal(periods)).quantize(Decimal('.01'),rounding=ROUND_DOWN)
 fees=[per_fee]*periods if fee_type=='ave' else [Decimal(0)]*periods
 if fee_type=='ave':fees[0 if left=='first' else -1]+=total_fee-per_fee*periods
 else:fees[0 if fee_type=='first' else -1]=total_fee
 if _native_amount(task['money'])!=sum(principal[done:],Decimal(0)) or _native_amount(task['fee'],zero=True)!=sum(fees[done:],Decimal(0)):raise ValueError('unsupported_task_shape')
 return sum(principal[done:],Decimal(0))


def _native_amount(value,zero=False):
 n=Decimal(str(value))
 if not n.is_finite() or n.quantize(Decimal('0.01'))!=n:raise ValueError('invalid_amount')
 return amount(format(n,'.2f'),zero=zero)
