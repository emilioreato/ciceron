"""El inicio automático y la reanudación no deben desplegar el centro."""
from ctypes import addressof, wintypes
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtTest import QTest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))


def load_module(profile):
    os.environ['APPDATA'] = profile
    os.environ['LOCALAPPDATA'] = profile
    os.environ['CICERON_HOME'] = str(Path(profile) / 'Aplicacion')
    path = root / 'src' / 'ciceron.pyw'
    loader = importlib.machinery.SourceFileLoader('ciceron_arranque', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def close_controller(controller):
    controller.tray.hide()
    if controller.dock is not None:
        controller.dock.shutdown()
    controller.window.close()
    controller.count.close()


with TemporaryDirectory() as temporary:
    module = load_module(temporary)
    app = module.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    module.write(module.CONFIG, dict(module.DEFAULT, show_timer=False, guardian=False,
                                     open_center_on_start=True))

    assert module.silent_start_requested(['Ciceron.exe', module.STARTUP_ARGUMENT])
    assert not module.silent_start_requested(['Ciceron.exe', '--abrir'])
    assert not module.silent_start_requested(['Ciceron.exe', '--alternar-centro'])
    assert not module.silent_start_requested(
        ['Ciceron.exe', module.STARTUP_ARGUMENT, '--abrir'])
    assert module.startup_target('"C:\\Program Files\\Ciceron\\Ciceron.exe" --inicio-silencioso') == (
        'C:\\Program Files\\Ciceron\\Ciceron.exe')
    assert module.startup_target('"C:\\Program Files\\Ciceron\\Ciceron.exe') is None

    with patch.object(module.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=True):
        controller = module.App(suppress_implicit_open=True)
    app.processEvents()
    assert controller.dock.isVisible()
    assert controller.dock.panel is None
    assert controller.dock.pending_panel is None
    assert controller.dock.progress == 0.0
    assert not controller.window.isVisible()

    with patch.object(module, 'restore_above_taskbar') as restore_stacking:
        controller.count.show()
        app.processEvents()
        assert controller.count.isVisible() and controller.count._stacking_check.isActive()
        timer_geometry = controller.count.geometry()
        controller.tray_clicked(module.QSystemTrayIcon.ActivationReason.Trigger)
        assert controller.count._stacking_check.isActive()
        QTest.qWait(220)
        assert not controller.count._stacking_check.isActive()
        assert restore_stacking.call_count == 1
        for _ in range(30):
            app.processEvents()
            if controller.dock.panel is not None:
                break
            QTest.qWait(20)
        QTest.qWait(200)
        assert restore_stacking.call_count == 1
    assert controller.dock.panel is not None
    assert controller.dock.panel.key == 'settings'
    assert not controller.count._stacking_check.isActive()
    assert controller.count.isVisible()
    assert controller.count.geometry() == timer_geometry

    controller.tray_clicked(module.QSystemTrayIcon.ActivationReason.Trigger)
    app.processEvents()
    assert controller.dock.panel is None
    assert controller.dock.progress == 0.0
    assert not controller.window.isVisible()
    assert controller.count.isVisible() and controller.count.geometry() == timer_geometry

    controller.tray_clicked(module.QSystemTrayIcon.ActivationReason.Trigger)
    for _ in range(30):
        app.processEvents()
        if controller.dock.panel is not None:
            break
        QTest.qWait(20)
    assert controller.dock.panel is not None
    assert controller.dock.panel.key == 'settings'
    controller.tray_clicked(module.QSystemTrayIcon.ActivationReason.DoubleClick)
    assert controller.dock.panel is not None and controller.dock.panel.key == 'settings'

    power_filter = module.SuspendResumeFilter(controller)
    message = wintypes.MSG()
    message.message = power_filter.WM_POWERBROADCAST
    message.wParam = power_filter.PBT_APMSUSPEND
    assert power_filter.nativeEventFilter(b'windows_generic_MSG', addressof(message)) == (False, 0)
    app.processEvents()
    assert controller.dock.isVisible()
    assert controller.dock.panel is None
    assert controller.dock.progress == 0.0
    assert not controller.window.isVisible()

    controller.open_center()
    for _ in range(30):
        app.processEvents()
        if controller.dock.panel is not None:
            break
        QTest.qWait(20)
    assert controller.dock.panel is not None
    assert controller.dock.panel.key == 'settings'
    close_controller(controller)

    module.CONFIG.unlink()
    with patch.object(module.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False):
        controller = module.App(suppress_implicit_open=True)
    assert controller.dock.isVisible()
    assert controller.dock.panel is None
    assert not controller.window.isVisible()
    close_controller(controller)

    kernel = module.ctypes.windll.kernel32
    kernel.CreateEventW.argtypes = [module.ctypes.c_void_p, module.ctypes.c_int,
                                    module.ctypes.c_int, module.ctypes.c_wchar_p]
    kernel.CreateEventW.restype = module.ctypes.c_void_p
    kernel.CreateSemaphoreW.argtypes = [module.ctypes.c_void_p, module.ctypes.c_long,
                                        module.ctypes.c_long,
                                        module.ctypes.c_wchar_p]
    kernel.CreateSemaphoreW.restype = module.ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [module.ctypes.c_void_p, module.ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = module.ctypes.c_ulong
    kernel.SetEvent.argtypes = [module.ctypes.c_void_p]
    kernel.ReleaseSemaphore.argtypes = [module.ctypes.c_void_p, module.ctypes.c_long,
                                        module.ctypes.c_void_p]
    kernel.ReleaseSemaphore.restype = module.ctypes.c_int
    kernel.CloseHandle.argtypes = [module.ctypes.c_void_p]
    first_event = kernel.CreateEventW(None, False, False, None)
    toggle_event = kernel.CreateSemaphoreW(None, 0, 2147483647, None)
    assert first_event and toggle_event
    requests = []
    watcher = module.watch_activation_event(
        app, kernel, first_event, lambda: requests.append('open'),
        read_power=lambda: False,
        additional_events=((toggle_event, lambda: requests.append('toggle')),))
    assert kernel.ReleaseSemaphore(toggle_event, 2, None)
    QTest.qWait(260)
    assert requests == ['toggle', 'toggle']
    kernel.SetEvent(first_event)
    QTest.qWait(260)
    assert requests == ['toggle', 'toggle', 'open']
    watcher.stop()
    kernel.CloseHandle(toggle_event)
    kernel.CloseHandle(first_event)

    probe = Mock()
    resume_filter = module.SuspendResumeFilter(probe)
    message = wintypes.MSG()
    message.message = resume_filter.WM_POWERBROADCAST
    message.wParam = 0x0007  # PBT_APMRESUMESUSPEND follows user activity.
    resume_filter.nativeEventFilter(b'windows_generic_MSG', addressof(message))
    probe.prepare_for_power_transition.assert_not_called()
    message.wParam = resume_filter.PBT_APMRESUMEAUTOMATIC
    resume_filter.nativeEventFilter(b'windows_generic_MSG', addressof(message))
    probe.prepare_for_power_transition.assert_called_once_with()

    class FakeFunction:
        argtypes = None
        restype = None

        def __init__(self, result):
            self.result = result
            self.calls = []

        def __call__(self, *args):
            self.calls.append(args)
            return self.result

    user32 = Mock()
    user32.RegisterSuspendResumeNotification = FakeFunction(17)
    user32.UnregisterSuspendResumeNotification = FakeFunction(True)
    with patch.object(module.ctypes, 'WinDLL', return_value=user32):
        assert power_filter.register(123)
        power_filter.stop()
    assert len(user32.RegisterSuspendResumeNotification.calls) == 1
    assert len(user32.UnregisterSuspendResumeNotification.calls) == 1
    power_filter.stop()
    assert len(user32.UnregisterSuspendResumeNotification.calls) == 1

    print('Arranque: inicio silencioso, alternancia, suspensión, contador y liberación de notificación verificados')
