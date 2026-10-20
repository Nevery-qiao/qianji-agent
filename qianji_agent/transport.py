"""Fixed destination, finite routes, TLS verification and single dispatch."""
import hashlib,http.client,json,time,urllib.parse,urllib.request,urllib.error
from .codec import loads

READS={
 'common/uploadtoken':{'dt'},'book/list':{'t'},'asset/list':{'status'},'category/listv2':{'bookid'},
 'syncv2/pull':{'bookid','lasttimes','pageoffset','pagesign'},'tag/list':{'status','lasttime'},
 'asset/typelist':set(),'asset/banklist':set(),'asset/info':{'did'},'asset/listloan':{'t','status'},
 'book/deletecheck':{'bookid'},'asset/deletecheck':{'did'},'category/deletecheckv2':{'did'},
 'repeat_task/list':{'page','flts'},'installment/list':{'flts'},'currency/listv2':set(),
}
WRITES={
 'book/visible':{'bookid'},'book/submit':{'v'},'book/delete':{'bookid'},'asset/submit':{'v','extra','diffparams'},
 'asset/delete':{'did'},'asset/finish':{'did','v'},'asset/visible':{'did'},
 'category/changelevel':{'did','parentid'},'category/movesubcate':{'did','parentid'},'category/submitv2':{'did','bookid','v','t','icon','parentid'},'category/deletev2':{'did','newcateid'},
 'bill/syncall':{'v'},'bill/refund2':{'did','v'},
 'tag/submitgroup':{'did','v'},'tag/deletegroup':{'did'},'tag/submittag':{'did','v'},
 'tag/deletetag':{'did'},'tag/archivetag':{'did'},
 'repeat_task/submit':{'v'},'repeat_task/toggle':{'did'},'repeat_task/delete':{'did'},
 'installment/prepay':{'v'},'installment/submit':{'v'},'installment/config':{'did','v'},'installment/delete':{'did'},
}
class QianjiError(ValueError):
 def __init__(self,code,response=None,cause_type=None):
  self.code=code;self.response=response;self.cause_type=cause_type;super().__init__(code)

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
class LowercaseConnection(http.client.HTTPSConnection):
 def putheader(self,header,*values):return super().putheader(header.lower(),*values)
class LowercaseHandler(urllib.request.HTTPSHandler):
 def https_open(self,request):return self.do_open(LowercaseConnection,request,context=self._context)

class Transport:
 def __init__(self,session):self.session=session
 def __repr__(self):return '<Transport: private session omitted>'
 def upload(self,plan):
  from .attachments import upload
  return upload(self,plan)
 def read(self,route,params):return self._call(route,params,READS,False)
 def write(self,route,params):return self._call(route,params,WRITES,True)
 def _call(self,route,params,routes,is_write):
  if route not in routes or set(params)-routes[route]:raise QianjiError('unsupported_protocol')
  s=self.session;c,a=route.split('/');h=dict(s.headers);md5=lambda x:hashlib.md5(x.encode()).hexdigest()
  salt,inner,rid_salt=s.salts
  rid=md5('com.mutangtech.qianji.fltios'+str(int(time.time()*1000)+20140216+int(s.build))+c+a+rid_salt)
  h.update(Ctrl=c,Act=a,Reqidv2=rid,Tok=md5(rid+salt+c+md5(rid+inner)+a))
  body=urllib.parse.urlencode({'uid':s.uid,'fr':s.uid,**params}).encode()
  req=urllib.request.Request('https://api.qianjiapp.com/'+route,data=body,headers=h,method='POST')
  try:
   with urllib.request.build_opener(NoRedirect(),LowercaseHandler()).open(req,timeout=25) as r:
    if r.status!=200:raise QianjiError('transport_failure',{'http_status':r.status})
    raw=r.read(8_000_001)
   if len(raw)>8_000_000:raise QianjiError('invalid_response')
   reply=loads(raw)
   if not isinstance(reply,dict) or type(reply.get('ec')) is not int:raise QianjiError('invalid_response')
   if reply['ec']!=200:
    msg=reply.get('em')
    try:msg=json.loads(msg) if isinstance(msg,str) else msg
    except ValueError:pass
    evidence={'ec':reply['ec'],'em':reply.get('em')}
    if reply['ec']==8888 and msg=='设备异常，请重新登录':raise QianjiError('reconnect_required',evidence)
    if reply['ec']==8888 and msg=='请升级到最新的公测版本':raise QianjiError('feature_unavailable',evidence)
    raise QianjiError('backend_result_unknown',evidence)
   return reply.get('data')
  except QianjiError:raise
  except urllib.error.HTTPError as e:
   raise QianjiError('result_unknown' if is_write else 'read_unavailable',{'http_status':e.code},'HTTPError') from None
  except Exception as e:raise QianjiError('result_unknown' if is_write else 'read_unavailable',cause_type=type(e).__name__) from None
