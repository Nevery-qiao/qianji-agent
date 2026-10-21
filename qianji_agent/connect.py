"""Offline integration routing. Never reads App credentials or creates a journal."""
import argparse,json,platform

def recommend(location,transport,mac_available,goal='read'):
 result={'state':'needs_information','route':None,'guide':'docs/AGENT-CONNECTION.md','financial_access_granted':False,'questions':[]}
 if location=='unknown':result['questions'].append('Agent 的 MCP 命令实际在哪台机器执行：钱迹所在 Mac，还是云端/另一台机器？')
 if transport=='unknown':result['questions'].append('平台支持 stdio 命令、远程 MCP URL，还是两者都不支持？')
 if mac_available=='unknown':result['questions'].append('是否有已登录官方钱迹、可保持在线的 Mac？')
 if result['questions']:return result
 if mac_available!='yes':return {**result,'state':'blocked','reason':'需要官方钱迹所在 Mac；不把登录材料复制到云端。'}
 if location=='same-mac' and transport in ('stdio','both'):
  return {**result,'state':'ready_for_validation','route':'local_stdio','method':'在同一 Mac 启动 qianji-agent-mcp；安装 Skill，核对连接、恢复全分页和 fresh account_review。权限另按用户授权。'}
 if location=='same-mac' and transport=='none':
  return {**result,'state':'ready_for_validation','route':'limited_local_cli','method':'仅在明确支持本机命令且用户授权时使用 qianji-agent CLI；CLI不是完整MCP接续合同。'}
 if transport in ('http','both'):
  if goal=='write':return {**result,'state':'blocked','reason':'本次远程合同只读，尚未开放金融写入。'}
  return {**result,'state':'ready_for_validation','route':'remote_readonly','method':'在钱迹 Mac 运行 qianji-agent-remote，经已部署 HTTPS 加 Bearer 鉴权连接平台 MCP URL；核对五工具及原 scope。'}
 return {**result,'state':'blocked','reason':'远端 stdio 命令不能启动 Mac 路径；连接 Mac 的 shell 能力不等于平台支持 Mac stdio。需远程 MCP URL 支持或实际 Mac MCP 宿主。'}

def main():
 p=argparse.ArgumentParser(description='离线判断 Agent 钱迹接入方法，不读取账务/登录信息')
 p.add_argument('--agent-location',choices=['same-mac','cloud','other-machine','unknown'],default='unknown')
 p.add_argument('--mcp',choices=['stdio','http','both','none','unknown'],default='unknown')
 p.add_argument('--mac-available',choices=['yes','no','unknown'],default='unknown')
 p.add_argument('--goal',choices=['read','write'],default='read')
 args=p.parse_args();result=recommend(args.agent_location,args.mcp,args.mac_available,args.goal)
 result['diagnostic_host_os']=platform.system();result['host_os_is_not_agent_location_proof']=True
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
