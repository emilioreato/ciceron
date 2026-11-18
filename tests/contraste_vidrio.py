"""Measure the OpenGL material over black and white desktop pixels."""
from pathlib import Path
import sys

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from window_glass import GlassBackdrop


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
    shade = QColor('white' if x % 8 < 4 else 'black')
    for y in range(source.height()):
        source.setPixelColor(x, y, shade)
layer.texture_dirty = True
result = layer.grabFramebuffer()
def variation(y):
    values = [sample(x, y).green() for x in range(130, 155)]
    return max(values) - min(values)
assert variation(45) > 180, 'V3 pierde la transparencia en el fondo.'
assert variation(127) < variation(45) * .65, 'Falta el desenfoque dentro del botón V3.'
window.close()
print(f'Vidrio: contraste mínimo {minimum:.2f}:1 en claro y oscuro contra blanco y negro.')
