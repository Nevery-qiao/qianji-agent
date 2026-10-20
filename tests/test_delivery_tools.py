import hashlib,importlib.util,json,tempfile,unittest,zipfile
from pathlib import Path

def tool(name):
 spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/'tools'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class DeliveryToolsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'project';self.root.mkdir();r=self.root
  for d in ('dist','docs','skills/qianji-bookkeeping','tools','evidence'):(r/d).mkdir(parents=True)
  (r/'pyproject.toml').write_text('[project]\nversion="9.8.7"\n[tool.setuptools.data-files]\n"share/docs"=["README.md","docs/matrix.csv","docs/local-closeout.json"]\n')
  (r/'README.md').write_text('See [matrix](docs/matrix.csv).');(r/'requirements.lock.txt').write_text('example==1\n');(r/'skills/qianji-bookkeeping/SKILL.md').write_text('public skill');(r/'tools/verify_delivery.py').write_text('# verifier')
  (r/'docs/matrix.csv').write_text('编号,本机状态\n'+''.join(f'G{i},partial\n'for i in range(48)))
  (r/'docs/local-closeout.json').write_text(json.dumps({'version':'9.8.7','mcp_tools':10,'open_operations':51,'original_scope_groups':48,'whole_scope_complete':False,'cross_machine_tested':False,'github_published':False}))
  (r/'evidence/secret.txt').write_text('DO_NOT_PACKAGE_PRIVATE')
  with zipfile.ZipFile(r/'dist/qianji_agent-9.8.7-py3-none-any.whl','w')as z:z.writestr('qianji_agent-9.8.7.dist-info/METADATA','Metadata-Version: 2.1\nName: qianji-agent\nVersion: 9.8.7\n')
  with zipfile.ZipFile(r/'dist/qianji-agent-9.8.7-source.zip','w')as z:z.writestr('qianji-agent-9.8.7/pyproject.toml',(r/'pyproject.toml').read_bytes())
 def build(self):return tool('build_delivery').build_bundle(self.root,self.root.parent/'delivery',matrix='docs/matrix.csv',summary='docs/local-closeout.json')
 def test_dynamic_version_allowlist_and_offline_verification(self):
  out=self.build();self.assertEqual(out.name,'qianji-agent-9.8.7');report=tool('verify_delivery').verify_bundle(out)
  self.assertTrue(report['manifest_and_all_hashes_verified']);self.assertEqual(report['version'],'9.8.7');self.assertFalse((out/'evidence').exists());self.assertFalse(any(b'DO_NOT_PACKAGE_PRIVATE'in p.read_bytes()for p in out.rglob('*')if p.is_file()))
 def test_handoff_lead_uses_current_summary_tool_count(self):
  out=self.build();self.assertIn('10个入口',(out/'00-先看这里.txt').read_text());self.assertNotIn('6个入口',(out/'00-先看这里.txt').read_text())
 def test_existing_bundle_never_overwritten(self):
  out=self.build();before=(out/'MANIFEST.json').read_bytes()
  with self.assertRaises(FileExistsError):self.build()
  self.assertEqual((out/'MANIFEST.json').read_bytes(),before)
 def test_tamper_refused(self):
  out=self.build();(out/'requirements.lock.txt').write_text('tampered')
  with self.assertRaises(ValueError):tool('verify_delivery').verify_bundle(out)
 def test_wrong_package_version_refused_without_publishing_directory(self):
  with zipfile.ZipFile(self.root/'dist/qianji_agent-9.8.7-py3-none-any.whl','w')as z:z.writestr('wrong.dist-info/METADATA','Version: 1.0\n')
  with self.assertRaises(ValueError):self.build()
  self.assertFalse((self.root.parent/'delivery/qianji-agent-9.8.7').exists())

 def test_public_repository_guides_are_copied_and_private_root_files_are_refused(self):
  for name in ('CONTRIBUTING.md','SECURITY.md','LICENSE'):
   (self.root/name).write_text('public guide')
  with (self.root/'pyproject.toml').open('a')as f:f.write('"share/project"=["CONTRIBUTING.md","SECURITY.md","LICENSE"]\n')
  out=self.build()
  for name in ('CONTRIBUTING.md','SECURITY.md','LICENSE'):self.assertEqual((out/name).read_text(),'public guide')
  self.assertTrue(tool('verify_delivery').verify_bundle(out)['manifest_and_all_hashes_verified'])
 def test_unapproved_root_data_file_is_still_refused(self):
  (self.root/'.env').write_text('SECRET_DO_NOT_INCLUDE')
  with (self.root/'pyproject.toml').open('a')as f:f.write('"share/private"=[".env"]\n')
  with self.assertRaisesRegex(ValueError,'non_public_data_file'):self.build()
