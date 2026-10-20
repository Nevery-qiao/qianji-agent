"""Exact wire encoding; public IDs and amounts never become binary floats."""
import datetime as dt
import json,re,hashlib
from decimal import Decimal

def dumps(v):
 if isinstance(v,Decimal):
  if not v.is_finite():raise ValueError('invalid_decimal')
  return format(v,'f')
 if v is None or type(v) in (str,int,bool):return json.dumps(v,ensure_ascii=False,allow_nan=False)
 if isinstance(v,(list,tuple)):return '['+','.join(dumps(x) for x in v)+']'
 if isinstance(v,dict) and all(isinstance(k,str) for k in v):return '{'+','.join(json.dumps(k,ensure_ascii=False)+':'+dumps(x) for k,x in v.items())+'}'
 raise ValueError('inexact_json')

def loads(s):return json.loads(s,parse_float=Decimal,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('invalid_number')))

def ident(v,default_book=False):
 if default_book and v=='-1':return -1
 if type(v) is not str or not re.fullmatch('[1-9][0-9]{0,18}',v) or int(v)>2**63-1:raise ValueError('invalid_id')
 return int(v)

def amount(v,zero=False,signed=False):
 pattern=r'-?[0-9]+\.[0-9]{2}' if signed else r'[0-9]+\.[0-9]{2}'
 if type(v) is not str or len(v)>20 or not re.fullmatch(pattern,v):raise ValueError('invalid_amount')
 n=Decimal(v)
 if not signed and (n<0 or (n==0 and not zero)):raise ValueError('invalid_amount')
 return n

def timestamp(v):
 if type(v) is not str:raise ValueError('invalid_time')
 t=dt.datetime.fromisoformat(v)
 if t.tzinfo is None or t.microsecond:raise ValueError('explicit_offset_whole_seconds_required')
 n=int(t.timestamp())
 if n<=0:raise ValueError('invalid_time')
 return n

def digest(v):
 def ordered(x):
  if isinstance(x,dict):return {k:ordered(x[k]) for k in sorted(x)}
  if isinstance(x,list):return [ordered(a) for a in x]
  return x
 return hashlib.sha256(dumps(ordered(v)).encode()).hexdigest()
