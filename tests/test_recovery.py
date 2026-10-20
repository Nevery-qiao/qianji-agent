import multiprocessing as mp,unittest,tempfile,shutil
from pathlib import Path
from test_engine import Backend
from test_business import expense
from qianji_agent.engine import Engine
from qianji_agent.codec import dumps,loads

def concurrent_worker(root,barrier,output):
 class FileBackend(Backend):
  def read(self,route,params):
   self.data=loads((Path(root)/'native.json').read_text());return super().read(route,params)
  def write(self,route,params):
   self.data=loads((Path(root)/'native.json').read_text());r=super().write(route,params)
   (Path(root)/'native.json').write_text(dumps(self.data))
   with (Path(root)/'dispatch.log').open('a') as f:f.write('dispatch\n')
   return r
 e=Engine(FileBackend(),'123',Path(root)/'state');barrier.wait(10)
 output.put(e.execute('same-order',expense())['state'])

class RecoveryTests(unittest.TestCase):
 def test_distinct_processes_share_one_dispatch_and_receipt(self):
  with tempfile.TemporaryDirectory() as root:
   (Path(root)/'native.json').write_text(dumps(Backend().data))
   ctx=mp.get_context('spawn');barrier=ctx.Barrier(2);output=ctx.Queue()
   workers=[ctx.Process(target=concurrent_worker,args=(root,barrier,output)) for _ in range(2)]
   for w in workers:w.start()
   for w in workers:
    w.join(20)
    if w.is_alive():w.terminate();w.join();self.fail('worker stalled')
    self.assertEqual(w.exitcode,0)
   self.assertEqual([output.get(timeout=2),output.get(timeout=2)],['verified','verified'])
   self.assertEqual((Path(root)/'dispatch.log').read_text().splitlines(),['dispatch'])
 def test_backup_restore_preserves_unknown_request_no_replay(self):
  with tempfile.TemporaryDirectory() as root:
   root=Path(root);b=Backend();e=Engine(b,'123',root/'old');plan=e.prepare(expense(),e.snapshot());plan.update(extended=False,owner='123')
   with e.journal.lock():e.journal.start('unknown','hash',plan)
   backup=root/'copy.sqlite3';e.journal.backup(backup)
   new=root/'restored';new.mkdir(mode=0o700);shutil.copy2(backup,new/'operations.sqlite3')
   restored=Engine(b,'123',new)
   self.assertEqual(restored.operation('unknown')['state'],'pending_verification')
   self.assertEqual(restored.execute('different',expense())['code'],'previous_result_unknown');self.assertEqual(b.writes,0)
   with self.assertRaises(ValueError):Engine(b,'different-owner',new)
