"""Build a public source archive from an explicit allowlist; no evidence/session data."""
from pathlib import Path
import hashlib,json,tomllib,zipfile
root=Path(__file__).resolve().parents[1]
project=tomllib.loads((root/'pyproject.toml').read_text());version=project['project']['version']
files=set(root.glob('qianji_agent/*.py'))|set(root.glob('qianji_agent/profiles/*.json'))|set(root.glob('tests/*.py'))
files|={root/'qianji_agent/capabilities.json',root/'pyproject.toml',root/'requirements.lock.txt',root/'tools/build_capabilities.py',root/'tools/build_release.py',root/'tools/build_delivery.py',root/'tools/verify_delivery.py'}
for paths in project['tool']['setuptools']['data-files'].values():files.update(root/p for p in paths)
files|={root/name for name in ('.gitignore','CONTRIBUTING.md','SECURITY.md','LICENSE') if (root/name).is_file()}
manifest=[]
for path in sorted(files):
 if path.is_symlink() or not path.is_file():raise RuntimeError('public_file_missing_or_symlink')
 manifest.append({'path':str(path.relative_to(root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
output=root/'dist'/f'qianji-agent-{version}-source.zip';output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
 for path in sorted(files):archive.write(path,f'qianji-agent-{version}/'+str(path.relative_to(root)))
 archive.writestr(f'qianji-agent-{version}/MANIFEST.public.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'public_files':len(manifest),'archive':output.name,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
