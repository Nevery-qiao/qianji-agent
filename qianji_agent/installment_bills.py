"""Finite generated installment bill maintenance; the schedule stays unchanged."""
from copy import deepcopy
from decimal import Decimal
from .codec import digest
from .operations import select,version,normalize,prepare,bill_request,editable_extra

def prepare_installment_bill(c,s,uid,bill_id=None,now=None):
 from .linked import installment_remaining
 raw=select(s['bills'],c['object_id'],uid=uid);version(c,raw);row=normalize(raw)
 task=select(s['installment'],c['related_id'],uid=uid)
 if str(raw.get('userid'))!=uid or str(task.get('userid'))!=uid:raise ValueError('owner_mismatch')
 for aid in {str(row['assetid'])}|({c['account_id']} if c.get('account_id') else set()):
  asset=select(s['assets'],aid,uid=uid)
  if str(asset.get('userid'))!=uid:raise ValueError('owner_mismatch')
 if c.get('related_version')!=digest(task):raise ValueError('version_conflict')
 pack=row['packid'];data=task.get('data') or {}
 from .codec import loads
 data=loads(data) if isinstance(data,str) else data
 if type(pack)is not int or pack<=0 or task.get('packid')!=pack or task.get('type')!=1 or row['type']!=0 or not isinstance(data,dict) or data.get('prepay'):raise ValueError('unsupported_task_bill_relation')
 if sum(t.get('packid')==pack for t in s['repeat']+s['installment'])!=1:raise ValueError('unsupported_task_bill_relation')
 installment_remaining(task,s,uid)
 original_extra=deepcopy(row['extra'] or {});fee=Decimal(str(original_extra.pop('fee',0) or 0))
 if not fee.is_finite() or fee<0 or fee!=fee.quantize(Decimal('.01')) or fee>Decimal(str(row['money'])) or not editable_extra(original_extra) or original_extra.get('curr'):raise ValueError('unsupported_task_bill_relation')
 # Delegate only after the real object/version/relation was checked. Fee is
 # metadata inside money, not an additional account debit.
 shadow_raw=deepcopy(raw);shadow_raw['extra']=original_extra or None
 shadow={**s,'installment':[t for t in s['installment'] if str(t['id'])!=c['related_id']],'bills':[shadow_raw if str(b['id'])==c['object_id'] else b for b in s['bills']]}
 base=c['action'].removeprefix('installment_');delegated={k:v for k,v in c.items() if k not in ('related_id','related_version')};delegated.update(action=base,expected_version=digest(shadow_raw))
 p=prepare(delegated,shadow,uid,bill_id=bill_id,now=now)
 if base=='bill_update':
  if Decimal(str(p['row']['money']))<fee:raise ValueError('installment_bill_below_fee')
  if 'fee' in (row['extra'] or {}):p['row']['extra']={**(p['row']['extra'] or {}),'fee':fee}
  p['expected_extra']=deepcopy(p['row']['extra']);p['expected']['packid']=pack;p['params']=bill_request(p['row'])
 elif base=='bill_copy':
  # Native detached copies retain the total but drop installment fee metadata.
  p['row']['packid']=-1;p['expected']['packid']=-1;p['params']=bill_request(p['row']);p['preserve_bill_digests']={c['object_id']:digest(raw)};p['no_unexpected_bill_extra']=True
 p['action']=c['action'];p['scheduled_task']={'collection':'installment','row':deepcopy(task)}
 return p
