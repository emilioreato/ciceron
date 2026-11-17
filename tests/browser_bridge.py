import importlib.util, io, json, os, struct, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'src'/'browser_bridge.py'
spec=importlib.util.spec_from_file_location('browser_bridge_test',SOURCE)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class BridgeTests(unittest.TestCase):
 def test_open_center_from_sibling_installation(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
   root=Path(folder); executable=root/'Ciceron.exe'
   with patch.object(m.sys,'executable',str(root/'CiceronHost-test.exe')), patch.object(m.subprocess,'Popen') as launch:
    self.assertFalse(m.open_ciceron())
    launch.assert_not_called()
    executable.touch()
    self.assertTrue(m.open_ciceron())
    self.assertEqual(launch.call_args.args,([str(executable),'--abrir'],))
    self.assertEqual(launch.call_args.kwargs['cwd'],root)
    self.assertEqual(launch.call_args.kwargs['stdin'],subprocess.DEVNULL)
    launch.side_effect=OSError()
    self.assertFalse(m.open_ciceron())

 def test_protocol_unicode_and_partial(self):
  b=io.BytesIO(); m.send_message(b,{'hola':'mañana'}); b.seek(0); self.assertEqual(m.read_message(b),{'hola':'mañana'})
  for data in (b'\x01',struct.pack('<I',100)+b'{}',struct.pack('<I',m.LIMIT+1)):
   with self.assertRaises(ValueError): m.read_message(io.BytesIO(data))
 def test_selectors_are_bounded_and_sanitized(self):
  self.assertEqual(m.validate({'enabled':None,'x_selectors':[' .foo ','.foo']}),{'enabled':None,'x_selectors':['.foo']})
  for item in ('x{display:none}', 'a;body', 'x\ny', '@import', 'x'*301):
   with self.assertRaises(ValueError): m.validate({'enabled':True,'x_selectors':[item]})
  with self.assertRaises(ValueError): m.validate({'enabled':1})
 def test_atomic_policy_and_host_disconnect(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
   env=os.environ.copy(); env['APPDATA']=folder
   p=subprocess.Popen([sys.executable,str(SOURCE)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
   try:
    m.send_message(p.stdin,{'type':'hello','browser':'Brave'})
    first=m.read_message(p.stdout); self.assertEqual(first,{'type':'policy','policy':m.DEFAULT})
    data=Path(folder)/'GanaLaBatalla'; data.mkdir(exist_ok=True)
    (data/'navegador.json').write_text(json.dumps({'enabled':False,'x_selectors':['aside']}),encoding='utf-8')
    second=m.read_message(p.stdout); self.assertFalse(second['policy']['enabled']); self.assertEqual(second['policy']['x_selectors'],['aside'])
    p.stdin.close(); self.assertEqual(p.wait(timeout=8),0)
   finally:
    if p.poll() is None: p.kill(); p.wait()
    p.stdout.close(); p.stderr.close()

if __name__=='__main__': unittest.main()
