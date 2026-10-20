"""Finite native reads; never label a truncated or inconsistent source complete."""
from .codec import dumps,ident
from .transport import QianjiError

def records(data,key='list'):
 if not isinstance(data,dict) or not isinstance(data.get(key),list) or not all(isinstance(r,dict) for r in data[key]):raise QianjiError('invalid_response')
 return data[key]

def pull_bills(transport):
 params={'bookid':-1,'lasttimes':'{}','pageoffset':0};seen_cursors=set();seen_ids=set();bills=[];deletes=[];lasttimes={}
 for _ in range(100):
  signature=dumps(params)
  if signature in seen_cursors:raise QianjiError('incomplete_sync')
  seen_cursors.add(signature);data=transport.read('syncv2/pull',params)
  changes=records(data,'changes')
  if not isinstance(data.get('deletes'),list) or not isinstance(data.get('categories'),list):raise QianjiError('invalid_response')
  for row in changes:
   key=str(row.get('id'));ident(key)
   if key in seen_ids:raise QianjiError('incomplete_sync')
   seen_ids.add(key);bills.append(row)
  for did in data['deletes']:ident(str(did));deletes.append(did)
  if type(data.get('hasmore')) is not int or data['hasmore'] not in (0,1):raise QianjiError('incomplete_sync')
  if data['hasmore']==0:
   if seen_ids.intersection(str(x) for x in deletes):raise QianjiError('incomplete_sync')
   return bills,deletes
  book=data.get('bookid');offset=data.get('pageoffset');sign=data.get('pagesign');last=data.get('lasttimes')
  if type(book)is not int or type(offset)is not int or offset<0 or not isinstance(sign,str) or not sign or len(sign)>512 or not isinstance(last,dict):raise QianjiError('incomplete_sync')
  ident(str(book),True)
  if book==params['bookid'] and offset<=params['pageoffset']:raise QianjiError('incomplete_sync')
  lasttimes.update(last)
  params={'bookid':book,'pageoffset':offset,'pagesign':sign,'lasttimes':dumps(lasttimes)}
 raise QianjiError('incomplete_sync')

def complete_records(data):
 marker=data.get('hasmore',0) if isinstance(data,dict) else None
 if type(marker) not in (int,bool) or marker!=0:raise QianjiError('incomplete_sync')
 return records(data)

def read_accounts(transport,status='active'):
 if status not in ('active','hidden','finished','all'):raise QianjiError('invalid_filter')
 result=[]
 for state in ([0,2] if status=='all' else [0] if status=='active' else [2] if status=='hidden' else []):
  part=complete_records(transport.read('asset/list',{'status':state}))
  if any(r.get('status',0)!=state for r in part):raise QianjiError('invalid_response')
  result.extend(part)
 if status in ('finished','all'):
  for subtype in (51,52):
   part=complete_records(transport.read('asset/listloan',{'t':subtype,'status':1}))
   if any(r.get('status')!=1 or r.get('type')!=5 or r.get('stype')!=subtype for r in part):raise QianjiError('invalid_response')
   result.extend(part)
 if len({str(r.get('id')) for r in result})!=len(result):raise QianjiError('invalid_response')
 return result
