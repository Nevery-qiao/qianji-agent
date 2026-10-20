"""Offline verifier. Optional live private scan compares only in RAM."""
from pathlib import Path,PurePosixPath
import argparse,csv,hashlib,io,json,re,stat,tomllib,zipfile

def sha(data):return hashlib.sha256(data).hexdigest()
def require(test,code):
 if not test:raise ValueError(code)
def relative(name):
 p=PurePosixPath(name);require(not p.is_absolute()and '..'not in p.parts and '\\'not in name,'unsafe_archive_path');return p

def verify_bundle(out,private_values=()):
 out=Path(out).resolve();manifest=json.loads((out/'MANIFEST.json').read_text());v=manifest['version'];expected={}
 for row in manifest['files']:
  relative(row['path']);require(row['path']not in expected,'duplicate_manifest_entry');p=out/row['path']
  require(p.is_file()and not p.is_symlink(),'missing_or_symlink');data=p.read_bytes();require(len(data)==row['size']and sha(data)==row['sha256'],'file_hash_mismatch');expected[row['path']]=data
 require(not any(p.is_symlink()for p in out.rglob('*')),'symlink_in_bundle')
 require({p.relative_to(out).as_posix()for p in out.rglob('*')if p.is_file()}==set(expected)|{'MANIFEST.json','SHA256SUMS'},'extra_or_missing_file')
 checks={}
 for line in(out/'SHA256SUMS').read_text().splitlines():
  want,name=line.split('  ',1);relative(name);require(name not in checks,'duplicate_checksum');checks[name]=want;require(sha((out/name).read_bytes())==want,'checksum_mismatch')
 require(set(checks)==set(expected)|{'MANIFEST.json'},'checksum_coverage');scanned=0
 def scan(data,label,depth=0):
  nonlocal scanned
  require(depth<=3,'unexpected_archive_depth');scanned+=1;require(not any(x and x in data for x in private_values),'private_value_found')
  if label.endswith(('.zip','.whl')):
   with zipfile.ZipFile(io.BytesIO(data))as z:
    require(len(z.namelist())==len(set(z.namelist())),'duplicate_archive_entry')
    for info in z.infolist():
     p=relative(info.filename);require(not stat.S_ISLNK(info.external_attr>>16),'archive_symlink');require(not any(x in p.parts for x in ('evidence','.venv','__pycache__','.git','sources'))and not info.filename.endswith(('.sqlite3','.plist','.pyc','.env','.private.json')),'private_file_in_archive');scan(z.read(info),info.filename,depth+1)
 for name,data in expected.items():scan(data,name)
 with zipfile.ZipFile(io.BytesIO(expected[f'packages/qianji_agent-{v}-py3-none-any.whl']))as z:
  names=[n for n in z.namelist()if n.endswith('.dist-info/METADATA')];require(len(names)==1 and f'Version: {v}'in z.read(names[0]).decode().splitlines(),'wheel_version_mismatch')
 with zipfile.ZipFile(io.BytesIO(expected[f'packages/qianji-agent-{v}-source.zip']))as z:require(tomllib.loads(z.read(f'qianji-agent-{v}/pyproject.toml').decode())['project']['version']==v,'source_version_mismatch')
 with(out/'docs/操作参数索引.csv').open(encoding='utf-8-sig')as f:require(len(list(csv.DictReader(f)))==51,'operation_count')
 with(out/'docs/完整48组能力矩阵.csv').open(encoding='utf-8-sig')as f:require(len(list(csv.DictReader(f)))==48,'matrix_count')
 s=json.loads((out/'docs/验收摘要.json').read_text());require(s['version']==v and s['open_operations']==51 and s['whole_scope_complete']is False and s['cross_machine_tested']is False and s['github_published']is False,'summary_scope_mismatch')
 for path in out.rglob('*.md'):
  for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
   if link.startswith(('https:','http:','#')):continue
   target=(path.parent/link.split('#',1)[0]).resolve();require(target.is_relative_to(out)and target.is_file(),'broken_local_document_link')
 archive=out.parent/f'qianji-agent-{v}-delivery.zip'
 with zipfile.ZipFile(archive)as z:
  require(len(z.namelist())==len(set(z.namelist()))and set(z.namelist())=={out.name+'/'+n for n in set(expected)|{'MANIFEST.json','SHA256SUMS'}},'outer_archive_entries')
  for n in set(expected)|{'MANIFEST.json','SHA256SUMS'}:require(z.read(out.name+'/'+n)==(out/n).read_bytes(),'outer_archive_mismatch')
 want,name=archive.with_suffix('.zip.sha256').read_text().strip().split('  ',1);require(name==archive.name and sha(archive.read_bytes())==want,'outer_archive_checksum')
 return {'version':v,'manifest_and_all_hashes_verified':True,'nested_entries_scanned':scanned,'private_value_scan_requested':bool(private_values),'local_document_links_valid':True,'matrix_rows':48,'operations_rows':51,'delivery_zip_sha256':want}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('bundle',nargs='?',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--live-private-scan',action='store_true');a=p.parse_args();values=()
 if a.live_private_scan:
  from qianji_agent.auth import load_session
  s=load_session();values=tuple(x.encode()for x in (s.uid,s.headers['utoken'],s.headers['devid'],str(Path.home())))
 print(json.dumps(verify_bundle(a.bundle,values),ensure_ascii=False))
