"""Render README views from Cicerón widgets with isolated demo data.

The material renderer receives only synthetic images; this script never reads
or saves a screenshot of the user's desktop.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPalette, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QDialog, QSystemTrayIcon

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'assets' / 'readme' / 'ui'
sys.path.insert(0, str(ROOT / 'src'))


def load_module(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def synthetic_backdrop(size, *, light=False, calendar=False):
    image = QImage(max(1, size.width()), max(1, size.height()), QImage.Format.Format_RGBA8888)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    width, height = image.width(), image.height()
    gradient = QLinearGradient(0, height, width, 0)
    if light:
        gradient.setColorAt(0, QColor('#c8dcf0'))
        gradient.setColorAt(.46, QColor('#eee9f1'))
        gradient.setColorAt(1, QColor('#c7dce0'))
    else:
        gradient.setColorAt(0, QColor('#0d1724'))
        gradient.setColorAt(.46, QColor('#26344b'))
        gradient.setColorAt(1, QColor('#302a43'))
    painter.fillRect(image.rect(), gradient)
    for x, y, radius, color in (
        (.12, .18, .60, '#63a8c1' if light else '#267d9d'),
        (.77, .23, .56, '#a89dcc' if light else '#554a92'),
        (.55, .88, .62, '#73b6b3' if light else '#196878'),
    ):
        glow = QRadialGradient(QPointF(width * x, height * y), min(width, height) * radius)
        glow.setColorAt(0, QColor(color))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.fillRect(image.rect(), glow)
    line_color = QColor(37, 59, 84, 42) if light else QColor(225, 237, 255, 45)
    painter.setPen(QPen(line_color, max(1, width // 650)))
    step = max(36, width // 13)
    for x in range(-height, width + height, step):
        painter.drawLine(x, 0, x + height, height)
    painter.setPen(QPen(QColor(255, 255, 255, 60), max(1, width // 900)))
    painter.setBrush(QColor(15, 24, 38, 70))
    painter.drawRoundedRect(QRectF(width * .08, height * .18, width * .38, height * .23), 22, 22)
    painter.drawRoundedRect(QRectF(width * .53, height * .51, width * .37, height * .26), 22, 22)
    painter.setPen(QColor(255, 255, 255, 170))
    painter.end()
    if calendar:
        from focus_alert import gaussian_backdrop
        return gaussian_backdrop(image, max(1, round(min(width, height) / 160)))
    return image


def save_widget(widget, path: Path, scale=2):
    widget.ensurePolished()
    pixmap = widget.grab()
    if pixmap.isNull():
        raise RuntimeError(f'No se pudo renderizar {widget.objectName() or widget.windowTitle()}')
    source = pixmap.toImage()
    result = QImage(source.width() * scale, source.height() * scale,
                    QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(QColor('#15171c'))
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(result.rect(), source)
    painter.end()
    if not result.save(str(path), 'PNG'):
        raise OSError(f'No se pudo guardar {path}')
    return result.size()


def move_hidden(widget, app):
    """Keep the Qt renderer outside every visible monitor while it paints."""
    screen = app.primaryScreen()
    geometry = screen.geometry() if screen is not None else None
    x = geometry.right() + 4096 if geometry is not None else 4096
    y = geometry.bottom() + 4096 if geometry is not None else 4096
    widget.move(x, y)
    widget.setWindowOpacity(0.0)


def add_synthetic_material(widget, app, backdrop):
    from window_glass import GlassBackdrop

    layer = GlassBackdrop(widget, lambda _: None)
    layer.pure = bool(app.property('pureGlass'))
    layer.dark = bool(getattr(widget, 'dark', False))
    layer.transparency = float(getattr(widget, 'transparency', 0.0))
    layer.setGeometry(widget.rect())
    layer.set_frame(backdrop)
    layer.show()
    layer.lower()
    app.processEvents()
    if not layer.isValid() or layer.error:
        layer.close()
        raise RuntimeError(layer.error or 'No se pudo crear el contexto OpenGL para la galería.')
    return layer


def capture_main(center, app, version, filename, page='general', *, size=(520, 650)):
    center.cfg.update(ui_version=version, theme='light', glass=True, clarity='balanced')
    center.apply_appearance()
    center.select_page(page)
    center.window.setFixedSize(*size)
    move_hidden(center.window, app)
    center.window.show()
    app.processEvents()
    layer = add_synthetic_material(center.window, app,
                                   synthetic_backdrop(center.window.size(), light=version == 'v2'))
    try:
        path = OUTPUT / filename
        dimensions = save_widget(center.window, path)
        print(f'{path.relative_to(ROOT)} · {dimensions.width()}×{dimensions.height()}')
    finally:
        layer.close()
        layer.deleteLater()
        center.window.hide()
        app.processEvents()


def capture_dialog(dialog, app, filename, width=None, *, light=False):
    dialog.ensurePolished()
    if width:
        dialog.resize(width, dialog.sizeHint().height())
    move_hidden(dialog, app)
    dialog.show()
    app.processEvents()
    layer = add_synthetic_material(dialog, app,
                                   synthetic_backdrop(dialog.size(), light=light))
    try:
        path = OUTPUT / filename
        dimensions = save_widget(dialog, path)
        print(f'{path.relative_to(ROOT)} · {dimensions.width()}×{dimensions.height()}')
    finally:
        layer.close()
        layer.deleteLater()
        dialog.close()
        app.processEvents()


def capture_calendar(app, path: Path):
    sys.path.insert(0, str(ROOT / 'paquetes' / 'happy-birthday'))
    agenda_module = load_module('ciceron_readme_agenda',
                                ROOT / 'paquetes' / 'happy-birthday' / 'qt_agenda.py')
    host = SimpleNamespace(
        center=SimpleNamespace(window=SimpleNamespace(dark=False), cfg={'dock_motion': False}),
        calendar_days=lambda year: {
            date(year, 2, 14): ['Cumpleaños de ejemplo'],
            date(year, 7, 4): ['Cumpleaños de ejemplo'],
            date(year, 11, 19): ['Cumpleaños de ejemplo'],
        },
    )
    agenda = QDialog()
    agenda.resize(430, 320)
    agenda.host = host
    agenda.dark = False
    agenda.records = SimpleNamespace(entries=[])
    agenda.trace = lambda *args, **kwargs: None
    agenda.trace_exception = lambda *args, **kwargs: None
    year = agenda_module.Year(agenda, date(2026, 11, 19))

    def synthetic_blurred_background():
        year.snapshot = synthetic_backdrop(year.size(), calendar=True)
        year.update()

    year.load_backdrop = synthetic_blurred_background
    move_hidden(year, app)
    year.show()
    app.processEvents()
    time.sleep(.06)
    app.processEvents()
    try:
        for table in year.months:
            palette = table.palette()
            for role in (QPalette.ColorRole.Base, QPalette.ColorRole.AlternateBase,
                         QPalette.ColorRole.Window):
                palette.setColor(role, QColor('#fbfbfc'))
            for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText):
                palette.setColor(role, QColor('#252a32'))
            table.setPalette(palette)
            table.viewport().setPalette(palette)
            table.viewport().setAutoFillBackground(True)
            table.setAutoFillBackground(True)
            table.setStyleSheet(table.styleSheet() + """
                QTableWidget { background: #fbfbfc; }
                QTableWidget::item { background-color: transparent; }
                QHeaderView::section { background: #fbfbfc; }
            """)
        app.processEvents()
        dimensions = save_widget(year, path)
        print(f'{path.relative_to(ROOT)} · {dimensions.width()}×{dimensions.height()}')
    finally:
        year.close()
        agenda.close()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    keys = ('APPDATA', 'LOCALAPPDATA', 'CICERON_HOME', 'CICERON_DATA', 'CICERON_DEV')
    previous = {key: os.environ.get(key) for key in keys}
    with tempfile.TemporaryDirectory(prefix='ciceron-readme-') as temporary:
        isolated = Path(temporary)
        os.environ['APPDATA'] = str(isolated / 'Roaming')
        os.environ['LOCALAPPDATA'] = str(isolated / 'Local')
        os.environ['CICERON_HOME'] = str(isolated / 'Aplicacion')
        os.environ['CICERON_DATA'] = str(isolated / 'datos')
        os.environ['CICERON_DEV'] = '1'
        for key in ('APPDATA', 'LOCALAPPDATA'):
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)

        module = load_module('ciceron_readme_app', ROOT / 'src' / 'ciceron.pyw')
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        module.write(module.CONFIG, dict(
            module.DEFAULT,
            title='Sesión de enfoque',
            target='2026-12-01T09:00:00',
            show_timer=False,
            theme='light',
            ui_version='v2',
            dock_motion=False,
        ))
        with (
            patch.object(module.App, 'show_edge_dock', lambda self: None),
            patch.object(module.App, 'prepare_birthday', lambda self: None),
            patch.object(QSystemTrayIcon, 'show', lambda self: None),
        ):
            center = module.App()

        center.window.setFixedSize(520, 650)
        capture_main(center, app, 'v2', 'general-v2.png')
        capture_main(center, app, 'v3', 'general-v3.png')
        capture_main(center, app, 'v4', 'general-v4.png')
        capture_main(center, app, 'v2', 'settings-v2.png', page='settings', size=(520, 700))

        center.cfg.update(title='Sesión de enfoque', target='2026-12-01T09:00:00',
                          guardian=True, ui_version='v2')
        center.apply_appearance()
        timer = center.goal_dialog(attached=True)
        capture_dialog(timer, app, 'timer-v2.png', width=410, light=True)

        center.cfg['ui_version'] = 'v3'
        center.apply_appearance()
        app._ciceron_overlay = SimpleNamespace(isVisible=lambda: True)
        app._ciceron_particles = []
        effects = module.VisualDialog(center.window, attached=True, dock_provider=lambda: None)
        capture_dialog(effects, app, 'effects-v3.png', width=380)

        browser = module.BrowserDialog(center.window, attached=True)
        capture_dialog(browser, app, 'web-block-v3.png', width=430)

        capture_calendar(app, OUTPUT / 'annual-calendar.png')

        center.tray.hide()
        center.window.close()
        app.processEvents()

    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == '__main__':
    main()
