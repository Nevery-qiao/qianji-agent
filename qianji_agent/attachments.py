"""Content-bound image upload, temporary storage credentials held in RAM only."""
import base64,hashlib,json,os,re,secrets,stat,urllib.request,urllib.error
from pathlib import Path
from .transport import QianjiError,NoRedirect
MAX_IMAGE=8_000_000

def etag(data):
 chunks=[hashlib.sha1(data[i:i+4*1024*1024]).digest() for i in range(0,len(data),4*1024*1024)] or [hashlib.sha1(b'').digest()]
 result=b'\x16'+chunks[0] if len(chunks)==1 else b'\x96'+hashlib.sha1(b''.join(chunks)).digest()
 return base64.urlsafe_b64encode(result).decode().rstrip('=')

def multipart(token,key,data,mime):
 boundary='qianji-agent-'+secrets.token_hex(16);parts=[]
 for name,value in [('token',token),('key',key)]:parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"\r\n\r\n'+value+'\r\n').encode())
 parts.extend([('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="image"\r\nContent-Type: '+mime+'\r\n\r\n').encode(),data,('\r\n--'+boundary+'--\r\n').encode()])
 return b''.join(parts),boundary

def image_bytes(path):
 p=Path(path).expanduser()
 if not p.is_absolute() or p.is_symlink():raise ValueError('image_path_must_be_absolute_regular_file')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=MAX_IMAGE:raise ValueError('invalid_image_size')
  with os.fdopen(fd,'rb',closefd=False) as f:data=f.read(MAX_IMAGE+1)
 finally:os.close(fd)
 if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>=33 and b'IEND' in data[-20:]:mime='image/png'
 elif data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):mime='image/jpeg'
 else:raise ValueError('supported_image_required')
 from .image_content import image_fingerprint
 image_fingerprint(data)
 return data,mime

def prepare_upload(c,owner):
 if set(c)-{'action','image_path'}:raise ValueError('unexpected_fields')
 data,mime=image_bytes(c['image_path']);sha=hashlib.sha256(data).hexdigest();key=hashlib.sha256((owner+sha).encode()).hexdigest()[:32]
 return {'action':'attachment_upload','route':'attachment/upload','params':{},'collection':'uploads','object_id':key,'storage_key':key,'sha256':sha,'etag':etag(data),'image_path':str(Path(c['image_path']).expanduser()),'mime':mime,'balances':{},'expected':{},'before_ids':[]}

def upload_token(data):
 if not isinstance(data,dict) or set(data)!={'v'} or not isinstance(data['v'],str) or not 10<len(data['v'])<10000:raise QianjiError('invalid_response')
 return data['v']

def upload_host(token):
 try:
  policy=token.split(':')[2];policy=json.loads(base64.urlsafe_b64decode(policy+'='*((-len(policy))%4)))
  hosts=policy['upHosts']
  regions={'up.qiniu.com':'','upload.qiniu.com':'','up-z1.qiniu.com':'-z1','upload-z1.qiniu.com':'-z1','up-z2.qiniu.com':'-z2','upload-z2.qiniu.com':'-z2','up-na0.qiniu.com':'-na0','upload-na0.qiniu.com':'-na0','up-as0.qiniu.com':'-as0','upload-as0.qiniu.com':'-as0'}
  for raw in hosts:
   parsed=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(raw)
   if parsed.hostname in regions and parsed.path in ('','/') and parsed.scheme in ('http','https') and not parsed.username and not parsed.password and not parsed.port:
    return 'https://upload'+regions[parsed.hostname]+'.qiniup.com/'
 except Exception:pass
 raise QianjiError('unsupported_upload_destination')

def upload(transport,p):
 data,mime=image_bytes(p['image_path'])
 if hashlib.sha256(data).hexdigest()!=p['sha256']:raise QianjiError('image_changed')
 token=upload_token(transport.read('common/uploadtoken',{'dt':1}))
 if not isinstance(token,str) or not 10<len(token)<10000:raise QianjiError('invalid_response')
 body,boundary=multipart(token,p['storage_key'],data,mime)
 req=urllib.request.Request(upload_host(token),data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
 try:
  with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as r:raw=r.read(100_001)
  if len(raw)>100_000:raise QianjiError('invalid_response')
  result=json.loads(raw)
  if result.get('key')!=p['storage_key'] or result.get('hash')!=p['etag']:raise QianjiError('upload_not_verified')
 except QianjiError:raise
 except Exception:raise QianjiError('result_unknown') from None
 return {'key':result['key'],'hash':result['hash']}

def verify_upload(p):
 try:
  from .image_content import image_fingerprint
  if not re.fullmatch('[a-f0-9]{32}',p['storage_key']):raise QianjiError('upload_not_verified')
  # Shipped Bill.getImageUrl uses this image host and its native !huge style.
  # The CDN may re-encode PNG without changing pixels; that is not byte proof.
  req=urllib.request.Request('https://billimg.qianjiapp.com/'+p['storage_key']+'!huge',headers={'Accept':'image/*'},method='GET')
  with urllib.request.build_opener(NoRedirect()).open(req,timeout=25) as r:data=r.read(MAX_IMAGE+1)
  if len(data)>MAX_IMAGE:raise QianjiError('upload_not_verified')
  downloaded=image_fingerprint(data)
  exact=hashlib.sha256(data).hexdigest()==p['sha256']
  if not exact:
   original,_=image_bytes(p['image_path'])
   if hashlib.sha256(original).hexdigest()!=p['sha256'] or image_fingerprint(original)!=downloaded:raise QianjiError('upload_not_verified')
  return {'object_id':p['storage_key'],'image_key':p['storage_key'],'file_content_verified':exact,'image_pixels_verified':True,'download_variant':'native_huge'}
 except QianjiError:raise
 except Exception:raise QianjiError('upload_not_verified') from None
