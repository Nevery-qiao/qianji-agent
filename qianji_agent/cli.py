"""CLI fallback for an Agent without MCP; input is JSON via stdin."""
import argparse,json,sys
from pathlib import Path
from .codec import dumps
from .models import Command,Filters,ScheduleObservation
from .server import LocalService,public_receipt

def main():
 p=argparse.ArgumentParser(description='钱迹后台记账；先登录官方App。业务指令从stdin读取JSON。')
 p.add_argument('--state-dir');sub=p.add_subparsers(dest='mode',required=True)
 q=sub.add_parser('query');q.add_argument('kind',choices=['books','accounts','account_types','categories','tags','bills','repeat','installments','currencies'])
 sub.add_parser('preview');x=sub.add_parser('execute');x.add_argument('request_id')
 x=sub.add_parser('status');x.add_argument('request_id');x.add_argument('--automatic',action='store_true');sub.add_parser('connection')
 q=sub.add_parser('recovery-list');q.add_argument('--include-closed',action='store_true');q.add_argument('--offset',type=int,default=0);q.add_argument('--limit',type=int,default=100)
 a=sub.add_parser('recovery-ack');a.add_argument('request_id')
 s=sub.add_parser('recovery-scheduler');s.add_argument('--record',action='store_true')
 b=sub.add_parser('backup');b.add_argument('destination',type=Path)
 args=p.parse_args();service=LocalService(args.state_dir)
 try:
  if args.mode in ('preview','execute'):
   command=Command.model_validate_json(sys.stdin.read(1_000_001)).model_dump(exclude_none=True)
   r=service.preview(command) if args.mode=='preview' else service.execute(args.request_id,command)
  elif args.mode=='query':
   value=sys.stdin.read(1_000_001) if not sys.stdin.isatty() else '{}'
   f=Filters.model_validate_json(value or '{}').model_dump(exclude_none=True);r=service.query(args.kind,f)
  elif args.mode=='status':r=service.operation(args.request_id,args.automatic)
  elif args.mode=='recovery-list':r=service.recovery_list(args.include_closed,args.offset,args.limit)
  elif args.mode=='recovery-ack':
   from pydantic import BaseModel,ConfigDict
   from typing import Literal
   class Ack(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    expected_version:str
    disposition:Literal['recorded','handled_without_recording']
    completion_reference:str
   a=Ack.model_validate_json(sys.stdin.read(1_000_001));r=service.recovery_ack(args.request_id,a.expected_version,a.disposition,a.completion_reference)
  elif args.mode=='recovery-scheduler':
   a=ScheduleObservation.model_validate_json(sys.stdin.read(1_000_001)) if args.record else None
   r=service.recovery_scheduler('record',**a.model_dump()) if a else service.recovery_scheduler()
  elif args.mode=='connection':
   read=service.query('books',{'limit':1});r={'state':'connected','book_count':read['total']} if read['state']=='read' else read
  elif args.mode=='backup':service.get().journal.backup(args.destination);r={'state':'verified','backup_created':True}
 except Exception:r={'state':'not_executed','code':'invalid_input_or_connection'}
 r=public_receipt(service,r).model_dump(exclude_none=True);print(dumps(r))
 if r['state'] in ('not_executed','unsupported','failed','pending_verification'):raise SystemExit(2)

if __name__=='__main__':main()
