"""Timer's full-screen reminder, using a single in-memory desktop snapshot."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from windows_glass import apply_capture_affinity, bind, set_affinity, user


class MonitorInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT),
                ('flags', wintypes.DWORD), ('device', wintypes.WCHAR * 32)]


def active_screen():
    if QApplication.platformName() == 'windows':
        foreground = bind(user, 'GetForegroundWindow', wintypes.HWND)
        monitor_from_window = bind(user, 'MonitorFromWindow', wintypes.HANDLE, wintypes.HWND, wintypes.DWORD)
        monitor_info = bind(user, 'GetMonitorInfoW', wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
        monitor = monitor_from_window(foreground(), 0)
        info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
        if monitor and monitor_info(monitor, ctypes.byref(info)):
            for screen in QApplication.screens():
                if screen.name().casefold() == info.device.casefold():
                    return screen
    return QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()


def capture_screen(screen):
    excluded = []
    try:
        if QApplication.platformName() == 'windows':
            for window in QApplication.topLevelWidgets():
                if window.isVisible() and set_affinity(int(window.winId()), 0x11):
                    excluded.append(window)
        return screen.grabWindow(0).toImage()
    finally:
        for window in excluded:
            apply_capture_affinity(window)


def gaussian_backdrop(image, divisor):
    """Blur at reduced resolution with a separable nine-tap Gaussian approximation."""
    import numpy as np

    if image.isNull():
        return image
    reduced = image.scaled(max(1, image.width() // divisor), max(1, image.height() // divisor),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    reduced = reduced.convertToFormat(QImage.Format.Format_RGBX8888)
    height, width = reduced.height(), reduced.width()
    pixels = np.frombuffer(reduced.constBits(), dtype=np.uint8).reshape(height, width, 4)
    weights = (1, 8, 28, 56, 70, 56, 28, 8, 1)
    for axis in (0, 1):
        padding = ((4, 4), (0, 0), (0, 0)) if axis == 0 else ((0, 0), (4, 4), (0, 0))
        padded = np.pad(pixels, padding, mode='edge')
        total = np.zeros(pixels.shape, dtype=np.uint16)
        for offset, weight in enumerate(weights):
            samples = (padded[offset:offset + height] if axis == 0
                       else padded[:, offset:offset + width])
            total += samples.astype(np.uint16) * weight
        pixels = (total >> 8).astype(np.uint8)
    return QImage(pixels.data, width, height, width * 4, QImage.Format.Format_RGBX8888).copy()


class FocusAlert(QDialog):
    def __init__(self, parent, countdown, stop, *, screen=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('Cicerón · enfoque')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.screen_to_cover = screen or active_screen()
        self.countdown_text = countdown
        self.backdrop = QImage()
        self.card_backdrop = QImage()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.card = QWidget(self)
        self.card.setFixedWidth(min(488, max(1, self.screen_to_cover.geometry().width() - 32)))
        layout.addWidget(self.card, alignment=Qt.AlignmentFlag.AlignCenter)
        box = QVBoxLayout(self.card)
        box.setContentsMargins(28, 30, 28, 22)
        box.setSpacing(12)
        title = self.label('Volvé a tu objetivo', 28, '#1d1d1f', 650)
        box.addWidget(title)
        box.addWidget(self.label('Esta ventana te está distrayendo. Retomá lo que te propusiste.', 15, '#424242'))
        self.countdown = self.label('', 48, '#c51b31', 650)
        self.countdown.setAccessibleName('Tiempo restante')
        box.addWidget(self.countdown)

        dismiss = QPushButton('Cerrar', self.card)
        dismiss.setObjectName('dismiss')
        dismiss.clicked.connect(self.accept)
        box.addWidget(dismiss, alignment=Qt.AlignmentFlag.AlignHCenter)
        disable = QPushButton('Detener avisos', self.card)
        disable.setObjectName('disable')
        disable.clicked.connect(stop)
        box.addWidget(disable, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.card.setStyleSheet("""
            QLabel { background: transparent; }
            QPushButton { color: #242424; border: none; padding: 7px 18px; border-radius: 13px;
                          font: 600 14px 'Segoe UI'; }
            QPushButton#dismiss { background-color: rgba(0, 0, 0, 18); min-width: 88px; }
            QPushButton#disable { color: #505050; background: transparent; font-weight: 400; }
            QPushButton#dismiss:hover, QPushButton#dismiss:focus,
            QPushButton#disable:hover, QPushButton#disable:focus { background-color: rgba(0, 0, 0, 30); }
        """)
        self.refresh_timer = QTimer(self, interval=1000)
        self.refresh_timer.timeout.connect(self.refresh_countdown)
        self.finished.connect(self.refresh_timer.stop)
        self.refresh_countdown()
        dismiss.setFocus()

    def label(self, text, size, color, weight=400):
        label = QLabel(text, self.card)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {color}; font: {weight} {size}px 'Segoe UI';")
        return label

    def refresh_countdown(self):
        text = self.countdown_text()
        if text != self.countdown.text():
            self.countdown.setText(text)

    def present(self):
        snapshot = capture_screen(self.screen_to_cover)
        density = self.screen_to_cover.devicePixelRatio()
        self.backdrop = gaussian_backdrop(snapshot, max(4, round(5 * density)))
        self.card_backdrop = gaussian_backdrop(snapshot, max(12, round(17 * density)))
        self.setScreen(self.screen_to_cover)
        self.setGeometry(self.screen_to_cover.geometry())
        self.show()
        self.activateWindow()
        self.refresh_timer.start()

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
            painter.fillRect(self.rect(), QColor('#dddddd'))
            if not self.backdrop.isNull():
                painter.drawImage(self.rect(), self.backdrop)
            painter.fillRect(self.rect(), QColor(248, 248, 248, 47))

            card = QPainterPath()
            card.addRoundedRect(QRectF(self.card.geometry()), 32, 32)
            painter.setClipPath(card)
            if not self.card_backdrop.isNull():
                painter.drawImage(self.rect(), self.card_backdrop)
            painter.fillRect(self.card.geometry(), QColor(250, 250, 250, 204))
