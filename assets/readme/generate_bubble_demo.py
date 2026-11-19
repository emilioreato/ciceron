"""Render Ciceron's real GPU bubble shader over a synthetic test backdrop.

The script never captures the Windows desktop. Run it from the repository's
Python environment in an interactive Windows session with OpenGL available.
"""
from pathlib import Path
import sys
import time

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from gpu_lens import DesktopBubble


def backdrop():
    image = QImage(400, 400, QImage.Format.Format_RGBA8888)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, 400, 400)
    gradient.setColorAt(0, QColor('#eee8dd'))
    gradient.setColorAt(.48, QColor('#b9a794'))
    gradient.setColorAt(1, QColor('#252422'))
    painter.fillRect(image.rect(), gradient)
    painter.fillRect(205, 0, 195, 400, QColor(30, 29, 28, 125))

    painter.setPen(QPen(QColor('#fff8ef'), 2))
    for offset in range(-360, 520, 38):
        painter.drawLine(offset, 0, offset + 380, 400)
    painter.setPen(QPen(QColor('#443c34'), 2))
    for x in range(28, 401, 48):
        painter.drawLine(x, 0, x, 400)
    for y in range(28, 401, 48):
        painter.drawLine(0, y, 400, y)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#cf8b6e'))
    painter.drawEllipse(48, 72, 94, 94)
    painter.setBrush(QColor('#e4d8c7'))
    painter.drawRoundedRect(244, 64, 120, 84, 15, 15)
    painter.setBrush(QColor('#59534c'))
    painter.drawRoundedRect(54, 270, 292, 66, 16, 16)
    painter.setPen(QPen(QColor('#fffaf2'), 2))
    painter.setFont(QFont('Segoe UI', 19, QFont.Weight.DemiBold))
    painter.drawText(72, 313, 'CICERÓN')
    painter.end()
    return image


def render_bubble(app, image, motion):
    bubble = DesktopBubble()
    bubble.setFixedSize(image.size())
    bubble.move(-1200, -1200)
    bubble.setWindowOpacity(0.0)
    bubble.show()
    app.processEvents()
    if not bubble.isValid() or bubble.gl_error:
        bubble.close()
        raise RuntimeError(bubble.gl_error or 'No se pudo crear el contexto OpenGL.')
    bubble.timer.stop()
    bubble.frame = image
    bubble.frame_origin = QPoint(0, 0)
    bubble.frame_dirty = True
    bubble.motion = motion
    bubble.started = time.monotonic() - .11
    bubble.update()
    app.processEvents()
    result = bubble.grabFramebuffer()
    bubble.close()
    if result.isNull():
        raise RuntimeError('La burbuja no produjo un fotograma.')
    return result


def main():
    app = QApplication.instance() or QApplication([])
    source = backdrop()
    resting = render_bubble(app, source, QPointF())
    moving = render_bubble(app, source, QPointF(.8, -.45))

    canvas = QImage(1200, 700, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QColor('#171615'))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor('#d99a78'))
    painter.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
    painter.drawText(62, 58, 'CAPTURA DEL SHADER OPENGL · FONDO SINTÉTICO')
    painter.setPen(QColor('#f3eee6'))
    painter.setFont(QFont('Segoe UI', 29, QFont.Weight.DemiBold))
    painter.drawText(62, 103, 'La burbuja refracta lo que hay detrás.')

    for x, title, frame in ((60, 'En reposo', resting), (620, 'Mientras se mueve', moving)):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#292725'))
        painter.drawRoundedRect(x, 142, 520, 478, 22, 22)
        painter.setPen(QPen(QColor(255, 255, 255, 34), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(x + .5, 142.5, 519, 477, 22, 22)
        area = x + 60
        painter.drawImage(area, 166, source)
        painter.drawImage(area, 166, frame)
        painter.setPen(QColor('#f3eee6'))
        painter.setFont(QFont('Segoe UI', 16, QFont.Weight.DemiBold))
        painter.drawText(x + 24, 599, title)

    painter.setPen(QColor('#aaa39a'))
    painter.setFont(QFont('Segoe UI', 11))
    painter.drawText(62, 666, 'La imagen se genera desde src/gpu_lens.py. No captura ni publica el escritorio del usuario.')
    painter.end()

    destination = ROOT / 'assets' / 'readme' / 'liquid-glass-bubble.png'
    if not canvas.save(str(destination), 'PNG'):
        raise OSError(f'No se pudo guardar {destination}')
    print(f'Imagen guardada: {destination}')


if __name__ == '__main__':
    main()
