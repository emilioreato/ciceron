"""Prueba la lente en una GPU real con una cuadrícula y cursor simulado."""
import sys,traceback
from time import perf_counter
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtCore import QPoint,QPointF,Qt,QTimer
from PySide6.QtGui import QColor,QImage,QLinearGradient,QPainter,QPen
from PySide6.QtWidgets import QApplication
from gpu_lens import DesktopBubble

app=QApplication([])
def run():
    bubble=None
    try:
        screen=app.primaryScreen(); center=screen.availableGeometry().center()
        with patch('gpu_lens.QCursor') as cursor:
            cursor.pos.return_value=center
            bubble=DesktopBubble();bubble.start();app.processEvents()
            assert bubble.isValid() and not bubble.gl_error
            assert bubble.windowFlags() & Qt.WindowType.WindowTransparentForInput
            cursor.pos.return_value=center+QPoint(24,16);bubble.follow_cursor()
            assert abs(bubble.geometry().center().x()-center.x()-24)<=1
            assert abs(bubble.geometry().center().y()-center.y()-16)<=1
            image=QImage(400,400,QImage.Format.Format_RGBA8888);image.fill(QColor('white'))
            p=QPainter(image);p.fillRect(0,0,200,400,QColor('black'));p.setPen(QPen(QColor('#888888'),3))
            for n in range(20,400,40):p.drawLine(n,0,n,399);p.drawLine(0,n,399,n)
            p.end(); bubble.timer.stop()
            bubble.motion = QPointF()
            bubble.frame=image;bubble.frame_dirty=True;bubble.update();app.processEvents()
            result=bubble.grabFramebuffer();assert not result.isNull()
            w,h=result.width(),result.height()
            assert result.pixelColor(0,0).alpha()<10
            assert result.pixelColor(w//2,h//2).alpha()>245
            assert result.pixelColor(w//4,h//2).lightness()<100
            assert result.pixelColor(3*w//4,h//2).lightness()>150
            # Neutral source must stay neutral: no accidental RGB corruption.
            for x,y in [(w//4,h//2),(3*w//4,h//2),(w//2,h//4)]:
                c=result.pixelColor(x,y);assert max(c.red(),c.green(),c.blue())-min(c.red(),c.green(),c.blue())<=2
            # A vertical line away from the center should bend near the rim.
            lines=QImage(400,400,QImage.Format.Format_RGBA8888);lines.fill(QColor('white'))
            painter=QPainter(lines);painter.setPen(QPen(QColor('black'),5));painter.drawLine(280,0,280,399);painter.end()
            bubble.frame=lines;bubble.frame_dirty=True;bubble.update();app.processEvents()
            bent=bubble.grabFramebuffer();size=bent.width()
            def line_x(y):
                interior = (x for x in range(int(size*.68), int(size*.82))
                            if bent.pixelColor(x, y).alpha() > 240)
                return min(interior, key=lambda x: bent.pixelColor(x, y).green())
            assert line_x(size//8) > line_x(size//2), 'El borde no curva la línea hacia el contorno.'
            fringe = [abs(color.red() - color.blue()) for y in range(size) for x in range(size)
                      if (color := bent.pixelColor(x, y)).alpha() > 245]
            assert 40 <= max(fringe) <= 94, f'Separación de canales fuera del rango esperado: {max(fringe)}.'
            y = size // 2
            assert all(abs(bent.pixelColor(x, y).red() - bent.pixelColor(x, y).blue()) <= 2
                       for x in range(size // 7, size * 6 // 7)), 'El color invade el centro.'
            # Slide the background under stationary glass at native resolution.
            # Its first few pixels disappear, then a compressed dark strip emerges.
            lip = round(size * 0.9875)
            def visible_strip(penetration):
                strip = QImage(size, size, QImage.Format.Format_RGBA8888)
                strip.fill(QColor('white'))
                painter = QPainter(strip)
                painter.fillRect(lip - penetration, 0, size, size, QColor('black'))
                painter.end()
                bubble.frame, bubble.frame_dirty = strip, True
                frame = bubble.grabFramebuffer()
                return sum(frame.pixelColor(x, size // 2).green() < 100
                           for x in range(size // 2, lip)
                           if frame.pixelColor(x, size // 2).alpha() > 245)
            assert visible_strip(round(size * .025)) == 0
            penetration = round(size * .18)
            assert 0 < visible_strip(penetration) < penetration
            assert visible_strip(size // 3) > penetration
            # At the diagonal lip the black band touches glass over a white
            # background pixel. The white cap is still visible at the apex.
            band = QImage(size, size, QImage.Format.Format_RGBA8888)
            band.fill(QColor('white'))
            painter = QPainter(band)
            painter.fillRect(0, round(size * .215), size, size, QColor('black'))
            painter.end()
            bubble.frame, bubble.frame_dirty = band, True
            contact = bubble.grabFramebuffer()
            tip = round(size * .16)
            for x in (tip, size - 1 - tip):
                pixel = contact.pixelColor(x, tip)
                assert pixel.alpha() > 230 and pixel.green() < 70
            assert contact.pixelColor(size // 2, round(size * .03)).green() > 190
            bubble.frame, bubble.frame_dirty = lines, True
            bubble.motion = QPointF(0.8, -0.45)
            rippled = bubble.grabFramebuffer()
            assert rippled.pixelColor(size//2, size//2) == bent.pixelColor(size//2, size//2)
            changes = sum(
                rippled.pixelColor(x, y) != bent.pixelColor(x, y)
                for y in range(0, size, 3) for x in range(0, size, 3)
            )
            assert changes > 50, 'El movimiento no modifica suficientemente el borde.'
            flat = QImage(size, size, QImage.Format.Format_RGBA8888)
            flat.fill(QColor('#c8c8c8'))
            bubble.frame, bubble.frame_dirty = flat, True
            for motion in (QPointF(), QPointF(.8, -.45)):
                bubble.motion = motion
                neutral = bubble.grabFramebuffer()
                assert all(max(pixel.red(), pixel.green(), pixel.blue()) -
                           min(pixel.red(), pixel.green(), pixel.blue()) <= 1
                           for y in range(size) for x in range(size)
                           if (pixel := neutral.pixelColor(x, y)).alpha() > 245), 'Hay tinte sobre un fondo neutro.'
            gradient = QImage(160, 160, QImage.Format.Format_RGBA8888)
            paint = QPainter(gradient)
            light = QLinearGradient(0, 0, 159, 0)
            light.setColorAt(0, QColor('black'))
            light.setColorAt(1, QColor('white'))
            paint.fillRect(gradient.rect(), light)
            paint.end()
            bubble.frame, bubble.frame_dirty = gradient, True
            # Compare both frames at the same phase of the decorative ripple.
            with patch('gpu_lens.time.monotonic', return_value=bubble.started):
                bubble.motion = QPointF()
                resting = bubble.grabFramebuffer()
                bubble.motion = QPointF(1, 0)
                entering = bubble.grabFramebuffer()
            w, y = entering.width(), entering.height() // 2
            assert any(resting.pixelColor(x, y).green() - entering.pixelColor(x, y).green() > 6
                       for x in range(int(w*.93), int(w*.985))
                       if entering.pixelColor(x, y).alpha() > 235
                       and resting.pixelColor(x, y).alpha() > 235), 'El labio no retrasa el detalle entrante.'
            # A large cursor step can outrun DXGI; the glass must keep its last frame.
            origin = bubble.pos() - QPoint(24, 24)
            scale = bubble.devicePixelRatioF()
            pixels = round((bubble.width() + 48) * scale)
            tile = np.full((pixels, pixels, 4), (80, 110, 140, 255), dtype=np.uint8)
            bubble.frame = None
            bubble.native_frame = ((origin.x(), origin.y(), scale), pixels, tile, perf_counter())
            bubble.frame_dirty = True
            bubble.motion = QPointF()
            before_jump = bubble.grabFramebuffer()
            bubble.move(bubble.pos() + QPoint(bubble.width() * 2, 0))
            assert not bubble.tile_covers_window(bubble.native_frame)
            after_jump = bubble.grabFramebuffer()
            center_x, center_y = after_jump.width() // 2, after_jump.height() // 2
            assert after_jump.pixelColor(center_x, center_y) == before_jump.pixelColor(center_x, center_y)
            assert after_jump.pixelColor(center_x, center_y).alpha() == 255
        worker = bubble.worker
        app.setProperty('captureMode', True)
        bubble.update_capture_mode()
        assert not bubble.timer.isActive() and bubble.worker is None and worker.closed.is_set()
        app.setProperty('captureMode', False)
        bubble.update_capture_mode()
        assert bubble.timer.isActive()
        resumed_worker = bubble.worker
        bubble.close()
        assert not bubble.timer.isActive() and resumed_worker.closed.is_set()
        print('GPU: renderizado, bordes, gris neutro, seguimiento y cierre: correctos.')
        app.quit()
    except Exception:
        traceback.print_exc()
        if bubble is not None: bubble.close()
        app.exit(1)
QTimer.singleShot(0,run)
sys.exit(app.exec())
