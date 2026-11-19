"""El inicio automático y la reanudación no deben desplegar el centro."""
from ctypes import addressof, wintypes
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QCursor
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
import windows_glass


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
    from live_reload import LiveReload

    sources = Path(temporary) / 'recarga'
    sources.mkdir()
    entry = sources / 'ciceron.pyw'
    entry.write_text('pass\n', encoding='utf-8')
    reload_check = LiveReload(sources, app)
    restarted = Mock()
    reload_check.restart.connect(restarted)
    with patch.object(reload_check, 'scan', side_effect=[PermissionError(), 'nueva revisión']):
        reload_check.check()
        assert reload_check.timer.isActive()
        QTest.qWait(850)
        restarted.assert_called_once()
    reload_check.deleteLater()
    with patch.object(Path, 'open', side_effect=[PermissionError(), Mock()]) as open_lock:
        with patch.object(module.time, 'sleep'):
            assert module.open_source_session(Path(temporary)) is not None
        assert open_lock.call_count == 2
    module.write(module.CONFIG, dict(module.DEFAULT, show_timer=False, guardian=False,
                                     open_center_on_start=True))

    assert module.startup_target('"C:\\Program Files\\Ciceron\\Ciceron.exe" --inicio-silencioso') == (
        'C:\\Program Files\\Ciceron\\Ciceron.exe')
    assert module.startup_target('"C:\\Program Files\\Ciceron\\Ciceron.exe') is None

    def mark_taskbar(hwnd, name, size):
        name.value = 'Shell_TrayWnd'
        return True

    with patch.object(windows_glass, 'client_bounds', return_value=(100, 200, 160, 24)), \
            patch.object(windows_glass, 'window_at', return_value=20), \
            patch.object(windows_glass, 'root_window', return_value=30), \
            patch.object(windows_glass, 'window_class', side_effect=mark_taskbar), \
            patch.object(windows_glass, 'set_window_pos') as raise_count:
        windows_glass.restore_above_taskbar(10)
        raise_count.assert_called_once_with(10, -1, 0, 0, 0, 0, 0x0013)

    with patch.object(module.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=True):
        controller = module.App()
    app.processEvents()
    assert controller.dock.isVisible()
    assert controller.dock.panel is None
    assert controller.dock.pending_panel is None
    assert controller.dock.progress == 0.0
    assert not controller.window.isVisible()

    with patch.object(module, 'restore_above_taskbar') as restore_stacking:
        controller.count.show()
        app.processEvents()
        assert (controller.count.isVisible() and controller.count._stacking_check.isActive()
                and controller.count._stacking_monitor.isActive())
        timer_geometry = controller.count.geometry()
        controller.tray_clicked(module.QSystemTrayIcon.ActivationReason.Trigger)
        assert controller.count._stacking_check.isActive()
        QTest.qWait(220)
        assert not controller.count._stacking_check.isActive()
        assert restore_stacking.call_count == 1
        QTest.qWait(controller.count.STACKING_RECHECK_MS - 220 + 40)
        assert restore_stacking.call_count >= 2
        for _ in range(30):
            app.processEvents()
            if controller.dock.panel is not None:
                break
            QTest.qWait(20)
        QTest.qWait(200)
        assert restore_stacking.call_count >= 2
        controller.count.hide()
        assert not controller.count._stacking_check.isActive()
        assert not controller.count._stacking_monitor.isActive()
        controller.count.show()
        assert controller.count._stacking_monitor.isActive()
        previous_show_timer = controller.cfg['show_timer']
        previous_target = controller.cfg['target']
        controller.cfg['show_timer'] = True
        controller.cfg['target'] = (module.dt.datetime.now() + module.dt.timedelta(minutes=2)).isoformat(
            timespec='minutes')
        controller._count_fits = True
        controller._count_hidden_by_layout = False
        with patch.object(controller, 'tick'):
            controller.count.hide()
            controller.count_visibility_changed()
            assert controller.count.isVisible(), 'El contador debe recuperarse si Windows lo oculta.'
        controller.cfg['show_timer'] = previous_show_timer
        controller.cfg['target'] = previous_target
    assert controller.dock.panel is not None
    assert controller.dock.panel.key == 'settings'
    assert controller.count._stacking_check.isActive()
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

    from edge_dock import PanelMousePress

    dock = controller.dock
    panel = dock.panel
    press = wintypes.MSG()
    press.message = PanelMousePress.MESSAGE
    press.wParam = 100
    press.lParam = dock.panel_session - 1
    with patch('edge_dock.window_belongs_to', side_effect=lambda target, owner: target == owner):
        assert dock.nativeEvent(b'windows_generic_MSG', addressof(press)) == (True, 0)
        app.processEvents()
        assert dock.panel is panel

        press.lParam = dock.panel_session
        for internal in (int(dock.winId()), int(panel.winId())):
            press.wParam = internal
            dock.nativeEvent(b'windows_generic_MSG', addressof(press))
            app.processEvents()
            assert dock.panel is panel

        press.wParam = 100
        with patch.object(dock, 'tray_geometry', return_value=QRect(QCursor.pos(), QCursor.pos())):
            dock.nativeEvent(b'windows_generic_MSG', addressof(press))
            app.processEvents()
            assert dock.panel is panel
        dock.nativeEvent(b'windows_generic_MSG', addressof(press))
        app.processEvents()
        assert dock.panel is None and dock.progress == 0.0 and dock.handle.isVisible()
        assert not controller.window.isVisible() and dock.panel_mouse_press.receiver is None

    controller.open_center()
    QTest.qWait(300)
    assert dock.panel is not None and dock.panel.key == 'settings'

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

    from focus_alert import FocusAlert
    snapshot = QImage(650, 400, QImage.Format.Format_RGBX8888)
    snapshot.fill(0xff181921)
    for x in range(300, 350):
        for y in range(400):
            snapshot.setPixel(x, y, 0xffccb98a)
    controller.cfg.update(show_timer=True, guardian=True, words='distractora',
                          target=(module.dt.datetime.now() + module.dt.timedelta(minutes=10)).isoformat())
    controller.last_poll = float('-inf')
    with patch.object(module, 'foreground', return_value='Ventana distractora'), \
            patch('focus_alert.capture_screen', return_value=snapshot) as capture:
        controller.tick()
        app.processEvents()
        alert = controller.alert
        assert isinstance(alert, FocusAlert) and alert.isVisible()
        assert alert.geometry() == alert.screen_to_cover.geometry()
        assert (alert.card.geometry().center() - alert.rect().center()).manhattanLength() <= 2
        rendered = alert.grab().toImage()
        card = alert.card.geometry()
        corner = card.topLeft() + QPoint(2, 2)
        outside = corner - QPoint(0, 4)
        inside = corner + QPoint(34, 8)
        assert rendered.pixelColor(corner) == rendered.pixelColor(outside)
        assert rendered.pixelColor(inside).red() > rendered.pixelColor(outside).red() + 60
        light, heavy = alert.backdrop, alert.card_backdrop
        assert light.pixelColor(light.width() // 2, 1).red() > heavy.pixelColor(heavy.width() // 2, 1).red()

        assert alert.countdown.text() == '00:10:00' and '#980e29' in alert.countdown.styleSheet()
        assert alert.refresh_timer.isActive() and alert.refresh_timer.interval() == 1000
        assert alert.refresh_timer.timerType() == Qt.TimerType.PreciseTimer
        QTest.qWait(1150)
        assert alert.countdown.text() == '00:09:59' and alert.countdown.isVisible()
        assert capture.call_count == 1
        close, = alert.findChildren(QPushButton)
        assert close.text() == 'Cerrar'
        QTest.mouseClick(close, Qt.MouseButton.LeftButton)
        assert controller.alert is None and controller.cfg['guardian']
        assert not alert.refresh_timer.isActive() and capture.call_count == 1
        controller.last_alert = controller.last_poll = float('-inf')
        controller.cfg['target'] = (module.dt.datetime.now() + module.dt.timedelta(seconds=15)).isoformat()
        controller.tick()
        assert controller.alert.countdown.text() == '00:00:15'
        controller.cfg['guardian'] = False
        controller.tick()
        assert controller.alert is None and not controller.cfg['guardian']
    controller.cfg['show_timer'] = False
    controller.tick()
    close_controller(controller)

    module.CONFIG.unlink()
    with patch.object(module.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False):
        controller = module.App()
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
