"""Refund amounts in original currency and physical destination units."""
from copy import deepcopy
from decimal import Decimal
import re
from .codec import amount,ident,timestamp,dumps
from .operations import select,normalize,version,balances


def native_positive(value):
 n=Decimal(str(value))
 if not n.is_finite() or n<=0 or n!=n.quantize(Decimal('.01')):raise ValueError('unknown_refund_shape')
 return n

def currency_extra(cur):
 if not isinstance(cur,dict) or set(cur)!={'ss','sv','ts','tv','bs','bv'} or cur['bs']!='CNY' or any(not isinstance(cur[k],str) or not re.fullmatch('[A-Z]{3}',cur[k]) for k in ('ss','ts')):raise ValueError('unknown_refund_shape')
 for k in ('sv','tv','bv'):native_positive(cur[k])
 if (cur['ss']==cur['ts'] and cur['sv']!=cur['tv']) or (cur['ss']=='CNY' and cur['sv']!=cur['bv']) or (cur['ts']=='CNY' and cur['tv']!=cur['bv']):raise ValueError('unknown_refund_shape')
 return cur


def prepare_refund(c,s,uid,p):
 old=select(s['bills'],c['object_id'],uid=uid) if c['action']=='refund_update' else None
 if old:
  version(c,old);old=normalize(old)
  if old['type']!=20:raise ValueError('not_refund')
  source_id=str((old['extra'] or {}).get('refundsid'))
 else:source_id=c['object_id']
 source=normalize(select(s['bills'],source_id,uid=uid));asset=select(s['assets'],c['account_id'],uid=uid)
 if source['type']!=0:raise ValueError('refund_requires_cny_expense')
 source_cur=(source['extra'] or {}).get('curr');dst=asset.get('currency') or 'CNY'
 if source_cur:
  currency_extra(source_cur)
  if Decimal(str(source_cur['tv']))!=Decimal(str(source['money'])):raise ValueError('unknown_refund_shape')
 original=source_cur['ss'] if source_cur else 'CNY';total=native_positive(source_cur['sv'] if source_cur else source['money'])
 value=amount(c['amount']);cur=None
 if source_cur or dst!='CNY' or any(k in c for k in ('currency','account_amount','base_amount')):
  if c.get('currency')!=original or 'account_amount' not in c or 'base_amount' not in c:raise ValueError('refund_requires_cny_expense')
  physical=amount(c['account_amount']);base=amount(c['base_amount'])
  cur=currency_extra({'ss':original,'sv':value,'ts':dst,'tv':physical,'bs':'CNY','bv':base})
 else:physical=value
 rfds=(source['extra'] or {}).get('rfds') or {}
 if not isinstance(rfds,dict):raise ValueError('unknown_refund_shape')
 used=Decimal(0);previous_original=Decimal(0);previous_physical=Decimal(0);currencies={c['account_id']:dst}
 for rid,n in rfds.items():
  child=normalize(select(s['bills'],str(rid),uid=uid));ce=child['extra'] or {};cc=ce.get('curr')
  if child['type']!=20 or ce.get('refundsid')!=source['id'] or child['bookid']!=source['bookid'] or Decimal(str(child['money']))!=Decimal(str(n)):raise ValueError('unknown_refund_shape')
  if cc:
   currency_extra(cc)
   if cc['ss']!=original or Decimal(str(cc['tv']))!=Decimal(str(child['money'])):raise ValueError('unknown_refund_shape')
   native_original=Decimal(str(cc['sv']))
  else:
   if original!='CNY' or source_cur:raise ValueError('unknown_refund_shape')
   native_original=Decimal(str(child['money']))
  native_positive(child['money']);native_positive(native_original)
  used+=native_original
  if old and str(rid)==c['object_id']:
   previous_original=native_original;previous_physical=Decimal(str(child['money']));currencies[str(child['assetid'])]=cc['ts'] if cc else 'CNY'
 if old and c['object_id'] not in {str(k) for k in rfds}:raise ValueError('unknown_refund_shape')
 if value+used-previous_original>total:raise ValueError('refund_exceeds_remaining')
 v={'money':physical,'time':timestamp(c['time']),'remark':c.get('remark'),'assetid':ident(c['account_id']),'images':None,'currency':cur}
 effect={c['account_id']:physical}
 if old:
  v['billid']=ident(c['object_id']);oi=str(old['assetid']);effect[oi]=effect.get(oi,Decimal(0))-previous_physical
 p.update(route='bill/refund2',params={'did':source_id,'v':dumps(v)},collection='bills',object_id=c['object_id'] if old else None,
  before_ids=[str(r['id']) for r in s['bills']],refunds_before=deepcopy(rfds),refund_owner=uid,refund_remark=c.get('remark'),refund_source=source_id,refund_amount=physical,refund_original_amount=value,refund_currency=cur,refund_time=v['time'],refund_account=c['account_id'],balances=balances(s,effect,currencies))
 return p
