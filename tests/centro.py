"""Exercise navigation and library changes against isolated user data."""
import importlib.machinery
import importlib.util
from ctypes import addressof, wintypes
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from PySide6.QtCore import QEvent, QPoint, QPointF
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtTest import QTest


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from windows_glass import energy_saver_active


def power_on_battery(pointer):
    status = pointer._obj
    status.ac = 0
    status.percentage = 45
    status.saving = saving
    return True


with patch('windows_glass.get_power', side_effect=power_on_battery):
    for saving in (0, 1):
        assert energy_saver_active() == bool(saving)


with TemporaryDirectory() as temporary:
    os.environ['APPDATA'] = os.environ['LOCALAPPDATA'] = temporary
    os.environ['CICERON_HOME'] = str(Path(temporary) / 'Aplicacion')
    loader = importlib.machinery.SourceFileLoader('ciceron_centro', str(root / 'src' / 'ciceron.pyw'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module.write(module.CONFIG, dict(module.DEFAULT, show_timer=False, glass=False))
    app = module.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with patch.object(module.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=True):
        center = module.App()
    kernel = module.ctypes.windll.kernel32
    kernel.CreateEventW.argtypes = [module.ctypes.c_void_p, module.ctypes.c_int, module.ctypes.c_int, module.ctypes.c_wchar_p]
    kernel.CreateEventW.restype = module.ctypes.c_void_p
    kernel.SetEvent.argtypes = [module.ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [module.ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [module.ctypes.c_void_p, module.ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = module.ctypes.c_ulong
    event = kernel.CreateEventW(None, False, False, None)
    assert event
    activated = []
    watcher = module.watch_activation_event(app, kernel, event, lambda: activated.append(True),
                                            read_power=lambda: False)
    assert not module.activation_event_signaled(kernel, event)
    kernel.SetEvent(event)
    QTest.qWait(350)
    assert activated == [True]
    assert not module.activation_event_signaled(kernel, event)
    watcher.stop()
    saving = module.watch_activation_event(app, kernel, event, lambda: None, read_power=lambda: True)
    assert saving.interval() == 1000
    saving.stop()
    kernel.CloseHandle(event)
    assert center.dock.isVisible() and center.dock.handle.isVisible()
    assert center.dock.panel is None and center.dock.progress == 0.0
    assert not center.timer.isActive()
    previous_cfg = center.cfg.copy()
    center.cfg.update(target=(module.dt.datetime.now() + module.dt.timedelta(hours=2)).isoformat(),
                      show_timer=True, guardian=True)
    with patch.object(module, 'foreground', return_value='Editor') as foreground:
        center.tick()
        assert center.timer.interval() == 5000
        center.set_background_power(True)
        assert 14000 <= center.timer.interval() <= 15000
        assert foreground.call_count == 1
    center.cfg = previous_cfg
    center.set_background_power(False)
    assert not center.timer.isActive()
    tray_actions = [action.text() for action in center.tray.contextMenu().actions()
                    if not action.isSeparator()]
    assert tray_actions == [
        'Ocultar barra lateral', 'Captura de pantalla · 20 segundos', 'Salir'
    ]
    center.glass_control.setChecked(True)
    center.update_tray_actions()
    center.photo_action.trigger()
    assert module.capture_mode() and center.photo_timer.interval() == 20000
    assert center.photo_timer.isActive()
    center.photo_timer.timeout.emit()
    assert not module.capture_mode() and not center.photo_timer.isActive()

    center.photo_action.trigger()
    center.capture_control.setChecked(False)
    center.update_tray_actions()
    assert not module.capture_mode() and app.property('capturePrivate')
    assert not center.photo_action.isEnabled() and not center.photo_timer.isActive()
    saved, _ = module.read(module.CONFIG, {})
    assert saved['include_in_captures'] is False
    center.capture_control.setChecked(True)
    center.update_tray_actions()
    assert not app.property('capturePrivate') and center.photo_action.isEnabled()
    center.glass_control.setChecked(False)
    assert center.dock_visibility_action.text() == 'Ocultar barra lateral'
    center.open_center()
    for _ in range(30):
        panel = center.dock.panel
        if panel is not None and panel.windowOpacity() == 1.0:
            break
        QTest.qWait(40)
    assert center.dock.panel.key == 'settings'
    assert set(center.page_ids) == {'general', 'settings', 'status'}
    assert center.import_button.parentWidget() is center.banner
    assert center.app_search.isHidden()

    for name, index in center.page_ids.items():
        center.nav.button(index).click()
        assert center.pages.currentIndex() == index, name

    center.select_page('settings')
    wheel_filter = center.wheel_filter
    msg = wintypes.MSG()
    msg.hWnd = 100
    with patch('edge_dock.root_window', side_effect=lambda handle, _: handle), \
            patch('edge_dock.foreground_window', side_effect=[200, 100]), \
            patch('edge_dock.is_external_window', side_effect=lambda handle: handle == 200), \
            patch('edge_dock.window_belongs_to', return_value=False), \
            patch('edge_dock.forward_wheel', return_value=True) as forward:
        msg.message = 0x0021  # click while the other app still owns focus
        assert wheel_filter.nativeEventFilter(b'windows_generic_MSG', addressof(msg)) == (False, 0)
        msg.message = 0x020A  # wheel over Ajustes while Cicerón has focus
        assert wheel_filter.nativeEventFilter(b'windows_generic_MSG', addressof(msg)) == (True, 0)
        assert forward.call_args.args[0::2] == (100, 200)
    theme = next(widget for widget in center.window.findChildren(module.QComboBox)
                 if widget.accessibleName() == 'Tema')
    theme.setCurrentIndex(theme.findData('dark'))
    assert center.window.dark
    assert module.read(module.CONFIG, {})[0]['theme'] == 'dark'
    assert not any(btn.text() == 'Aplicaciones instaladas de Windows'
                   for btn in center.window.findChildren(module.QPushButton))
    center.select_page('status')
    app.processEvents()
    page = center.pages.currentWidget()
    bar = page.verticalScrollBar()
    assert bar.maximum() > 0
    wheel = QWheelEvent(QPointF(10, 10), QPointF(), QPoint(), QPoint(0, -120),
                        module.Qt.MouseButton.NoButton, module.Qt.KeyboardModifier.NoModifier,
                        module.Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(page.viewport(), wheel)
    assert wheel.isAccepted() and bar.value() == 0
    QTest.qWait(200)
    assert bar.value() > 0
    for tool in ('clock', 'browser', 'effects'):
        module.request_launch(module.LAUNCH_REQUESTS, tool, builtin=True)
        center.launch_requested_apps()
        opened = center.dock.panel
        assert opened.key == tool and opened.isVisible()
        module.request_launch(module.LAUNCH_REQUESTS, tool, builtin=True)
        center.launch_requested_apps()
        assert center.dock.panel is opened
    center.open_center()
    center.dock.hide()
    assert not center.dock.isVisible()
    QTest.mouseClick(center.count, module.Qt.MouseButton.LeftButton)
    app.processEvents()
    assert center.dock.isVisible()
    assert center.dock.panel is None and center.dock.pending_panel[0] == 'clock'
    center.open_tool('clock', from_start=True)
    assert center.dock.pending_panel[0] == 'clock'
    QTest.qWait(450)
    assert center.dock.panel is not None and center.dock.panel.key == 'clock'
    assert center.dock.panel.content.property('dockEmbedded') is True
    assert center.dock.panel.windowOpacity() == 1.0
    assert center.dock.panel.open_animation.duration() == 155
    assert center.dock.panel.open_animation.startValue() == .20
    assert center.dock.panel.open_animation.endValue() == 1.0
    QTest.mouseClick(center.count, module.Qt.MouseButton.LeftButton)
    app.processEvents()
    assert center.dock.panel is None

    paths = [Path(temporary) / name for name in ('Editor.cmd', 'Notas.cmd', 'Nuevo.cmd')]
    for path in paths:
        path.write_text('@echo off\n', encoding='utf-8')
    center.select_page('general')
    with patch.object(module.QFileDialog, 'getOpenFileNames', return_value=([str(paths[0]), str(paths[1])], '')):
        center.import_button.click()
    assert [item['name'] for item in center.apps] == ['Editor', 'Notas']
    center.search_button.click()
    assert not center.app_search.isHidden()
    with patch.object(module.QInputDialog, 'getText', return_value=('Edición, CLASES', True)):
        center.edit_app_tags(center.apps[1])
    center.app_search.setText('edicion clases')
    assert center.library_rows.count() == 1
    assert 'Etiquetas: Edición, CLASES' in center.library_rows.itemAt(0).widget().toolTip()
    center.app_search.setText('examenes')
    assert center.library_rows.count() == 0
    assert not center.builtin_cards[0][0].isHidden()
    center.search_button.click()
    assert center.app_search.isHidden() and not center.app_search.text()
    center.search_button.click()
    center.app_search.setText('NOTAS')
    assert center.library_rows.count() == 1
    row = center.library_rows.itemAt(0).widget()
    assert row.objectName() == 'appCard'
    more = next(btn for btn in row.findChildren(module.QPushButton) if btn.menu() is not None)
    with patch.object(module.QInputDialog, 'getText', return_value=('Notas rápidas', True)):
        more.menu().actions()[0].trigger()
    assert center.apps[1]['name'] == 'Notas rápidas'
    with patch.object(module.QFileDialog, 'getOpenFileName', return_value=(str(paths[2]), '')):
        center.relink_app(center.apps[1])
    assert Path(center.apps[1]['path']) == paths[2]
    with patch.object(module.QMessageBox, 'question', return_value=module.QMessageBox.StandardButton.Yes):
        center.remove(center.apps[1])
    assert len(center.apps) == 1 and paths[2].is_file()
    stored_apps = module.read(module.APPS, [])[0]
    reloaded_apps = [dict(item, path=str(module.resolve_app_path(item['path']))) for item in stored_apps]
    assert len(reloaded_apps) == len(center.apps)
    for saved, runtime in zip(reloaded_apps, center.apps):
        assert {key: value for key, value in saved.items() if key != 'path'} == {
            key: value for key, value in runtime.items() if key != 'path'}
        assert Path(saved['path']) == Path(runtime['path'])

    center.open_page('settings')
    chooser = next(widget for widget in center.window.findChildren(module.QComboBox)
                   if widget.accessibleName() == 'Versión de la interfaz')
    center.capture_control.setChecked(False)
    assert app.property('capturePrivate')
    chooser.setCurrentIndex(chooser.findData('v1'))
    app.processEvents()
    app.processEvents()
    assert center.dock.isVisible() and center.window.isVisible()
    assert center.dock.panel.key == 'settings' and center.dock.panel.content is center.window
    assert center.window.property('dockEmbedded') is True
    assert center.window.monochrome and not center.window.glass and not center.window.dark
    assert not app.property('capturePrivate') and not center.capture_control.isEnabled()
    center.update_tray_actions()
    assert not center.photo_action.isEnabled()
    assert not center.glass_control.isEnabled() and not center.glass_control.isChecked()
    assert not center.theme_control.isEnabled()
    assert 'QLabel#heroTitle { color: #242424; }' in center.dock.panel.styleSheet()
    assert 'QFrame#clockCard { background: qlineargradient' not in center.dock.panel.styleSheet()
    assert center.dock.geometry().right() == center.dock.screen.availableGeometry().right()
    assert center.dock.panel.geometry().x() < center.dock.geometry().x()
    assert center.dock.panel.geometry().right() <= center.dock.geometry().right()
    panel = center.dock.panel
    dock_left = center.dock.x() + center.dock.optic_rect().left()
    panel_right = panel.x() + panel.optic_rect().right()
    assert 0 <= dock_left - panel_right <= 2
    assert module.read(module.CONFIG, {})[0]['ui_version'] == 'v1'
    center.open_center()
    assert center.dock.panel.key == 'settings' and center.window.isVisible()
    assert center.pages.currentIndex() == center.page_ids['general']
    center.open_center()
    assert center.dock.panel.key == 'settings'
    center.open_page('settings')
    chooser.setCurrentIndex(chooser.findData('v2'))
    app.processEvents()
    app.processEvents()
    assert center.dock.isVisible() and center.window.isVisible()
    assert not center.window.monochrome and center.window.dark
    assert app.property('capturePrivate') and center.capture_control.isEnabled()
    center.capture_control.setChecked(True)
    assert center.glass_control.isEnabled() and not center.glass_control.isChecked()
    assert center.theme_control.isEnabled()
    assert center.dock.geometry().right() == center.dock.screen.availableGeometry().right()
    assert [entry.accessibleName() for entry in center.dock.entries] == [
        'Timer', 'Navegador', 'Efectos de escritorio', 'Editor']
    assert module.read(module.CONFIG, {})[0]['ui_version'] == 'v2'
    pages = center.pages
    active_page = pages.currentWidget()
    chooser.setCurrentIndex(chooser.findData('v3'))
    app.processEvents()
    assert center.dock.pure and center.window.glass and center.pages is pages
    assert pages.currentWidget() is active_page and center.dock.panel.content is center.window
    assert module.read(module.CONFIG, {})[0]['ui_version'] == 'v3'
    chooser.setCurrentIndex(chooser.findData('v1'))
    app.processEvents()
    app.processEvents()
    assert not app.closingDown()
    assert center.window.monochrome and center.window.isVisible()
    assert center.dock.panel.key == 'settings' and center.dock.panel.content is center.window
    assert module.read(module.CONFIG, {})[0]['ui_version'] == 'v1'
    chooser.setCurrentIndex(chooser.findData('v2'))
    app.processEvents()
    assert not center.dock.pure
    assert center.dock.panel.key == 'settings' and center.window.isVisible()
    center.dock.panel.close()
    dock = center.dock
    dock.progress = 1
    dock.layout_icons()
    geometry = [entry.geometry() for entry in dock.entries]
    with patch('edge_dock.QCursor') as cursor:
        cursor.pos.return_value = dock.geometry().center()
        dock.update_dock()
    assert [entry.geometry() for entry in dock.entries] == geometry
    effects = dock.entries[2]
    effects.click()
    assert dock.panel.key == 'effects' and dock.panel.isVisible()
    effects.click()
    assert dock.panel is None
    dock.gear.click()
    assert dock.panel.key == 'settings' and center.window.property('dockEmbedded')
    assert center.pages.currentIndex() == center.page_ids['general']
    dock.gear.click()
    assert dock.panel is None and center.window.isWindow()
    dock.gear.click()
    escape = QKeyEvent(QEvent.Type.KeyPress, module.Qt.Key.Key_Escape, module.Qt.KeyboardModifier.NoModifier)
    dock.keyPressEvent(escape)
    assert escape.isAccepted() and dock.panel is None
    assert dock.isVisible() and dock.handle.isVisible() and dock.progress == 0
    assert dock.mask().contains(dock.handle.geometry().center())
    edge = module.QPoint(dock.width() - 1, dock.handle.geometry().center().y())
    assert dock.mask().contains(edge)
    assert not dock.mask().contains(module.QPoint(edge.x(), dock.handle.y() - 1))
    frame = dock.grab().toImage()
    assert frame.pixelColor(frame.width() - 1, round(edge.y() * frame.devicePixelRatio())).alpha() == 1
    handle_images = []
    for monochrome, pure in ((True, False), (False, False), (False, True)):
        dock.monochrome, dock.pure, dock.theme_dark = monochrome, pure, False
        dock.layer.light = None
        dock.handle.update()
        handle_images.append(dock.grab().toImage())
    handle = handle_images[0]
    ratio = handle.devicePixelRatio()
    handle_rect = dock.handle.geometry()
    left, top = round(handle_rect.left() * ratio), round(handle_rect.top() * ratio)
    width, height = round(handle_rect.width() * ratio), round(handle_rect.height() * ratio)
    points = [(x, y) for y in range(height) for x in range(width)
              if handle.pixelColor(left + x, top + y).alpha() > 64]
    assert points
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    assert (max(xs) - min(xs) + 1) / ratio < 8
    assert (max(ys) - min(ys) + 1) / ratio < 12
    assert all(image.size() == handle.size() and all(
        image.pixelColor(left + x, top + y) == handle.pixelColor(left + x, top + y)
        for y in range(height) for x in range(width))
               for image in handle_images[1:])
    assert max(handle.pixelColor(left + x, top + y).lightness() for x, y in points) < 100
    dock.theme_dark = True
    dark_handle = dock.grab().toImage()
    assert [dark_handle.pixelColor(left + x, top + y).alpha() for y in range(height)
            for x in range(width)] == [handle.pixelColor(left + x, top + y).alpha()
                                       for y in range(height) for x in range(width)]
    assert min(dark_handle.pixelColor(left + x, top + y).lightness() for x, y in points) > 180
    with patch('edge_dock.QCursor') as cursor:
        cursor.pos.return_value = dock.mapToGlobal(edge)
        dock.reveal()
        assert dock.transition_to == 1.0
        dock.reset_to_handle()
        dock.theme_dark = True
        dock.pure = False
        dock.glass_enabled = True
        dock.handle.click()
        assert dock.progress == 1.0
        dock.reset_to_handle()
    # The compact arrow needs no continuous desktop capture.
    dock.progress = dock.transition_to = dock.leave_at = 0.0
    with patch('edge_dock.QCursor') as cursor, patch.object(dock, 'capture') as capture:
        cursor.pos.return_value = dock.geometry().topLeft() - module.QPoint(100, 100)
        dock.backdrop = source = Mock(lens=None)
        dock.reveal()
        assert dock.capture_timer.isActive()
        capture.assert_called_once()
        dock.leave_at = 0.0
        dock.update_dock()
        assert not dock.capture_timer.isActive()
        assert dock.glass_idle_timer.isActive()
        dock.release_idle_capture()
        source.close.assert_called_once()
        assert dock.backdrop is None and not dock.glass_idle_timer.isActive()
    dock.animation.start(1000)
    dock.capture_timer.start(1000)
    dock.glass_timer.start(1000)
    center.toggle_edge_dock_visibility()
    assert not dock.isVisible()
    assert dock.progress == 0.0 and dock.panel is None and dock.backdrop is None
    assert not any(timer.isActive() for timer in
                   (dock.animation, dock.capture_timer, dock.glass_timer))
    center.update_tray_actions()
    assert center.dock_visibility_action.text() == 'Mostrar barra lateral'
    center.toggle_edge_dock_visibility()
    assert dock.isVisible() and dock.handle.isVisible() and dock.progress == 0.0
    center.update_tray_actions()
    assert center.dock_visibility_action.text() == 'Ocultar barra lateral'
    center.dock.close()
    center.window.close()
    center.tray.hide()
    center.count.close()
    print('Centro: navegación, tema persistente, importación, búsqueda, cambio de acceso y eliminación sin borrar archivos.')
