"""Version-aware allowlisted handoff builder. No App, account, or config writes."""
from pathlib import Path
import argparse,csv,hashlib,json,shutil,tempfile,tomllib,zipfile

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def build_bundle(root,parent,*,matrix='docs/本机能力验收-v0.1.csv',summary='docs/local-closeout.json'):
 root=Path(root).resolve();parent=Path(parent).resolve();project=tomllib.loads((root/'pyproject.toml').read_text());v=project['project']['version']
 if not v or any(c not in '0123456789.-abcdefghijklmnopqrstuvwxyz'for c in v):raise ValueError('invalid_version')
 out=parent/f'qianji-agent-{v}';archive=parent/f'qianji-agent-{v}-delivery.zip'
 if out.exists()or archive.exists()or archive.with_suffix('.zip.sha256').exists():raise FileExistsError('delivery_exists')
 wheel=root/'dist'/f'qianji_agent-{v}-py3-none-any.whl';source=root/'dist'/f'qianji-agent-{v}-source.zip'
 with zipfile.ZipFile(wheel)as z:
  meta=[n for n in z.namelist()if n.endswith('.dist-info/METADATA')]
  if len(meta)!=1 or f'Version: {v}'not in z.read(meta[0]).decode().splitlines():raise ValueError('wheel_version_mismatch')
 with zipfile.ZipFile(source)as z:
  if tomllib.loads(z.read(f'qianji-agent-{v}/pyproject.toml').decode())['project']['version']!=v:raise ValueError('source_version_mismatch')
 accepted=json.loads((root/summary).read_text())
 tool_count=accepted.get('mcp_tools')
 if type(tool_count)is not int or tool_count<1:raise ValueError('summary_tool_count_missing')
 if accepted['version']!=v or accepted['open_operations']!=51 or accepted['original_scope_groups']!=48 or accepted['whole_scope_complete']is not False or accepted['cross_machine_tested']is not False or accepted['github_published']is not False:raise ValueError('summary_scope_mismatch')
 parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix='.qianji-delivery-',dir=parent))
 try:
  def copy(src,target):
   if src.is_symlink()or not src.is_file():raise ValueError('public_file_missing_or_symlink')
   target=stage/target;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
  for p in (wheel,source):copy(p,'packages/'+p.name)
  files={'README.md','requirements.lock.txt','skills/qianji-bookkeeping/SKILL.md','tools/verify_delivery.py'}
  if (root/'LICENSE').is_file():files.add('LICENSE')
  for paths in project['tool']['setuptools']['data-files'].values():files.update(paths)
  for name in sorted(files):
   p=Path(name)
   if p.is_absolute()or '..'in p.parts or not(name in ('README.md','requirements.lock.txt','CONTRIBUTING.md','SECURITY.md','LICENSE')or name.startswith(('docs/','skills/','tools/'))):raise ValueError('non_public_data_file')
   copy(root/p,p)
  copy(root/matrix,'docs/完整48组能力矩阵.csv');copy(root/summary,'docs/验收摘要.json')
  from qianji_agent.operations import ALLOWED
  from qianji_agent.linked import SUPPORTED
  actions={**ALLOWED,**SUPPORTED,'attachment_upload':{'image_path'}}
  if len(actions)!=51:raise ValueError('operation_count_changed')
  with(stage/'docs/操作参数索引.csv').open('w',encoding='utf-8-sig',newline='')as f:
   w=csv.writer(f);w.writerow(['操作名','允许业务参数','共同规则'])
   for action,fields in sorted(actions.items()):
    rule='外层唯一request_id；金额/ID字符串；修改删除用最新version；条件必填字段以Skill/预览为准'
    if action=='refund_update':rule+='；必填object_id、expected_version、account_id、amount、time'
    w.writerow([action,','.join(sorted(fields)),rule])
  (stage/'00-先看这里.txt').write_text(f'钱迹Agent {v} 本机交付包\n\n先读README.md、skills/qianji-bookkeeping/SKILL.md和docs/本机收尾交付说明.txt。\n用户先登录官方App；工具后台记账，不负责获取账单、不改App或账号。\n{tool_count}个入口、51操作不等于48组全场景通过；当前实际验收层次和限制见矩阵及验收摘要。\n跨机与云端需单独验证；实际本机验收及当前边界见README与验收摘要。\n离线校验：python3 tools/verify_delivery.py .\n',encoding='utf-8')
  manifest={'version':v,'files':[{'path':p.relative_to(stage).as_posix(),'size':p.stat().st_size,'sha256':sha(p)}for p in sorted(stage.rglob('*'))if p.is_file()]}
  (stage/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
  (stage/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(stage).as_posix()}\n'for p in sorted(stage.rglob('*'))if p.is_file()))
  if out.exists():raise FileExistsError('delivery_exists')
  stage.rename(out)
  with archive.open('xb')as target,zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED)as z:
   for p in sorted(out.rglob('*')):
    if p.is_file():z.write(p,out.name+'/'+p.relative_to(out).as_posix())
  with archive.with_suffix('.zip.sha256').open('x')as f:f.write(f'{sha(archive)}  {archive.name}\n')
  return out
 finally:
  if stage.exists():shutil.rmtree(stage)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output-parent',type=Path);a=p.parse_args();print(build_bundle(a.project_root,a.output_parent or a.project_root.parent/'delivery'))
