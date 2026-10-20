"""Local stdio MCP. All tools use the same durable execution core as CLI."""
from typing import Literal
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from .models import Command,Filters,Receipt,ScheduleObservation

READ_HINT=ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=True)
WRITE_HINT=ToolAnnotations(readOnlyHint=False,destructiveHint=True,idempotentHint=True,openWorldHint=True)
META_HINT=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=True,openWorldHint=False)

def public_receipt(service,value):
 from . import __version__
 result={**value,'runtime_version':__version__}
 if 'account_review' not in result:
  try:
   if result.get('state')=='not_executed':raise ValueError('current result unavailable')
   result['account_review']=service.account_review_summary()
  except Exception:result['account_review']={'state':'unavailable','current':False,'ready':False,'observed_at':None,'accounts':[]}
 if 'recovery' not in result:
  try:
   summary=service.recovery_scheduler()
   if summary['state']!='read':raise ValueError('metadata unavailable')
   result.update(recovery=summary['recovery'],tracking=summary['tracking'])
  except Exception:result.update(recovery={'available':False},tracking={'ready':False,'action':'inspect','code':'recovery_metadata_unavailable'})
 return Receipt(**result)

def build_server(service):
 def receipt(value):return public_receipt(service,value)
 server=MCPServer('Qianji-Agent',instructions='钱迹后台记账工具。先查询对象及能力；金额和ID使用字符串。每条独立指令使用唯一request_id，同一指令保持不变。修改/删除携带最新version。待核实结果仅查询状态，禁止换编号重发。是否征求用户确认由Agent按用户授权决定。')
 @server.tool(annotations=READ_HINT,structured_output=True)
 def qianji_connection() -> Receipt:
  """核对官方App登录态能否后台读取；不返回账号或登录信息。"""
  r=service.query('books',{'limit':1})
  return receipt({'state':'connected','book_count':r['total']} if r['state']=='read' else r)
 @server.tool(annotations=READ_HINT,structured_output=True)
 def qianji_capabilities() -> Receipt:
  """列出当前代码已开放的操作及限制；存在操作不代表其全部组合已验收。"""
  from .operations import ALLOWED
  from .linked import SUPPORTED
  import json
  from pathlib import Path
  connection=service.query('books',{'limit':1})
  groups=json.loads((Path(__file__).parent/'capabilities.json').read_text())['groups']
  return receipt(dict(state='read',compatible=connection['state']=='read',code=connection.get('code'),capabilities=groups,operations=sorted(set(ALLOWED)|set(SUPPORTED)|{'attachment_upload'}),limitations=['当前官方macOS4.5.9/build1580适配；新版本先暂停。','原生报销结算仍受接口限制；不改账号升级。','跨机、未来日期触发和真实登录失效需单独验收；详见安装包能力矩阵。','恢复队列适用全部动作；历史未知仅在通用普通新增合同内接续，其他依赖仍暂停。开始/批末/交班调用account_review；账户差异保持停止，宿主跟进未接通时不保证无人值守。']))
 @server.tool(annotations=READ_HINT,structured_output=True)
 def qianji_query(kind:Literal['books','accounts','account_types','categories','tags','bills','repeat','installments','currencies'],filters:Filters|None=None) -> Receipt:
  """查询原生对象、账目与任务；ID和金额字符串，version供修改/删除使用。日期上界不包含在内。"""
  return receipt(service.query(kind,filters.model_dump(exclude_none=True) if filters else {}))
 @server.tool(annotations=READ_HINT,structured_output=True)
 def qianji_preview(command:Command) -> Receipt:
  """校验指令与引用并预览余额影响，不发写请求；预览不是强制人工审批。"""
  return receipt(service.preview(command.model_dump(exclude_none=True)))
 @server.tool(annotations=WRITE_HINT,structured_output=True)
 def qianji_execute(request_id:str,command:Command) -> Receipt:
  """执行已获用户授权的记账指令；稳定请求编号防重复，成功必须通过原生回读核验。"""
  return receipt(service.execute(request_id,command.model_dump(exclude_none=True)))
 @server.tool(annotations=READ_HINT,structured_output=True)
 def qianji_operation_status(request_id:str,automatic:bool=False) -> Receipt:
  """查询并核对待核实操作的原生结果；此调用不会重发写请求。"""
  return receipt(service.operation(request_id,automatic))
 @server.tool(annotations=READ_HINT,structured_output=True)
 def qianji_recovery_list(include_closed:bool=False,offset:int=0,limit:int=100) -> Receipt:
  """列出持久待核实及待收尾事项；检查开始、每批结束和定时跟进均调用。无金融发送。"""
  return receipt(service.recovery_list(include_closed,offset,limit))
 @server.tool(annotations=META_HINT,structured_output=True)
 def qianji_account_review() -> Receipt:
  """复核账户自然余额/账单/结构并持久保存停止原因；开始、批末及交班调用。不发送金融请求，不重查旧号或恢复旧核实预算。"""
  return receipt(service.account_review())
 @server.tool(annotations=META_HINT,structured_output=True)
 def qianji_recovery_ack(request_id:str,expected_version:str,disposition:Literal['recorded','handled_without_recording'],completion_reference:str) -> Receipt:
  """原结果已查明且调用方接续台账/处置后确认收尾；未知不能关闭。只改恢复元数据。"""
  return receipt(service.recovery_ack(request_id,expected_version,disposition,completion_reference))
 @server.tool(annotations=META_HINT,structured_output=True)
 def qianji_recovery_scheduler(action:Literal['status','record']='status',observation:ScheduleObservation|None=None) -> Receipt:
  """读取唯一调度意图或登记宿主正规回读；此工具不直接创建/取消宿主任务，也不发送金融请求。"""
  if action=='status' and observation is not None:return receipt({'state':'not_executed','code':'invalid_recovery_schedule'})
  if action=='record' and observation is None:return receipt({'state':'not_executed','code':'missing_required_fields'})
  return receipt(service.recovery_scheduler(action,**(observation.model_dump() if observation else {})))
 return server

class LocalService:
 def __init__(self,state_dir=None):self.engine=None;self.state_dir=state_dir
 def get(self):
  from .auth import load_session
  from .engine import Engine
  from .transport import Transport,QianjiError
  from pathlib import Path
  if self.state_dir is not None and not Path(self.state_dir).expanduser().is_absolute():raise QianjiError('unsafe_state_path')
  session=load_session()
  if self.engine is not None:
   if self.engine.owner!=session.uid:raise QianjiError('account_changed')
   self.engine.transport=Transport(session)
  else:self.engine=Engine(Transport(session),session.uid,self.state_dir,session_guard=self._guard)
  return self.engine
 def _guard(self):
  from .auth import load_session
  from .transport import Transport,QianjiError
  current=load_session()
  if current.uid!=self.engine.owner:raise QianjiError('account_changed')
  return Transport(current)
 def _invoke(self,method,*args,**kwargs):
  from .engine import safe_code
  try:return getattr(self.get(),method)(*args,**kwargs)
  except Exception as e:return {'state':'not_executed','code':safe_code(e)}
 def query(self,*a):return self._invoke('query',*a)
 def preview(self,*a):return self._invoke('preview',*a)
 def execute(self,*a):return self._invoke('execute',*a)
 def operation(self,*a):return self._invoke('operation',*a)
 def account_review(self):return self._invoke('account_review')
 def account_review_summary(self):
  if self.engine is None:return {'state':'unavailable','ready':False,'current':False,'observed_at':None,'accounts':[]}
  return self.engine.account_review_summary()
 def recovery_list(self,*a):return self._invoke('recovery_list',*a)
 def recovery_ack(self,*a):return self._invoke('recovery_ack',*a)
 def recovery_scheduler(self,*a,**kw):return self._invoke('recovery_scheduler',*a,**kw)

def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--state-dir');args=p.parse_args()
 build_server(LocalService(args.state_dir)).run(transport='stdio')

if __name__=='__main__':main()
