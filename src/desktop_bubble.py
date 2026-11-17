"""Small click-through particle layer and lifecycle of the desktop effects."""
from math import ceil

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget


class DesktopParticles(QWidget):
    SIZE = 184
    RADIUS = 77
    GRID = 23
    SPRITE_SIZE = 8

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.pointer = QPoint(-10000, -10000)
        self.display = None
        self.rest = 0
        self.sprite = self.particle_sprite(self.devicePixelRatioF())
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.update_pointer)

    @classmethod
    def particle_sprite(cls, scale):
        pixels = ceil(cls.SPRITE_SIZE * scale)
        sprite = QPixmap(pixels, pixels)
        sprite.setDevicePixelRatio(scale)
        sprite.fill(Qt.GlobalColor.transparent)
        painter = QPainter(sprite)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = sprite.deviceIndependentSize().width() / 2
        point = QPointF(center, center)
        glow = QRadialGradient(point, cls.SPRITE_SIZE / 2)
        glow.setColorAt(0, QColor(134, 211, 255, 104))
        glow.setColorAt(.62, QColor(134, 211, 255, 50))
        glow.setColorAt(1, QColor(134, 211, 255, 0))
        painter.fillRect(QRectF(0, 0, center * 2, center * 2), glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(32, 62, 87, 222))
        painter.drawEllipse(point, 2.33, 2.33)
        painter.setBrush(QColor(231, 252, 255))
        painter.drawEllipse(point, 1.55, 1.55)
        painter.end()
        return sprite

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(9)
        self.update_pointer()

    def update_pointer(self):
        position = QCursor.pos()
        if position == self.pointer:
            self.rest += 1
            if self.rest >= 8 and self.timer.interval() < 24:
                self.timer.setInterval(24)
            return
        if self.display is None or not self.display.geometry().contains(position):
            self.display = QApplication.screenAt(position)
        scale = self.display.devicePixelRatio() if self.display else self.devicePixelRatioF()
        if self.sprite.devicePixelRatio() != scale:
            self.sprite = self.particle_sprite(scale)
        refresh = self.display.refreshRate() if self.display else 60
        interval = max(7, round(1000 / max(30, min(144, refresh))))
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        self.rest = 0
        self.pointer = position
        self.move(position - QPoint(self.SIZE // 2, self.SIZE // 2))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        half = self.SIZE // 2
        sprite_half = self.sprite.deviceIndependentSize().width() / 2
        px, py = self.pointer.x(), self.pointer.y()
        grid, radius = self.GRID, self.RADIUS
        for y in range((py-radius)//grid*grid, py+radius+1, grid):
            dy = y - py
            for x in range((px-radius)//grid*grid, px+radius+1, grid):
                dx = x - px
                square = dx*dx + dy*dy
                if square >= radius*radius:
                    continue
                distance = square ** .5
                depth = 1 - distance / radius
                push = 1 + depth * depth * 23 / max(distance, 1)
                painter.setOpacity(.18 + depth * .78)
                painter.drawPixmap(QPointF(half + dx*push - sprite_half,
                                           half + dy*push - sprite_half), self.sprite)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)


def stop_desktop_effects():
    app = QApplication.instance()
    bubble = getattr(app, '_ciceron_overlay', None)
    if bubble is not None:
        bubble.close()
    app._ciceron_overlay = None
    for window in getattr(app, '_ciceron_particles', []):
        window.close()
    app._ciceron_particles = []
