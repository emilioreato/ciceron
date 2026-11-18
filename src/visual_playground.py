"""Two switches for Cicerón's desktop effects."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from center_ui import GlassDialog


class VisualDialog(GlassDialog):
    def __init__(self, parent=None, attached=False, dock_provider=None):
        super().__init__(parent, attached=attached)
        self.dock_provider = dock_provider
        self.setWindowTitle('Efectos de escritorio')
        self.floating = self.glass and not attached
        if self.floating:
            self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
                                Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.set_live(False)
        self.resize(280 if attached else 320, 142 if attached else 168)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(8)
        title = QLabel('Efectos de escritorio')
        title.setObjectName('heading')
        if self.floating:
            header = QHBoxLayout()
            header.addWidget(title, 1)
            dismiss = QPushButton('×')
            dismiss.setObjectName('quiet')
            dismiss.setAccessibleName('Cerrar efectos de escritorio')
            dismiss.setFixedSize(30, 30)
            dismiss.setStyleSheet('QPushButton { min-height: 0; padding: 0; font-size: 19px; }')
            dismiss.setAutoDefault(False)
            dismiss.clicked.connect(self.reject)
            header.addWidget(dismiss)
            box.addLayout(header)
        else:
            box.addWidget(title)
        self.bubble = EffectSwitch('Burbuja', self.toggle_bubble)
        self.particles = EffectSwitch('Partículas', self.toggle_particles)
        box.addWidget(self.bubble)
        box.addWidget(self.particles)
        if self.floating:
            self.setTabOrder(self.bubble, self.particles)
            self.setTabOrder(self.particles, dismiss)
            self.bubble.setFocus()
        self.sync()

    def set_live(self, live):
        super().set_live(live)
        if getattr(self, 'floating', False):
            self.setStyleSheet(self.styleSheet() + '\nQDialog { background: transparent; }')
            self.update()

    def paintEvent(self, event):
        if not self.floating:
            super().paintEvent(event)
        elif not self.live:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(33, 39, 51, 225) if self.dark else QColor(248, 249, 252, 229))
            painter.setPen(QPen(QColor(255, 255, 255, 175), 1))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 19, 19)

    def sync(self):
        app = QApplication.instance()
        bubble = getattr(app, '_ciceron_overlay', None)
        self.bubble.update_state(bubble is not None and bubble.isVisible())
        self.particles.update_state(bool(getattr(app, '_ciceron_particles', [])))

    def toggle_bubble(self, enabled):
        app = QApplication.instance()
        if not enabled:
            current = getattr(app, '_ciceron_overlay', None)
            if current is not None:
                current.close()
            app._ciceron_overlay = None
        else:
            try:
                from gpu_lens import DesktopBubble
                bubble = DesktopBubble(dock_provider=self.dock_provider)
                bubble.start()
                app._ciceron_overlay = bubble
            except (ImportError, OSError, RuntimeError) as error:
                QMessageBox.warning(self, 'Burbuja no disponible', str(error))
        self.sync()


    def toggle_particles(self, enabled):
        from desktop_bubble import DesktopParticles
        app = QApplication.instance()
        if enabled:
            surface = DesktopParticles()
            app._ciceron_particles = [surface]
            surface.show()
        else:
            for surface in getattr(app, '_ciceron_particles', []):
                surface.close()
            app._ciceron_particles = []
        self.sync()


class EffectSwitch(QPushButton):
    def __init__(self, text, command):
        super().__init__(text)
        self.setObjectName('effectSwitch')
        self.setCheckable(True)
        self.clicked.connect(command)

    def update_state(self, active):
        self.setChecked(active)
        state = 'Activado' if active else 'Desactivado'
        self.setAccessibleDescription(state)
        self.setToolTip(state)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#2db47b' if self.isChecked() else '#e5656c'))
        painter.drawEllipse(QRectF(self.width() - 20, self.height() / 2 - 4, 8, 8))
