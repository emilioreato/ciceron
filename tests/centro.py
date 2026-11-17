"""Exercise navigation and library changes against isolated user data."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeyEvent


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
with TemporaryDirectory() as temporary:
    os.environ['APPDATA'] = os.environ['LOCALAPPDATA'] = temporary
    loader = importlib.machinery.SourceFileLoader('ciceron_centro', str(root / 'src' / 'ciceron.pyw'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module.write(module.CONFIG, dict(module.DEFAULT, show_timer=False, glass=False))
    app = module.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with patch.object(module.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=True):
        center = module.App()
    assert center.dock.isVisible() and center.dock.handle.isVisible()
    assert center.dock.panel is None and center.dock.progress == 0.0
    center.open_center()
    assert center.dock.panel.key == 'settings'
    assert set(center.page_ids) == {'general', 'settings', 'status'}
    assert center.import_button.parentWidget() is center.banner
    assert center.app_search.isHidden()
    assert center.window.property('localWheel')

    for name, index in center.page_ids.items():
        center.nav.button(index).click()
        assert center.pages.currentIndex() == index, name

    center.select_page('settings')
    assert not center.window.property('localWheel')
    theme = next(widget for widget in center.window.findChildren(module.QComboBox)
                 if widget.accessibleName() == 'Tema')
    theme.setCurrentIndex(theme.findData('dark'))
    assert center.window.dark
    assert module.read(module.CONFIG, {})[0]['theme'] == 'dark'

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
    assert module.read(module.APPS, [])[0] == center.apps

    center.open_page('settings')
    chooser = next(widget for widget in center.window.findChildren(module.QComboBox)
                   if widget.accessibleName() == 'Versión de la interfaz')
    chooser.setCurrentIndex(chooser.findData('v1'))
    assert center.classic.isVisible() and not center.window.isVisible()
    assert module.read(module.CONFIG, {})[0]['ui_version'] == 'v1'
    center.open_page('settings')
    chooser.setCurrentIndex(chooser.findData('v2'))
    assert center.dock.isVisible() and not center.classic.isVisible()
    assert center.dock.geometry().right() == center.dock.screen.availableGeometry().right()
    assert [entry.accessibleName() for entry in center.dock.entries] == [
        'Timer', 'Navegador', 'Efectos de escritorio', 'Editor']
    assert module.read(module.CONFIG, {})[0]['ui_version'] == 'v2'
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
    with patch('edge_dock.QCursor') as cursor:
        cursor.pos.return_value = dock.mapToGlobal(edge)
        dock.reveal()
        assert dock.transition_to == 1.0
        dock.reset_to_handle()
    # The compact arrow needs no continuous desktop capture.
    dock.progress = dock.transition_to = dock.leave_at = 0.0
    with patch('edge_dock.QCursor') as cursor, patch.object(dock, 'capture') as capture:
        cursor.pos.return_value = dock.geometry().topLeft() - module.QPoint(100, 100)
        dock.backdrop = object()
        dock.reveal()
        assert dock.capture_timer.isActive()
        capture.assert_called_once()
        dock.leave_at = 0.0
        dock.update_dock()
        assert not dock.capture_timer.isActive()
        dock.backdrop = None
    center.dock.close()
    center.classic.close()
    center.window.close()
    center.tray.hide()
    center.count.close()
    print('Centro: navegación, tema persistente, importación, búsqueda, cambio de acceso y eliminación sin borrar archivos.')
