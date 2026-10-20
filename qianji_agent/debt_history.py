"""Finite maintenance of native CNY debt bills with both object versions."""
import time
from copy import deepcopy
from decimal import Decimal
from .codec import amount,timestamp,digest
from .operations import select,version,normalize,balance_effect,balances,bill_request,text


def prepare_history(c,s,uid,p):
 raw=select(s['bills'],c['object_id'],uid=uid);version(c,raw);old=normalize(raw)
 debt=select(s['assets'],c['related_id'],uid=uid)
 if c.get('related_version')!=digest(debt):raise ValueError('version_conflict')
 typ=old['type'];borrow=debt.get('stype')==51
 if debt.get('type')!=5 or debt.get('stype') not in (51,52) or debt.get('currency') not in (None,'CNY') or debt.get('status') not in (0,1):raise ValueError('invalid_debt_account')
 if typ not in ((6,9,10) if borrow else (7,4,11)) or old['extra'] or old['packid']!=-1:raise ValueError('specialized_bill_operation_required')
 if str(old['assetid'] if typ in (4,6,7,9) else old['fromid'])!=c['related_id']:raise ValueError('invalid_debt_account')
 cash_id=str(old['targetid'] if typ in (4,6) else old['fromid'] if typ in (7,9) else old['assetid']);cash=select(s['assets'],cash_id,uid=uid)
 if cash.get('type')!=1 or cash.get('currency') not in (None,'CNY'):raise ValueError('debt_requires_cny_cash')
 loan=deepcopy(debt.get('loan'))
 if not isinstance(loan,dict):raise ValueError('invalid_debt_account')
 total=Decimal(str(loan['money']));paid=Decimal(str(loan.get('totalpay') or 0));remaining=Decimal(str(debt['money']));sign=Decimal(-1 if borrow else 1)
 if any(not n.is_finite() or n!=n.quantize(Decimal('.01')) for n in (total,paid,remaining)) or sign*total<0 or paid<0 or paid>abs(total) or remaining!=total-sign*paid:raise ValueError('invalid_debt_account')
 row=deepcopy(old)
 if not {'amount','time','remark'}.intersection(c):raise ValueError('missing_required_fields')
 if 'amount' in c:
  row['money']=amount(c['amount'])
  if debt['status']==1 and row['money']!=Decimal(str(old['money'])):raise ValueError('finished_debt_amount_edit_requires_adapter')
 if 'time' in c:row['time']=timestamp(c['time'])
 if 'remark' in c:row['remark']=text(c['remark'])
 delta=Decimal(str(row['money']))-Decimal(str(old['money']))
 if typ in (6,7):total+=sign*delta;loan['money']=total
 elif typ in (4,9):paid+=delta;loan['totalpay']=paid
 if sign*total<0 or paid<0 or paid>abs(total):raise ValueError('principal_exceeds_remaining')
 row.update(status=2,updatetime=int(time.time()));effect={}
 for r,multiplier in ((old,-1),(row,1)):
  for i,n in balance_effect(r).items():effect[i]=effect.get(i,Decimal(0))+multiplier*n
 effect.setdefault(c['related_id'],Decimal(0))
 p.update(route='bill/syncall',params=bill_request(row),collection='bills',object_id=c['object_id'],row=row,
  expected={k:row[k] for k in ('money','type','time','remark','bookid','assetid','fromid','targetid')},balances=balances(s,effect),
  debt_history={'id':c['related_id'],'loan':loan,'status':debt['status'],'stype':debt['stype']})
 return p
