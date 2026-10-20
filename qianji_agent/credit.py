"""Native CreditInfo dates: fixed day '21', statement-relative '20d'."""
from copy import deepcopy
from decimal import Decimal
from .codec import amount

SETTINGS={'limit','statement_day','payment_day','payment_after_statement_days','statement_inclusive','clear_credit_limit'}
def apply_credit(command,existing=None):
 c=command;credit=deepcopy(existing) if existing is not None else {'statedate':1,'paydate2':'20','limit':-1,'statein':0}
 if 'payment_day' in c and 'payment_after_statement_days' in c:raise ValueError('conflicting_credit_dates')
 if 'clear_credit_limit' in c:
  if c['clear_credit_limit'] is not True or 'limit' in c:raise ValueError('invalid_credit_limit')
  credit['limit']=-1
 if 'limit' in c:credit['limit']=amount(c['limit'],zero=True)
 for field,key in [('statement_day','statedate'),('payment_day','paydate2'),('payment_after_statement_days','paydate2')]:
  if field not in c:continue
  day=c[field]
  if type(day)is not int or not 1<=day<=31:raise ValueError('invalid_credit_day')
  credit[key]=day if field=='statement_day' else str(day)+('d' if field=='payment_after_statement_days' else '')
 if 'statement_inclusive' in c:
  if type(c['statement_inclusive'])is not bool:raise ValueError('invalid_bill_flag')
  credit['statein']=int(c['statement_inclusive'])
 return credit


def apply_shared(c,s,uid,old,v,expected):
 from .operations import select
 from .codec import digest,ident
 related=[];all_assets=s.get('relationship_assets',s['assets'])
 if c.get('clear_credit_limit') and any(str((r.get('credit') or {}).get('shareid'))==c['object_id'] for r in all_assets):raise ValueError('shared_limit_has_members')
 if 'shared_limit_account_id' not in c:
  if 'shared_limit_version' in c:raise ValueError('unexpected_fields')
  if (old.get('credit') or {}).get('shareid') not in (None,-1,0,'') and ('limit' in c or 'clear_credit_limit' in c):raise ValueError('shared_limit_member_uses_parent')
  return related
 if old.get('type')!=2 or not isinstance(old.get('credit'),dict):raise ValueError('repayment_requires_credit')
 target=c['shared_limit_account_id'];credit=deepcopy(v['credit']);old_parent=(old.get('credit') or {}).get('shareid')
 if old_parent not in (None,-1,0,''):related.append(select(all_assets,str(old_parent),uid=uid))
 if target=='-1':
  if c.get('shared_limit_version') is not None:raise ValueError('unexpected_fields')
  credit.pop('shareid',None)
 else:
  ident(target)
  if target==c['object_id'] or 'limit' in c or 'clear_credit_limit' in c:raise ValueError('invalid_shared_credit')
  parent=select(all_assets,target,uid=uid)
  if c.get('shared_limit_version')!=digest(parent):raise ValueError('version_conflict')
  pc=parent.get('credit')
  if parent.get('type')!=2 or parent.get('status',0)!=0 or parent.get('currency')!=old.get('currency') or not isinstance(pc,dict) or pc.get('shareid') not in (None,-1,0,''):raise ValueError('invalid_shared_credit')
  limit=Decimal(str(pc.get('limit')))
  if not limit.is_finite() or limit<0:raise ValueError('invalid_shared_credit')
  if any(str((r.get('credit') or {}).get('shareid'))==c['object_id'] for r in all_assets):raise ValueError('invalid_shared_credit')
  credit['shareid']=parent['id'];credit['limit']=pc['limit'];related.append(parent)
 v['credit']=credit;expected['credit']=deepcopy(credit)
 return [{k:a[k] for k in ('id','money','currency','type','status','credit') if k in a} for a in {str(a['id']):a for a in related}.values()]
