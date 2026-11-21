"""Exercise navigation and library changes against isolated user data."""
import importlib.machinery
import importlib.util
from ctypes import addressof, wintypes
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QEnterEvent, QKeyEvent, QWheelEvent
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
    assert center.library_summary.text() == ''
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
    assert module.capture_mode() and not app.property('capturePrivate')
    assert center.photo_action.isEnabled() and center.photo_timer.isActive()
    center.photo_timer.timeout.emit()
    assert not module.capture_mode() and not center.photo_timer.isActive()
    assert app.property('capturePrivate')
    saved, _ = module.read(module.CONFIG, {})
    assert saved['include_in_captures'] is False
    center.capture_control.setChecked(True)
    center.update_tray_actions()
    assert not app.property('capturePrivate') and center.photo_action.isEnabled()
    center.glass_control.setChecked(False)
    assert center.dock_visibility_action.text() == 'Ocultar barra lateral'
    from app_packages import atomic_json, create_package
    payload = Path(temporary) / 'miniapp'
    payload.mkdir()
    (payload / 'open.pyw').write_text('pass\n', encoding='utf-8')
    atomic_json(payload / 'ciceron.json', {
        'schema': 1, 'id': 'local.desde-codigo', 'version': '1.0.0', 'name': 'Desde código',
        'entrypoint': 'open.pyw', 'python': '3.12',
    })
    archive = Path(temporary) / 'miniapp.ciceron'
    create_package(payload, archive)
    assert not center.managed_apps
    module.PackageStore(center.packages.root, center.packages.data).install(archive)
    with patch.object(center, 'launch') as package_launch:
        module.request_launch(module.LAUNCH_REQUESTS, 'local.desde-codigo')
        center.launch_requested_apps()
    package_launch.assert_called_once_with(center.managed_apps[0])
    with patch.object(center, 'launch') as package_launch:
        icon = next(entry for entry in center.dock.entries if entry.accessibleName() == 'Desde código')
        icon.click()
    package_launch.assert_called_once_with(center.managed_apps[0])
    center.packages.remove('local.desde-codigo')
    center.reload_packages()
    center.render()
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
            patch('edge_dock.QApplication.widgetAt', return_value=center.window), \
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
    timer_dialog = center.goal_dialog(attached=True)
    date_editor = timer_dialog.findChild(module.QDateEdit).lineEdit()
    time_editor = timer_dialog.findChild(module.QTimeEdit).lineEdit()
    assert 'color:' not in date_editor.styleSheet()
    assert 'color:' not in time_editor.styleSheet()
    timer_dialog.close()
    timer_dialog.deleteLater()
    assert module.read(module.CONFIG, {})[0]['theme'] == 'dark'
    assert not any(btn.text() == 'Aplicaciones instaladas de Windows'
                   for btn in center.window.findChildren(module.QPushButton))
    center.select_page('status')
    app.processEvents()
    page = center.pages.currentWidget()
    bar = page.verticalScrollBar()
    assert bar.maximum() > 0
    msg.message = 0x020A  # Wheel over a page with internal scroll stays in Cicerón.
    with patch('edge_dock.QApplication.widgetAt', return_value=page.viewport()), \
            patch('edge_dock.forward_wheel') as forward:
        assert wheel_filter.nativeEventFilter(b'windows_generic_MSG', addressof(msg)) == (False, 0)
        forward.assert_not_called()
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
        if tool == 'clock':
            timer = opened.content
            more = next(button for button in timer.findChildren(module.QPushButton) if button.text() == 'Opciones')
            initial = opened.geometry()
            with patch.object(center.dock, 'motion_enabled', False):
                more.click()
                assert opened.content is timer and opened.subpanel is None
                assert opened.y() == initial.y() and opened.height() > initial.height()
                more.click()
                assert opened.y() == initial.y() and opened.height() == initial.height()
        if tool == 'browser':
            browser = opened.content
            title = browser.findChild(module.QLabel, 'title')
            indicator = browser.status_indicator
            assert indicator.isVisible()
            assert indicator.geometry().right() == browser.toggle.geometry().right()
            assert abs(indicator.geometry().center().y() - title.geometry().center().y()) <= 1
            dots = indicator.grab().toImage()
            assert dots.pixelColor(dots.rect().center()).name() == '#e5656c'
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
    for _ in range(30):
        panel = center.dock.panel
        if panel is not None and panel.windowOpacity() == 1.0:
            break
        QTest.qWait(40)
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
    for card in (row, *(frame for frame, _ in center.builtin_cards)):
        identity = card.findChild(module.AppCardIdentity)
        assert identity is not None and not identity.badge.pixmap().isNull()
        assert {label.objectName() for label in identity.findChildren(module.QLabel)} == {
            'appCardIcon', 'heading', 'muted',
        }
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
    assert abs(dock_left - panel_right - (center.dock.PANEL_GAP + 1)) <= 1
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
    center.select_page('general')
    app.processEvents()
    assert not center.banner.live and center.library_summary.text() == ''
    v2_banner = center.banner.grab().toImage()
    v2_samples = tuple(v2_banner.pixelColor(v2_banner.width() - 36, y).rgba()
                       for y in (v2_banner.height() // 5, v2_banner.height() // 2))
    assert v2_samples[0] != v2_samples[1]
    v2_geometry = (center.banner.geometry().getRect(),
                   tuple((child.objectName(), child.geometry().getRect())
                         for child in center.banner.findChildren(module.QWidget)))
    center.select_page('settings')
    pages = center.pages
    active_page = pages.currentWidget()
    chooser.setCurrentIndex(chooser.findData('v3'))
    app.processEvents()
    assert (center.dock.pure and center.window.glass and center.glass_control.isChecked()
            and not center.glass_control.isEnabled() and center.pages is pages)
    assert pages.currentWidget() is active_page and center.dock.panel.content is center.window
    assert module.read(module.CONFIG, {})[0]['ui_version'] == 'v3'
    center.select_page('general')
    app.processEvents()
    assert not center.banner.live and center.library_summary.text() == ''
    v3_banner = center.banner.grab().toImage()
    v3_samples = tuple(v3_banner.pixelColor(v3_banner.width() - 36, y).rgba()
                       for y in (v3_banner.height() // 5, v3_banner.height() // 2))
    assert v3_samples == v2_samples, (v2_banner.size(), v3_banner.size(),
                                      v2_samples, v3_samples)
    v3_geometry = (center.banner.geometry().getRect(),
                   tuple((child.objectName(), child.geometry().getRect())
                         for child in center.banner.findChildren(module.QWidget)))
    assert v3_geometry == v2_geometry
    center.select_page('settings')
    timer_dialog = center.goal_dialog(attached=True)
    assert 'color:' not in timer_dialog.findChild(module.QDateEdit).lineEdit().styleSheet()
    timer_dialog.close()
    timer_dialog.deleteLater()
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
    with patch.object(dock, 'prime_initial_capture') as prime_capture:
        center.show_edge_dock()
        prime_capture.assert_called_once_with()
    previous_glass = dock.glass_enabled
    dock.glass_enabled = True
    with patch('edge_dock.DockBackdropCapture') as capture_worker, \
            patch('edge_dock.apply_capture_affinity', return_value=True), \
            patch('edge_dock.client_bounds', return_value=(10, 20, 55, 600)), \
            patch('edge_dock.energy_saver_active', return_value=False):
        capture_worker.return_value.latest = None
        dock.prime_initial_capture()
        dock.prime_initial_capture()
        capture_worker.assert_called_once_with()
        capture_worker.return_value.submit.assert_called_once_with(((10, 20, 55, 600), None))
        assert not dock.capture_timer.isActive()
    dock.backdrop = None
    dock.initial_capture_attempted = False
    dock.glass_enabled = previous_glass
    dock.pure = True
    dock.progress = (dock.HANDLE_FADE_END + .76) / 2
    dock.layout_icons()
    for entry in (*dock.entries, dock.gear):
        overlap = entry.geometry().intersected(dock.handle.geometry())
        if not overlap.isEmpty() and entry.isVisible():
            break
    else:
        raise AssertionError('La prueba necesita un icono bajo la flecha durante la transición.')
    assert dock.childAt(overlap.center()) is entry
    dock.progress = 1
    dock.layout_icons()
    assert dock.handle.isHidden()
    assert dock.childAt(entry.geometry().center()) is entry
    dock.pure = False
    geometry = [entry.geometry() for entry in dock.entries]
    with patch('edge_dock.QCursor') as cursor:
        cursor.pos.return_value = dock.geometry().center()
        dock.update_dock()
    assert [entry.geometry() for entry in dock.entries] == geometry
    effects = dock.entries[2]
    effects.click()
    assert dock.panel.key == 'effects' and dock.panel.isVisible()
    visual = dock.panel.content
    title = visual.findChild(module.QLabel, 'heading')
    assert visual.bubble.x() == visual.particles.x() == title.x()
    assert visual.bubble.size() == visual.particles.size()
    assert visual.particles.y() - visual.bubble.geometry().bottom() - 1 == visual.layout().spacing()
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
    assert dock.handle.cursor().shape() == dock.cursor().shape() == module.Qt.CursorShape.ArrowCursor
    assert dock.gear.cursor().shape() == module.Qt.CursorShape.PointingHandCursor
    handle_hit = dock.handle.hit_region()
    handle_hit_bounds = handle_hit.boundingRect()
    arrow_hit_point = module.QPoint(dock.handle.width() - dock.handle.ARROW_RIGHT_INSET,
                                    dock.handle.height() // 2)
    assert dock.handle.mapTo(dock, arrow_hit_point).x() == dock.WIDTH - 5
    assert handle_hit_bounds.width() == dock.handle.HIT_WIDTH < dock.handle.width()
    assert handle_hit_bounds.height() >= dock.handle.HIT_HEIGHT - 1
    assert handle_hit_bounds.height() > dock.HANDLE_HEIGHT - 10
    assert handle_hit_bounds.right() == dock.handle.width() - 1
    assert handle_hit.contains(arrow_hit_point)
    assert not handle_hit.contains(handle_hit_bounds.topLeft())
    assert not handle_hit.contains(handle_hit_bounds.topRight())
    assert not dock.mask().contains(dock.handle.mapTo(dock, module.QPoint(1, 1)))
    assert dock.mask().contains(dock.handle.geometry().center())
    edge = module.QPoint(dock.width() - 1, dock.handle.geometry().center().y())
    assert dock.mask().contains(edge)
    for offset in (-28, 28):
        edge_margin = edge + module.QPoint(0, offset)
        assert dock.mask().contains(edge_margin)
        assert dock.childAt(edge_margin) is dock.handle
        with patch('edge_dock.QCursor') as cursor:
            cursor.pos.return_value = dock.mapToGlobal(edge_margin)
            assert dock.pointer_over_dock()
    assert dock.optic_rect().right() == dock.width() - 2
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
        image.pixelColor(left + x, top + y).alpha() == handle.pixelColor(left + x, top + y).alpha()
        for y in range(height) for x in range(width)) for image in handle_images[1:])
    arrow_tones = [handle.pixelColor(left + x, top + y).lightness() for x, y in points]
    assert max(arrow_tones) < 90, 'La flecha clara debe ser un trazo único, sin contorno.'
    pure_tones = [handle_images[2].pixelColor(left + x, top + y).lightness() for x, y in points]
    assert min(pure_tones) > 220, 'La flecha oscura debe conservar el mismo trazo en V3.'
    dock.theme_dark = True
    dock.glass_enabled = True
    dark_handle = dock.grab().toImage()
    assert [dark_handle.pixelColor(left + x, top + y).alpha() for y in range(height)
            for x in range(width)] == [handle.pixelColor(left + x, top + y).alpha()
                                       for y in range(height) for x in range(width)]
    dark_tones = [dark_handle.pixelColor(left + x, top + y).lightness() for x, y in points]
    assert min(dark_tones) > 220, 'La flecha debe adaptar solo el color, sin añadir un borde.'
    with patch('edge_dock.QCursor') as cursor, patch.object(dock, 'prepare_layer') as start_glass, \
            patch('edge_dock.energy_saver_active', return_value=False), \
            patch('edge_dock.capture_mode', return_value=False):
        cursor.pos.return_value = dock.mapToGlobal(edge)
        enter = QEnterEvent(QPointF(edge), QPointF(edge), QPointF(cursor.pos.return_value))
        dock.enterEvent(enter)
        assert dock.hover_timer.isActive() and dock.progress == dock.transition_to == 0.0
        assert dock.hover_timer.interval() + dock.hover_probe.interval() < 70
        assert not dock.animation.isActive() and not dock.glass_timer.isActive()
        start_glass.assert_not_called()
        cursor.pos.return_value = dock.mapToGlobal(QPoint(-5, -5))
        dock.leaveEvent(QEvent(QEvent.Type.Leave))
        assert not dock.hover_timer.isActive() and not dock.animation.isActive()
        cursor.pos.return_value = dock.mapToGlobal(edge)
        # The cursor can be on the handle without Qt delivering a fresh Enter event.
        dock.hover_probe.timeout.emit()
        assert dock.hover_timer.isActive()
        dock.hover_timer.timeout.emit()
        assert not dock.hover_timer.isActive() and dock.transition_to == 1.0
        start_glass.assert_called_once()
        dock.leaveEvent(QEvent(QEvent.Type.Leave))
        assert dock.transition_to == 1.0
        dock.reset_to_handle()
        dock.hover_probe.timeout.emit()
        assert not dock.hover_timer.isActive()
        dock.reveal()
        assert dock.transition_to == 1.0
        assert start_glass.call_count == 2
        dock.reset_to_handle()
        dock.theme_dark = True
        dock.pure = False
        dock.glass_enabled = True
        dock.handle.click()
        assert dock.transition_to == 1.0 and dock.progress < 1.0
        assert start_glass.call_count == 3
        assert dock.animation.isActive()
        dock.reset_to_handle()
        with patch('edge_dock.time.monotonic', return_value=20.0) as now:
            dock.reveal()
            now.return_value = 20.5
            dock.update_dock()
            assert 0.0 < dock.progress < .1, 'El primer cuadro no debe saltar tras una pausa de Qt.'
            assert dock.handle.isVisible() and not dock.gear.isVisible()
            for time_at_edge in (20.5 + tick * .02 for tick in range(1, 12)):
                now.return_value = time_at_edge
                dock.update_dock()
                assert dock.mask().contains(edge) and dock.transition_to == 1.0
                assert dock.edge_hover.isVisible() and dock.edge_hover.hit_region().translated(
                    dock.edge_hover.pos()).contains(edge)
                assert dock.cursor().shape() == module.Qt.CursorShape.ArrowCursor
            assert dock.progress == 1.0 and dock.handle.isHidden()
            assert not dock.mask().contains(module.QPoint(edge.x(), dock.handle.y() - 1))
        dock.reset_to_handle()
    # Desktop capture starts on its worker; repeated reveals cannot block input
    # or spawn additional workers while the first frame is pending.
    dock.progress = dock.transition_to = dock.leave_at = 0.0
    with patch('edge_dock.QCursor') as cursor, patch('edge_dock.DockBackdropCapture') as capture_worker, \
            patch('edge_dock.energy_saver_active', return_value=False), \
            patch('edge_dock.capture_mode', return_value=False), \
            patch.object(dock.layer, 'isValid', return_value=True), \
            patch('edge_dock.apply_capture_affinity', return_value=True), \
            patch.object(dock, 'capture') as submit_capture:
        capture_worker.return_value.latest = None
        capture_worker.return_value.lens = None
        dock.backdrop = None
        dock.layer.frame = None
        dock.layer.light = None
        cursor.pos.return_value = dock.mapToGlobal(edge)
        dock.reveal()
        assert capture_worker.call_count == 1
        assert dock.capture_timer.isActive() and submit_capture.call_count == 1
        dock.reveal()
        dock.prepare_layer()
        assert capture_worker.call_count == 1
        assert submit_capture.call_count == 1
        dock.reset_to_handle()
        dock.release_idle_capture()
    dock.progress = dock.transition_to = 1.0
    dock.leave_at = 0.0
    dock.motion_enabled = False
    dock.animation.stop()
    with patch('edge_dock.QCursor') as cursor:
        cursor.pos.return_value = dock.mapToGlobal(module.QPoint(-100, -100))
        dock.leaveEvent(QEvent(QEvent.Type.Leave))
        assert dock.animation.isActive()
        QTest.qWait(round(dock.HIDE_DELAY * 1000) + 20)
        dock.update_dock()
    assert dock.progress == 0.0 and not dock.animation.isActive()
    dock.motion_enabled = True
    dock.set_glass(False)
    first = Mock(side_effect=module.QWidget)
    latest = Mock(side_effect=module.QWidget)
    dock.toggle_panel('clock', first)
    dock.toggle_panel('clock', first)
    assert dock.pending_panel is None
    dock.toggle_panel('clock', first)
    dock.progress = 1.0
    dock.update_dock()
    assert dock.pending_open_timer.isActive()
    dock.reset_to_handle()
    assert not dock.pending_open_timer.isActive()
    dock.toggle_panel('effects', latest)
    app.processEvents()
    first.assert_not_called()
    latest.assert_not_called()
    assert dock.panel is None and dock.pending_panel[0] == 'effects'
    dock.progress = 1.0
    dock.update_dock()
    app.processEvents()
    latest.assert_called_once_with()
    panel = dock.panel
    assert panel is not None and panel.key == 'effects'

    initial_height = panel.height()
    original_geometry = panel.geometry()
    seam = dock.x() + round(dock.optic_rect().left()) + panel.INSET - dock.PANEL_GAP
    narrow_screen = SimpleNamespace(availableGeometry=lambda: QRect(seam - 120, 0, 120, 900))
    wide_screen = SimpleNamespace(availableGeometry=lambda: QRect(seam - 2000, 0, 2000, 1100))
    with patch.object(dock, 'current_screen', return_value=narrow_screen):
        clamped = dock.panel_geometry(panel, initial_height)
    assert clamped.width() == 120
    panel.setGeometry(clamped)
    with patch.object(dock, 'current_screen', return_value=wide_screen):
        restored = dock.panel_geometry(panel, initial_height)
    assert restored.width() == panel.preferred_width
    panel.setGeometry(original_geometry)

    with patch('edge_dock.client_bounds', return_value=(0, 0, panel.width(), initial_height)), \
            patch.object(panel.content, 'sizeHint', return_value=QSize(260, initial_height + 30)) as size_hint, \
            patch.object(dock, 'capture'):
        panel.using_glass = True
        panel.fit_content()
        assert panel.resize_wait_timer.isActive()
        target = panel.pending_geometry
        assert target.height() != initial_height
        QTest.qWait(160)
        assert panel.geometry() == target and panel.pending_geometry is None and panel.capture_tile is None
        assert panel.scroll.verticalScrollBarPolicy() == module.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        size_hint.return_value = QSize(260, initial_height + 10)
        dock.motion_enabled = False
        panel.fit_content()
        assert panel.height() != target.height()
        assert panel.resize_target() is None and not panel.resize_wait_timer.isActive()
    panel.close()
    dock.reset_to_handle()
    if dock.panel is not None:
        dock.panel.close()
    dock.cancel_pending_panel()
    dock.reset_to_handle()
    dock.set_glass(True)
    from birthday_host import agenda_module
    birthday_ui = agenda_module()
    birthday_path = Path(temporary) / 'birthday' / 'cumpleanos.json'
    birthday_path.parent.mkdir(parents=True, exist_ok=True)
    birthday_host = SimpleNamespace(center=SimpleNamespace(window=center.window),
                                    calendar_days=lambda _year: {})
    content = birthday_ui.Agenda(birthday_path, birthday_ui.load(birthday_path), birthday_host)
    content.setProperty('restartState', 'kept')
    dock.motion_enabled = False
    dock.progress = 1.0
    dock.toggle_panel('emilioreato.happy-birthday', lambda: content, persistent=True)
    assert dock.panel is not None and dock.panel.content is content
    content.open_year()
    app.processEvents()
    calendar = content.year_dialog
    assert calendar is not None and calendar.isVisible()
    calendar.accept()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert content.year_dialog is None
    dock.panel.close()
    dock.reset_to_handle()
    dock.progress = 1.0
    dock.toggle_panel('emilioreato.happy-birthday', lambda: content, persistent=True)
    content.open_year()
    app.processEvents()
    calendar = content.year_dialog
    assert calendar is not None and calendar.isVisible()
    calendar.accept()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert content.year_dialog is None and dock.panel.content is content
    dock.motion_enabled = True
    dock.animation.start(1000)
    dock.capture_timer.start(1000)
    dock.glass_timer.start(1000)
    center.toggle_edge_dock_visibility()
    assert not dock.isVisible()
    assert dock.progress == 0.0 and dock.panel is None and dock.backdrop is None
    assert content.parentWidget() is None and content.property('restartState') == 'kept'
    assert not any(timer.isActive() for timer in
                   (dock.animation, dock.hover_timer, dock.hover_probe, dock.pending_open_timer,
                    dock.capture_timer, dock.glass_timer))
    center.update_tray_actions()
    assert center.dock_visibility_action.text() == 'Mostrar barra lateral'
    dock.progress = 0.63
    dock.transition_to = 1.0
    dock.layer.frame = Mock()
    dock.layer.light = True
    dock.pending_panel = ('clock', Mock(), False)
    dock.pending_open_timer.start(1000)
    dock.panel_mouse_press.receiver = 123
    old_dock = dock
    with patch.object(type(dock), 'reveal') as reveal:
        center.dock_visibility_action.trigger()
    reveal.assert_called_once()
    dock = center.dock
    assert dock is not old_dock and not old_dock.isVisible()
    assert dock.isVisible() and dock.handle.isVisible() and dock.progress == 0.0
    assert dock.transition_to == 0.0 and dock.layer.frame is None and dock.layer.light is None
    assert dock.pending_panel is None and dock.panel_mouse_press.receiver is None
    assert old_dock.pending_panel is None and old_dock.panel_mouse_press.receiver is None
    assert not any(timer.isActive() for timer in
                   (dock.animation, dock.hover_timer, dock.pending_open_timer, dock.capture_timer,
                    dock.glass_timer, dock.glass_idle_timer))
    dock.motion_enabled = False
    dock.progress = 1.0
    dock.toggle_panel('restart-test', lambda: content, persistent=True)
    assert dock.panel is not None and dock.panel.content is content
    assert content.property('restartState') == 'kept'
    dock.panel.close()
    assert content.parentWidget() is None
    dock.reset_to_handle()
    center.update_tray_actions()
    assert center.dock_visibility_action.text() == 'Ocultar barra lateral'
    center.dock.close()
    content.reminders.stop()
    content.deleteLater()
    center.window.close()
    center.tray.hide()
    center.count.close()
    print('Centro: navegación, tema persistente, importación, búsqueda, cambio de acceso y eliminación sin borrar archivos.')
