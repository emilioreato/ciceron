"""Aisla el Registro para comprobar la casilla de inicio de Cicerón."""
import importlib.machinery, importlib.util, os, sys, tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

with tempfile.TemporaryDirectory() as tmp:
    os.environ['APPDATA'] = tmp
    os.environ['LOCALAPPDATA'] = tmp
    path = Path(__file__).resolve().parents[1] / 'src' / 'ciceron.pyw'
    loader = importlib.machinery.SourceFileLoader('ciceron_prueba', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    module.write(module.CONFIG, dict(module.DEFAULT, show_timer=False, guardian=False))
    app = module.QApplication([]); app.setQuitOnLastWindowClosed(False)
    controller = module.App()

    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Registry:
        HKEY_CURRENT_USER = 1; KEY_QUERY_VALUE = 1; KEY_SET_VALUE = 2; REG_SZ = 1; REG_EXPAND_SZ = 2
        current = None; writes = []
        def OpenKey(self, *args): return Key()
        def QueryValueEx(self, *args):
            if self.current is None: raise FileNotFoundError()
            return self.current
        def SetValueEx(self, key, name, reserved, kind, value):
            self.writes.append(('set', value)); self.current = (value, kind)
        def DeleteValue(self, key, name):
            self.writes.append(('delete',)); self.current = None
    registry = Registry(); module.winreg = registry
    warnings = []
    module.QMessageBox.warning = lambda *args: warnings.append(args[-1])
    original_executable = sys.executable
    installed = str(Path(tmp) / 'GanaLaBatalla' / 'Ciceron.exe')
    try:
        def interact(enable, change=None, enabled=True):
            def answer():
                dialog = app.activeModalWidget()
                assert dialog is not None
                boxes = [b for b in dialog.findChildren(module.QCheckBox) if 'iniciar sesión' in b.text()]
                assert len(boxes) == 1 and boxes[0].isEnabled() == enabled
                if enabled: boxes[0].setChecked(enable)
                if change is not None: registry.current = change
                dialog.accept()
            module.QTimer.singleShot(50, answer)
            controller.options()

        # A standalone or development executable must not take ownership of startup.
        sys.frozen = True; sys.executable = str(Path(tmp) / 'otra-copia.exe')
        interact(True, enabled=False)
        assert registry.current is None and not registry.writes
        # A concurrent third-party change must never be overwritten.
        sys.executable = installed
        other = (str(Path(tmp) / 'otro.exe'), registry.REG_SZ)
        interact(True, change=other)
        assert registry.current == other and not registry.writes and warnings
        # The installed app can turn its own entry on and off.
        registry.current = None; warnings.clear()
        interact(True)
        assert registry.current == ('"' + installed + '"', registry.REG_SZ)
        interact(False)
        assert registry.current is None
        registry.current = ('"%LOCALAPPDATA%\\GanaLaBatalla\\Ciceron.exe"', registry.REG_EXPAND_SZ)
        interact(False)
        assert registry.current is None
        print('Inicio: copia externa, concurrencia, rutas expandibles y activación/desactivación verificados')
    finally:
        sys.executable = original_executable
        if hasattr(sys, 'frozen'): del sys.frozen
        controller.tray.hide(); controller.window.close(); controller.count.close()
