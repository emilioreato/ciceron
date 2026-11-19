"""Measure the OpenGL material over black and white desktop pixels."""
from ctypes import POINTER, byref, wintypes
from pathlib import Path
import sys
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QLabel, QPushButton, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from window_glass import GlassBackdrop, glass_text_rect
from center_ui import AppCardIdentity
from edge_dock import EdgeDock
from windows_glass import CapturePrivacy, bind, client_bounds, root_window, user, window_at


def luminance(color):
    values = [channel / 12.92 if channel <= 0.04045 else ((channel + .055) / 1.055) ** 2.4
              for channel in (color.redF(), color.greenF(), color.blueF())]
    return sum(weight * channel for weight, channel in zip((.2126, .7152, .0722), values))


def contrast(first, second):
    low, high = sorted((luminance(first), luminance(second)))
    return (high + .05) / (low + .05)


app = QApplication([])
window = QWidget()
window.resize(360, 250)
layer = GlassBackdrop(window, lambda _: None)
layer.setGeometry(window.rect())
card = QFrame(window)
card.setObjectName('card')
card.setGeometry(20, 80, 320, 134)
button = QPushButton('Control activo', card)
button.setGeometry(65, 24, 190, 45)
button.setCheckable(True)
button.setChecked(True)
window.show()
layer.show()
layer.lower()
app.processEvents()
assert layer.isValid() and not layer.error, layer.error

source = QImage(360, 250, QImage.Format.Format_RGBA8888)
source.fill(QColor('#000000'))
painter = QPainter(source)
painter.fillRect(180, 0, 180, 250, QColor('#ffffff'))
painter.end()
layer.frame = source
layer.texture_dirty = True
minimum = 99.0
for dark in (False, True):
    layer.dark = dark
    description = QColor('#e0e7f5' if dark else '#35415a')
    active = QColor('#cfdeff' if dark else '#183f82')
    for clarity in (-.18, 0.0, .20):
        layer.transparency = clarity
        result = layer.grabFramebuffer()
        assert not result.isNull()

        def sample(x, y):
            return result.pixelColor(round(x * result.width() / 360),
                                     round(y * result.height() / 250))

        for x in (130, 230):
            for y, foreground in ((45, description), (180, description), (127, active)):
                ratio = contrast(foreground, sample(x, y))
                minimum = min(minimum, ratio)
                assert ratio >= 4.5, (dark, clarity, x, y, ratio)
        assert sample(130, 45) != sample(230, 45), 'Se perdió la transmisión del fondo.'

# Cross the straight upper edge of the window and of a card beneath it.
layer.dark = False
layer.transparency = 0
for top in (0, card.y()):
    readings = []
    for penetration in (0, 3, 15):
        source.fill(QColor('white'))
        painter = QPainter(source)
        painter.fillRect(0, top - 20, source.width(), 20 + penetration, QColor('black'))
        painter.end()
        layer.texture_dirty = True
        result = layer.grabFramebuffer()
        readings.append(sample(60, top + 2).green())
    assert abs(readings[1] - readings[0]) < 5, (top, readings)
    assert readings[0] - readings[2] > 60, (top, readings)
layer.pure = True
for x in range(source.width()):
    shade = QColor('white' if x % 16 < 8 else 'black')
    for y in range(source.height()):
        source.setPixelColor(x, y, shade)
layer.texture_dirty = True
result = layer.grabFramebuffer()
def variation(y):
    values = [sample(x, y).green() for x in range(130, 155)]
    return max(values) - min(values)
assert variation(45) > 180, 'V3 pierde la transparencia en el fondo.'
assert variation(127) < variation(45) * .65, 'Falta el desenfoque dentro del botón V3.'
regular_variation = variation(127)
window.setProperty('frostControls', True)
result = layer.grabFramebuffer()
assert variation(127) < regular_variation, 'El desenfoque de Timer debe suavizar más el fondo.'
source.fill(QColor('black'))
layer.texture_dirty = True
result = layer.grabFramebuffer()
assert sample(140, 45).lightness() < 20
assert sample(140, 2).lightness() > 20, 'Falta el borde óptico de V3 sobre negro.'
over_black = sample(140, 127)
assert contrast(QColor('#202731'), over_black) >= 4.5
source.fill(QColor('white'))
layer.texture_dirty = True
result = layer.grabFramebuffer()
assert sample(140, 127).lightness() > over_black.lightness() + 50
corner = button.mapTo(window, QPoint(0, 0))
with_button = sample(corner.x(), corner.y())
button.hide()
result = layer.grabFramebuffer()
assert with_button == sample(corner.x(), corner.y()), 'La esquina transparente borra el vidrio de base.'
button.show()
label = QLabel('Texto sobre el vidrio', window)
label.setGeometry(125, 33, 180, 24)
label.show()
checkbox = QCheckBox('Opción', window)
checkbox.setGeometry(125, 61, 130, 22)
checkbox.show()
checkbox_text = glass_text_rect(checkbox)
assert not checkbox_text.isEmpty() and checkbox_text.left() > 0
text_rect = label.fontMetrics().boundingRect(label.contentsRect(), label.alignment().value, label.text())
surface = glass_text_rect(label)
assert surface == text_rect.adjusted(-12, -8, 12, 8)
position = label.mapTo(window, surface.center())
result = layer.grabFramebuffer()
assert contrast(QColor('#f0f2f6'), sample(position.x(), position.y())) >= 4.5
assert sample(position.x(), label.y() + surface.top() + 4).lightness() < 220
assert sample(position.x(), 22).lightness() > 220
painter = QPainter(source)
for x in range(source.width()):
    shade = QColor('white' if x % 16 < 8 else 'black')
    painter.fillRect(x, 0, 1, source.height(), shade)
painter.end()
layer.texture_dirty = True
result = layer.grabFramebuffer()
assert variation(position.y()) < variation(22) * .65, 'Falta el desenfoque tras el texto.'
label.hide()
checkbox.hide()
icon = QPixmap(30, 30)
icon.fill(QColor('#6754a5'))
identity = AppCardIdentity(QIcon(icon), QLabel('Happy Birthday'), QLabel('Agenda de cumpleaños'))
identity.setParent(window)
identity.setGeometry(60, 38, 242, 63)
identity.show()
app.processEvents()
source.fill(QColor('white'))
layer.texture_dirty = True
result = layer.grabFramebuffer()
for widget in identity.findChildren(QLabel):
    point = widget.mapTo(window, widget.rect().center())
    assert contrast(QColor('#f0f2f6'), sample(point.x(), point.y())) >= 4.5
assert sample(180, 25).lightness() > 220, 'La superficie debe quedar dentro de la tarjeta.'
window.close()

# Render the actual V2 dock shader against known backgrounds without capturing the desktop.
dock = EdgeDock(QIcon(), lambda: None)
dock.set_glass(False)
dock.move(120, 100)
dock.show()
dock.progress = 1
dock.layout_icons()
dock.layer.show()
app.processEvents()
assert dock.layer.isValid() and not dock.layer.error, dock.layer.error
bounds = client_bounds(int(dock.winId()))
assert bounds is not None
left, top, width, height = bounds
for progress in (0.0, 1.0):
    dock.progress = progress
    dock.layout_icons()
    app.processEvents()
    for offset in (-28, 0, 28):
        y = dock.edge_hover.geometry().center().y() + offset
        edge_y = top + round(y * height / dock.height())
        assert root_window(window_at(wintypes.POINT(left + width - 1, edge_y)), 2) == int(dock.winId())
source = QImage(bounds[2], bounds[3], QImage.Format.Format_RGB32)

def dock_pixel(color, light):
    source.fill(QColor(color))
    dock.layer.set_frame(source.copy(), bounds)
    dock.layer.light = light
    frame = dock.layer.grabFramebuffer()
    center = dock.optic_rect().center() * frame.devicePixelRatio()
    return frame.pixelColor(round(center.x()), round(center.y()))

dark = dock_pixel('#000000', False)
assert dark.red() == dark.green() == dark.blue() < 45, dark.name()
light_in_dark_mode = dock_pixel('#ffffff', False)
assert light_in_dark_mode.red() == light_in_dark_mode.green() == light_in_dark_mode.blue()
assert dock_pixel('#000000', True).lightness() < 50
blue = dock_pixel('#1e519e', False)
assert blue.blue() > blue.green() > blue.red() and blue.blue() > 100, blue.name()

dock.glass_enabled = True
hwnd = int(dock.winId())
dock.layer.frame = None
def center_pixel():
    frame = dock.layer.grabFramebuffer()
    center = dock.optic_rect().center() * frame.devicePixelRatio()
    return frame.pixelColor(round(center.x()), round(center.y()))

# The rim is already present alongside the fading icons with no desktop frame.
dock.progress = 1.0
dock.layout_icons()
with patch('edge_dock.energy_saver_active', return_value=True), \
        patch('edge_dock.DockBackdropCapture') as capture:
    dock.prepare_layer()
    capture.assert_not_called()
dock.progress = .82
dock.layout_icons()
assert dock.gear.isVisible()
for pure in (False, True):
    dock.pure = pure
    frame = dock.layer.grabFramebuffer()
    center = dock.optic_rect().center() * frame.devicePixelRatio()
    row = [frame.pixelColor(x, round(center.y())).alpha() for x in range(round(center.x()) + 1)]
    assert max(row) > row[-1] + 20
dock.pure = False
dock.progress = 1.0
dock.layout_icons()

provisional = center_pixel()
dock.layer.handoff_started = 10.0
with patch('edge_dock.time.monotonic', return_value=10.0):
    first_frame = dock_pixel('#ffffff', False)
with patch('edge_dock.time.monotonic', return_value=10.075):
    intermediate = center_pixel()
with patch('edge_dock.time.monotonic', return_value=10.2):
    live = center_pixel()
assert first_frame == provisional
endpoints = sorted((provisional.lightness(), live.lightness()))
assert endpoints[0] < intermediate.lightness() < endpoints[1]
assert provisional.alpha() < intermediate.alpha() < live.alpha()
assert int(dock.winId()) == hwnd
dock.layer.handoff_timer.stop()
dock.layer.handoff_started = None

dock.progress = .60
dock.layer.awaiting_open = True
dock.layer.frame = None
cold_opening = center_pixel()
assert dock_pixel('#ffffff', True) == cold_opening
assert dock.layer.awaiting_open and dock.layer.handoff_started is None
dock.progress = 1.0
with patch('edge_dock.time.monotonic', return_value=20.0):
    center_pixel()
assert not dock.layer.awaiting_open and dock.layer.handoff_started == 20.0
dock.layer.handoff_timer.stop()
dock.layer.handoff_started = None

dock.using_glass = True
coverage = []
for light, ink in ((False, '#ffffff'), (True, '#343434')):
    dock.layer.light = light
    icon = QImage(dock.gear.size(), QImage.Format.Format_ARGB32_Premultiplied)
    icon.fill(0)
    painter = QPainter(icon)
    dock.gear.render(painter, QPoint(), QRegion(), QWidget.RenderFlag(0))
    painter.end()
    pixels = [icon.pixelColor(x, y) for y in range(icon.height()) for x in range(icon.width())]
    coverage.append([pixel.alpha() for pixel in pixels])
    assert {pixel.name() for pixel in pixels if pixel.alpha() == 255} == {ink}
assert coverage[0] == coverage[1], 'El trazo debe conservar la misma cobertura al cambiar de color.'

dock.pure = True
background_with_icon = dock_pixel('#dedede', True)
dock.gear.hide()
assert dock_pixel('#dedede', True) == background_with_icon
dock.close()

get_affinity = bind(user, 'GetWindowDisplayAffinity', wintypes.BOOL,
                    wintypes.HWND, POINTER(wintypes.DWORD))


def affinity(widget):
    value = wintypes.DWORD()
    assert get_affinity(int(widget.winId()), byref(value)), widget.windowTitle()
    return value.value


dock = EdgeDock(QIcon(), lambda: None)
dock.motion_enabled = False
dock.show()
app.processEvents()
assert dock.layer.isVisible() and dock.layer.isValid()
assert affinity(dock) == 0x11, 'La flecha plegada debe quedar fuera de la captura.'
app.setProperty('captureMode', True)
dock.update_capture_mode()
assert affinity(dock) == 0x11
dock.toggle_panel('clock', QWidget)
app.processEvents()
panel = dock.panel
assert panel is not None and panel.isVisible()
assert affinity(dock) == affinity(panel) == 0
assert dock.backdrop is None and not dock.capture_timer.isActive()
assert not panel.capture_enabled
dock.dismiss_outside_click(dock.panel_session, 0)
assert dock.panel is panel
app.setProperty('captureMode', False)
dock.update_capture_mode()
if dock.backdrop is not None:
    assert affinity(dock) == affinity(panel) == 0x11
    assert dock.capture_timer.isActive()

privacy = CapturePrivacy(app)
privacy.set_private(True)
count = QWidget()
count.setWindowTitle('Timer')
count.show()
app.processEvents()
assert affinity(count) == 0x11
count.hide()
privacy.set_private(False)
count.show()
app.processEvents()
assert affinity(count) == 0
dock.monochrome = True
dock.set_glass(False)
assert affinity(dock) == affinity(panel) == affinity(count) == 0
assert dock.backdrop is None and not panel.capture_enabled
count.close()
dock.shutdown()
assert dock.panel_mouse_press.hook is None
print('Captura: exclusión de flecha, visibilidad de barra y panel, y preferencia de Timer verificadas en Win32.')
print(f'Vidrio: contraste mínimo {minimum:.2f}:1 en claro y oscuro contra blanco y negro.')
