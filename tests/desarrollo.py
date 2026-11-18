"""Start two isolated source processes and verify the activation boundary."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CHILD = '''
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
from unittest.mock import patch
import app_paths
import browser_setup
from start_menu import StartMenuApps

dev = app_paths.development_mode()
profile = Path(os.environ['CICERON_HOME'])
if dev:
    assert app_paths.instance_suffix().startswith('_Dev_')
    with patch('browser_setup.winreg.CreateKeyEx') as registry, patch.object(StartMenuApps, 'shell') as shell:
        try:
            browser_setup.prepare('Chrome')
        except ValueError as error:
            assert 'desarrollo' in str(error)
        else:
            raise AssertionError('Desarrollo preparó el puente.')
        shortcuts = StartMenuApps(profile, profile / 'Ciceron.exe')
        shortcuts.update({}, [])
        shortcuts.remove({})
        assert not registry.called and not shell.called
else:
    assert app_paths.instance_suffix() == ''
    # Keep the test daily instance separate from the user's existing mutex.
    app_paths.instance_suffix = lambda: os.environ['CICERON_TEST_DAILY_SUFFIX']

loader = importlib.machinery.SourceFileLoader('test_center', str(Path.cwd() / 'src/ciceron.pyw'))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
original_init = module.App.__init__

def observe_start(self):
    original_init(self)
    self.timer.setInterval(80)
    self.timer.timeout.connect(lambda: module.QApplication.quit() if (profile / 'stop').exists() else None)
    if dev:
        self.cfg['title'] = 'Perfil de desarrollo'
        assert self.save()
    (profile / 'ready').touch()

def observe_activation(self):
    with (profile / 'activation').open('a', encoding='utf-8') as output:
        output.write('open\\n')

module.App.__init__ = observe_start
module.App.open_center = observe_activation
sys.exit(module.main())
'''


def wait_until(check, *processes):
    deadline = monotonic() + 12
    while not check() and monotonic() < deadline:
        for process in processes:
            assert process.poll() is None, process.returncode
        sleep(.05)
    assert check()


with TemporaryDirectory() as temporary:
    base = Path(temporary)
    paths = (base / 'Simulada diaria', base / 'Dev local')
    children = []
    try:
        for profile in paths:
            (profile / 'datos').mkdir(parents=True)
            (profile / 'datos/config.json').write_text('{"glass": false}', encoding='utf-8')
        arguments = [sys.executable, '-c', CHILD]
        marker = '_Prueba_' + uuid4().hex
        base_env = dict(os.environ, CICERON_DATA='', QT_QPA_PLATFORM='offscreen',
                        CICERON_TEST_DAILY_SUFFIX=marker, PYTHONPATH=str(ROOT / 'src'),
                        APPDATA=str(base / 'windows'), LOCALAPPDATA=str(base / 'local'))
        daily_env = dict(base_env, CICERON_DEV='', CICERON_HOME=str(paths[0]))
        dev_env = dict(base_env, CICERON_DEV='1', CICERON_HOME=str(paths[1]))
        daily = subprocess.Popen(arguments, cwd=ROOT, env=daily_env)
        children.append(daily)
        dev = subprocess.Popen(arguments, cwd=ROOT, env=dev_env)
        children.append(dev)
        wait_until(lambda: all((path / 'ready').is_file() for path in paths), daily, dev)
        before = [(path / 'activation').read_bytes() for path in paths]
        link = subprocess.run([*arguments, '--abrir'], cwd=ROOT, env=dev_env, timeout=12)
        assert link.returncode == 0
        wait_until(lambda: (paths[1] / 'activation').read_bytes() != before[1], daily, dev)
        assert (paths[0] / 'activation').read_bytes() == before[0]
        assert (paths[0] / 'datos/config.json').read_text(encoding='utf-8') == '{"glass": false}'
        assert 'Perfil de desarrollo' in (paths[1] / 'datos/config.json').read_text(encoding='utf-8')
    finally:
        for path in paths:
            (path / 'stop').touch()
        for process in children:
            try:
                assert process.wait(timeout=5) == 0
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait()
                raise
print('Desarrollo: dos instancias, activación separada y perfiles independientes verificados.')
