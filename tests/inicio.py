"""Aisla el Registro para comprobar la casilla de inicio de Cicerón."""
import importlib.machinery, importlib.util, os, sys, tempfile
from pathlib import Path
import sys
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from app_identity import AppIdentity, BIRTHDAY_PACKAGE, file_icon_reference, resource_icon
from birthday_host import BirthdayHost
from start_menu import StartMenuApps

with tempfile.TemporaryDirectory() as tmp:
    os.environ['APPDATA'] = tmp
    os.environ['LOCALAPPDATA'] = tmp
    os.environ['CICERON_HOME'] = str(Path(tmp) / 'Aplicacion')
    path = Path(__file__).resolve().parents[1] / 'src' / 'ciceron.pyw'
    loader = importlib.machinery.SourceFileLoader('ciceron_prueba', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    module.write(module.CONFIG, dict(module.DEFAULT, show_timer=False, guardian=False))
    app = module.QApplication([]); app.setQuitOnLastWindowClosed(False)
    with patch.object(module.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=True):
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
    installed = str(Path(tmp) / 'Aplicacion' / 'Ciceron.exe')
    try:
        def interact(enable, change=None, enabled=True):
            def answer():
                dialog = app.activeModalWidget()
                assert dialog is not None
                boxes = [b for b in dialog.findChildren(module.QCheckBox) if 'minimizado con Windows' in b.text()]
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
        assert registry.current == other and not registry.writes and warnings, (registry.current, registry.writes, warnings)
        # The installed app can turn its own entry on and off.
        registry.current = None; warnings.clear()
        interact(True)
        assert registry.current == (module.startup_command(installed), registry.REG_SZ)
        registry.current = ('"' + installed + '"', registry.REG_SZ)
        interact(True)
        assert registry.current == (module.startup_command(installed), registry.REG_SZ)
        interact(False)
        assert registry.current is None
        registry.current = (module.startup_command(installed), registry.REG_SZ)
        interact(False)
        assert registry.current is None
        registry.current = ('"%CICERON_HOME%\\Ciceron.exe"', registry.REG_EXPAND_SZ)
        interact(False)
        assert registry.current is None
        print('Inicio: copia externa, concurrencia, rutas expandibles y activación/desactivación verificados')

        # Write a real Windows shortcut under the temporary profile.
        launcher = Path(installed)
        launcher.parent.mkdir(exist_ok=True)
        launcher.touch()
        script = launcher.with_name('cumpleaños.pyw')
        script.touch()
        png = script.with_suffix('.png')
        from PySide6.QtGui import QColor, QImage
        image = QImage(32, 32, QImage.Format.Format_ARGB32)
        image.fill(QColor('#6754a5'))
        assert image.save(str(png))
        item = dict(name='Happy Birthday', path=str(script), icon=str(png),
                    package=dict(id=BIRTHDAY_PACKAGE, name='Happy Birthday', tags=['cumpleaños']))
        identity = AppIdentity.from_entry(item, {BIRTHDAY_PACKAGE: ['Familia']})
        assert identity.tags == ('Familia',)
        assert AppIdentity.from_entry(item).tags == ('cumpleaños',)
        assert identity.notification_title == 'Cicerón · Happy Birthday'
        shortcuts = StartMenuApps(Path(tmp) / 'Inicio de prueba', launcher)
        with patch('start_menu.development_mode', return_value=False):
            shortcuts.update(item, list(identity.tags))
            shortcuts.update(item, [], previous=item)
        path, = shortcuts.folder.glob('*.lnk')
        link = shortcuts.shell().CreateShortcut(str(path))
        assert Path(link.TargetPath) == launcher
        assert link.Arguments == f'--lanzar-paquete {BIRTHDAY_PACKAGE}'
        ico = Path(link.IconLocation.rsplit(',', 1)[0])
        assert ico.suffix == '.ico' and QImage(str(ico)).pixelColor(16, 16) == QColor('#6754a5')
        print('Inicio: icono PNG de paquete convertido y apertura por ID estable verificadas')

        source_link = launcher.with_name('Acceso personal.lnk')
        file_link = shortcuts.shell().CreateShortcut(str(source_link))
        file_link.TargetPath = str(launcher)
        file_link.IconLocation = f'{ico},0'
        file_link.Save()
        assert file_icon_reference(source_link) == (ico, 0)
        assert not resource_icon(ico, 0, ico.stat().st_mtime_ns).isNull()
        entry = dict(name='Acceso personal', path=str(source_link), tags=['Agenda personal'])
        with patch('start_menu.development_mode', return_value=False):
            shortcuts.update(entry, entry['tags'])
        copied = shortcuts.shell().CreateShortcut(str(shortcuts.folder / source_link.name))
        assert Path(copied.IconLocation.rsplit(',', 1)[0]) == ico
        from comtypes.client import CreateObject
        namespace = CreateObject('Shell.Application', dynamic=True).NameSpace(str(shortcuts.folder))
        assert 'Agenda personal' in namespace.ParseName(source_link.name).ExtendedProperty('System.Keywords')

        host = BirthdayHost(controller, item)
        host.agenda = Mock(path=Path(tmp) / 'cumpleanos.json')
        acknowledged = Mock()
        with patch('birthday_host.agenda_module') as agenda, patch('birthday_host.set_window_identity') as set_identity:
            tray = agenda.return_value.Tray.return_value
            assert host.show('Cumpleaños de hoy', 'Ejemplo', acknowledged)
            icon = agenda.return_value.Tray.call_args.args[2]
            assert icon.name == ico.name and agenda.return_value.Tray.call_args.kwargs['hidden']
            set_identity.assert_called_once_with(tray.hwnd, identity.windows_id)
            tray.show.assert_called_once_with('Cicerón · Happy Birthday', 'Cumpleaños de hoy\nEjemplo', acknowledged)
            renamed = dict(item, package=dict(item['package'], name='Agenda'))
            host.update_entry(renamed)
            assert host.notification_tray is None and host.agenda is not None
            tray.close.assert_called_once()
            host.show('Agenda', 'Ejemplo', acknowledged)
            tray.show.assert_called_with('Cicerón · Agenda', 'Ejemplo', acknowledged)
        print('Avisos: identidad e icono del paquete enviados sin pedir un icono visible en la bandeja')
    finally:
        sys.executable = original_executable
        if hasattr(sys, 'frozen'): del sys.frozen
        controller.tray.hide(); controller.window.close(); controller.count.close()
