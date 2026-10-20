"""Maintain a generated repeat bill without silently changing its schedule."""
from copy import deepcopy
from .codec import digest
from .operations import select,version,normalize,prepare,bill_request,ALLOWED


def prepare_scheduled(c,s,uid,bill_id=None,now=None):
 action=c['action'];raw=select(s['bills'],c['object_id'],uid=uid);version(c,raw);row=normalize(raw)
 task=select(s['repeat'],c['related_id'],uid=uid)
 if c.get('related_version')!=digest(task):raise ValueError('version_conflict')
 pack=row['packid']
 if type(pack)is not int or pack<=0 or task.get('packid')!=pack or row['type'] not in (0,1,2,3,5) or row['type']!=task.get('type'):raise ValueError('unsupported_task_bill_relation')
 if sum(t.get('packid')==pack for t in s['repeat']+s['installment'])!=1:raise ValueError('unsupported_task_bill_relation')
 base=action.removeprefix('scheduled_');delegated={k:v for k,v in c.items() if k not in ('related_id','related_version')};delegated['action']=base
 if set(delegated)-ALLOWED[base]-{'action','expected_version'}:raise ValueError('unexpected_fields')
 shadow={**s,'repeat':[t for t in s['repeat'] if str(t['id'])!=c['related_id']]}
 p=prepare(delegated,shadow,uid,bill_id=bill_id,now=now)
 if base=='bill_copy':
  p['row']['packid']=-1;p['expected']['packid']=-1;p['params']=bill_request(p['row'])
 elif base=='bill_update':p['expected']['packid']=pack
 p['action']=action;p['scheduled_task']={'collection':'repeat','row':deepcopy(task)}
 return p
