import json, tempfile, unittest, base64, plistlib, hashlib
from decimal import Decimal
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
try:
 from qianji_agent import codec, auth, transport
except ImportError:
 codec=auth=transport=None

class ConnectionTests(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(codec,'Independent product connection modules required')
 def test_decimal_is_exact_and_float_rejected(self):
  self.assertEqual(codec.dumps({'n':Decimal('9007199254740993.01')}),'{"n":9007199254740993.01}')
  with self.assertRaises(ValueError):codec.dumps({'n':0.1})
 def test_id_precision_and_invalid_ids(self):
  self.assertEqual(codec.ident('9007199254740993123'),9007199254740993123)
  for value in [12,True,'1e10','-2','9223372036854775808']:
   with self.subTest(value=value),self.assertRaises(ValueError):codec.ident(value)
 def test_time_requires_offset_whole_second(self):
  self.assertEqual(codec.timestamp('2026-10-18T08:00:00+08:00'),1792281600)
  for v in ['2026-10-18','2026-10-18T08:00:00','2026-10-18T08:00:00.123+08:00']:
   with self.assertRaises(ValueError):codec.timestamp(v)
 def test_no_nan_in_money(self):
  for v in ['NaN','Infinity','0.00','-1.00','0.001',0.1]:
   with self.assertRaises(ValueError):codec.amount(v)
 def test_secret_decrypt_synthetic_account(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); app=root/'app'; (app/'Frameworks/App.framework/Versions/A').mkdir(parents=True)
   binary=app/'Frameworks/App.framework/Versions/A/App';binary.write_bytes(b'synthetic app')
   (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion':'1580','CFBundleIdentifier':'com.mutangtech.qianji.fltios','CFBundleShortVersionString':'4.5.9'}))
   profile={'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'key':base64.b64encode(b'k'*32).decode(),'iv':base64.b64encode(b'i'*16).decode(),'salts':['a','b','c'],'dart':'3.11','build':'1580'}
   def enc(s):
    b=s.encode(); pad=16-len(b)%16;b+=bytes([pad])*pad
    c=Cipher(algorithms.AES(b'k'*32),modes.CTR(b'i'*16)).encryptor()
    return base64.b64encode(c.update(b)+c.finalize()).decode()
   prefs=root/'prefs';prefs.write_bytes(plistlib.dumps({'flutter.u_account_datav2':enc('{"id":123}'),'flutter.u_actok2_123':enc('private-token'),'flutter.local_device_id':'private-device'}))
   s=auth.load_session(app,prefs,profile)
   self.assertEqual(s.uid,'123');self.assertEqual(s.headers['utoken'],'private-token')
   self.assertNotIn('private-token',repr(s));self.assertNotIn('123',repr(s))
   profile['sha256']='0'*64
   with self.assertRaises(transport.QianjiError) as e:auth.load_session(app,prefs,profile)
   self.assertEqual(e.exception.code,'adapter_update_required')
 def test_route_allowlist_and_identity_override(self):
  s=auth.Session('123',{},('a','b','c'),'1580');t=transport.Transport(s)
  for route,params in [('account/login',{}),('book/list',{'uid':'other'}),('https://evil.example',{})]:
   with self.assertRaises(transport.QianjiError):t.read(route,params)
 def test_wire_headers_lowercase_and_tls_verified(self):
  import ssl
  c=transport.LowercaseConnection('api.qianjiapp.com');c._buffer=[];c._HTTPConnection__state='Request-started'
  c.putheader('Utoken','synthetic')
  self.assertEqual(c._buffer,[b'utoken: synthetic'])
  h=transport.LowercaseHandler(context=ssl.create_default_context());self.assertTrue(h._context.check_hostname)
 def test_error_has_no_backend_message(self):
  e=transport.QianjiError('backend_rejected');self.assertEqual(str(e),'backend_rejected')
 def test_owner_identity_is_opaque_not_bill_numeric_id(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);app=root/'app';(app/'Frameworks/App.framework/Versions/A').mkdir(parents=True)
   (app/'Frameworks/App.framework/Versions/A/App').write_bytes(b'app')
   (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion':'1580','CFBundleIdentifier':'com.mutangtech.qianji.fltios','CFBundleShortVersionString':'4.5.9'}))
   profile={'sha256':hashlib.sha256(b'app').hexdigest(),'key':base64.b64encode(b'k'*32).decode(),'iv':base64.b64encode(b'i'*16).decode(),'salts':['a','b','c'],'dart':'3.11','build':'1580'}
   def enc(s):
    b=s.encode();pad=16-len(b)%16;b+=bytes([pad])*pad;c=Cipher(algorithms.AES(b'k'*32),modes.CTR(b'i'*16)).encryptor();return base64.b64encode(c.update(b)+c.finalize()).decode()
   p=root/'prefs';p.write_bytes(plistlib.dumps({'flutter.u_account_datav2':enc('{"id":"user-opaque-a123"}'),'flutter.u_actok2_user-opaque-a123':enc('private-token'),'flutter.local_device_id':'private-device','flutter.user-opaque-a123_confu_basecur':'USD'}))
   session=auth.load_session(app,p,profile);self.assertEqual(session.uid,'user-opaque-a123');self.assertEqual(session.base_currency,'USD')
 def test_storage_multipart_and_hash_are_content_bound_no_session_token(self):
  from qianji_agent import attachments
  data=b'\x89PNG\r\n\x1a\n'+b'test-image'
  body,boundary=attachments.multipart('temporary-storage-token','a'*32,data,'image/png')
  self.assertIn(b'name="token"',body);self.assertIn(b'name="file"',body)
  self.assertIn(data,body);self.assertNotIn(b'utoken',body)
  self.assertNotEqual(attachments.etag(data),attachments.etag(data+b'x'))
 def test_native_upload_token_value_envelope_is_not_public_data(self):
  from qianji_agent.attachments import upload_token
  self.assertEqual(upload_token({'v':'opaque-temporary-upload-token'}),'opaque-temporary-upload-token')
  for v in [{'utoken':'login-secret'},{'v':3},'unexpected-direct-token']:
   with self.assertRaises(transport.QianjiError):upload_token(v)
 def test_upload_host_uses_token_region_but_rejects_arbitrary_destinations(self):
  from qianji_agent.attachments import upload_host
  def tok(hosts):return 'public:signature:'+base64.urlsafe_b64encode(json.dumps({'upHosts':hosts}).encode()).decode().rstrip('=')
  self.assertEqual(upload_host(tok(['http://up-z2.qiniu.com','-H injected'])),'https://upload-z2.qiniup.com/')
  with self.assertRaises(transport.QianjiError):upload_host(tok(['https://evil.example/token']))
 def test_native_error_messages_and_http_failures_are_classified_without_leaks(self):
  import io
  from unittest.mock import patch
  s=auth.Session('synthetic-owner',{'utoken':'private-login'},('a','b','c'),'1580');t=transport.Transport(s)
  class Reply(io.BytesIO):status=200
  class Opener:
   def __init__(self,body):self.body=body;self.calls=0
   def open(self,*a,**k):self.calls+=1;return Reply(self.body)
  cases=[({'ec':8888,'em':'设备异常，请重新登录'},'reconnect_required'),({'ec':8888,'em':'请升级到最新的公测版本'},'feature_unavailable'),({'ec':8888,'em':'private-backend-message'},'backend_result_unknown'),({'ec':'200','data':{}},'invalid_response')]
  for reply,want in cases:
   opener=Opener(json.dumps(reply).encode())
   with patch('qianji_agent.transport.urllib.request.build_opener',return_value=opener):
    with self.assertRaises(transport.QianjiError) as error:t.write('bill/syncall',{'v':'{}'})
    self.assertEqual(error.exception.code,want);self.assertNotIn('private-',str(error.exception));self.assertEqual(opener.calls,1)
 def test_redirect_handler_never_forwards_user_headers(self):
  self.assertIsNone(transport.NoRedirect().redirect_request(None,None,302,'redirect',{},'https://evil.example'))
