"""Isolated subprocess fixture. No auth, network or official App access."""
import sys,os
from pathlib import Path
sys.path.insert(0,os.environ.get('QIANJI_TEST_PACKAGE_ROOT',str(Path(__file__).resolve().parents[1])))
sys.path.insert(0,str(Path(__file__).parent))
from test_account_review import FullBackend
from qianji_agent.codec import dumps,loads
from qianji_agent.engine import Engine
from qianji_agent.server import build_server

class FileBackend(FullBackend):
 def __init__(self,root):
  super().__init__();self.root=Path(root)
 def read(self,route,params):
  self.data=loads((self.root/'native.json').read_text());return super().read(route,params)
 def write(self,route,params):
  self.data=loads((self.root/'native.json').read_text());result=super().write(route,params)
  (self.root/'native.json').write_text(dumps(self.data))
  with (self.root/'dispatch.log').open('a') as f:f.write('synthetic-dispatch\n')
  return result

if __name__=='__main__':
 import qianji_agent
 root=Path(sys.argv[1])
 with(root/'runtime-files.log').open('a')as f:f.write(str(Path(qianji_agent.__file__).resolve())+'\n')
 build_server(Engine(FileBackend(root),'123',root/'journal')).run(transport='stdio')
