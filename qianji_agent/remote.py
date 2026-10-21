"""Authenticated, loopback-only remote readonly profile over the original MCP core."""
import argparse
import hmac
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit
from mcp.server.transport_security import TransportSecuritySettings
from .server import build_server, LocalService

class ExistingLocalService(LocalService):
 """Remote access must attach to an existing original journal, never initialize one."""
 def __init__(self,root=None):
  root=Path(root) if root else Path.home()/'Library/Application Support/qianji-agent'
  self._original_path=root/'operations.sqlite3'
  self._original_identity=self._check_original()
  super().__init__(root,existing_journal=True,journal_identity=self._original_identity)
 def _check_original(self):
  root=self._original_path.parent
  if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:raise ValueError('original_journal_required')
  st=self._original_path.lstat()
  if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode & 0o077:raise ValueError('original_journal_required')
  return st.st_dev,st.st_ino
 def get(self):
  if self._check_original()!=self._original_identity:raise ValueError('original_journal_changed')
  return super().get()

class ReadOnlyService:
 """Backend guard in addition to the MCP registration allowlist."""
 def __init__(self, service): self._service=service
 def query(self,kind,filters=None):
  if kind not in {'books','accounts','account_types','categories','tags','bills','repeat','installments','currencies'}:raise PermissionError('remote_readonly')
  return self._service.query(kind,filters)
 def recovery_list(self,*a):return self._service.recovery_list(*a)
 def account_review(self):return self._service.account_review()
 def account_review_summary(self):return self._service.account_review_summary()
 def recovery_scheduler(self,action='status',**kwargs):
  if action!='status' or kwargs:raise PermissionError('remote_readonly')
  return self._service.recovery_scheduler()
 def __getattr__(self,name):raise PermissionError('remote_readonly')

def read_token(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'r') as handle:
  st=os.fstat(handle.fileno())
  if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_uid!=os.getuid() or st.st_size>1024:raise ValueError('unsafe_token_file')
  value=handle.read().strip()
  if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',value):raise ValueError('unsafe_token_file')
  return value

class BearerGate:
 def __init__(self,app,token_file):self.app=app;self.token_file=Path(token_file)
 async def __call__(self,scope,receive,send):
  if scope['type']!='http':return await self.app(scope,receive,send)
  values=[v for k,v in scope['headers'] if k.lower()==b'authorization']
  try:valid=len(values)==1 and hmac.compare_digest(values[0],('Bearer '+read_token(self.token_file)).encode())
  except (OSError,ValueError):valid=False
  if not valid:
   await send({'type':'http.response.start','status':401,'headers':[(b'content-type',b'application/json'),(b'cache-control',b'no-store'),(b'www-authenticate',b'Bearer')]})
   return await send({'type':'http.response.body','body':b'{"error":"unauthorized"}'})
  return await self.app(scope,receive,send)

def build_remote_app(service,token_file,public_url,port=8769):
 parsed=urlsplit(public_url)
 if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.path not in ('','/mcp') or parsed.query or parsed.fragment:raise ValueError('invalid_public_https_url')
 read_token(token_file)
 security=TransportSecuritySettings(enable_dns_rebinding_protection=True,allowed_hosts=[parsed.hostname,parsed.hostname+':443',f'127.0.0.1:{port}'],allowed_origins=['https://'+parsed.netloc])
 app=build_server(ReadOnlyService(service),read_only=True).streamable_http_app(json_response=True,stateless_http=True,transport_security=security,host='127.0.0.1',max_request_body_size=262144)
 return BearerGate(app,token_file)

def main():
 p=argparse.ArgumentParser(description='Qianji authenticated remote readonly MCP; no financial writes')
 p.add_argument('--token-file',required=True,type=Path);p.add_argument('--public-url',required=True);p.add_argument('--port',type=int,default=8769)
 args=p.parse_args()
 if not 1024<=args.port<=65535:p.error('invalid port')
 import logging,uvicorn
 # Never log request bodies, credentials, financial results or SDK tool arguments.
 logging.getLogger('mcp').setLevel(logging.CRITICAL)
 app=build_remote_app(ExistingLocalService(),args.token_file,args.public_url,args.port)
 uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,log_level='critical',proxy_headers=False)
if __name__=='__main__':main()
