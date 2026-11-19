"""Right-edge application dock with the desktop lens behind each icon."""
import ctypes
from ctypes import wintypes
import math
import time

from OpenGL import GL
from PySide6.QtCore import (QAbstractNativeEventFilter, QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation,
                           QRect, QRectF, Qt, QTimer)
from PySide6.QtGui import (
    QColor, QCursor, QIcon, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRegion, QShortcut, QSurfaceFormat
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QDialog, QMenu, QScrollArea,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from gpu_lens import backdrop_is_light, compile_lens, make_lens_texture, paint_optic
from lens_capture import DockBackdropCapture
from windows_glass import (PanelMousePress, client_bounds, energy_saver_active, foreground_window, forward_wheel,
                           is_external_window, root_window, apply_capture_affinity, capture_mode, window_belongs_to)


def tool_icon(name, *, light_background=False):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2, 2)
    path = QPainterPath()
    if name == 'lens':
        path.addEllipse(QRectF(4.8, 4.8, 22.4, 22.4))
        for rect, angle, extent in ((QRectF(8.1, 8.1, 15.8, 15.8), 23, 77),
                                    (QRectF(7.5, 10.5, 17, 12), 185, 93)):
            path.arcMoveTo(rect, angle)
            path.arcTo(rect, angle, extent)
    elif name == 'settings':
        outline = []
        for tick in range(32):
            angle = tick * math.pi / 16
            radius = 11 if tick % 4 in (1, 2) else 8.7
            outline.append(QPointF(16 + radius * math.cos(angle), 16 + radius * math.sin(angle)))
        path.moveTo(outline[0])
        for point in outline[1:]:
            path.lineTo(point)
        path.closeSubpath()
        path.addEllipse(QRectF(12.2, 12.2, 7.6, 7.6))
    elif name == 'search':
        path.addEllipse(QRectF(5, 5, 16, 16))
        path.moveTo(19, 19)
        path.lineTo(27, 27)
    elif name == 'clock':
        path.addEllipse(QRectF(5, 5, 22, 22))
        path.moveTo(16, 10)
        path.lineTo(16, 16)
        path.lineTo(21, 18)
    elif name == 'gift':
        path.moveTo(6, 12)
        path.lineTo(26, 12)
        path.lineTo(26, 16)
        path.lineTo(6, 16)
        path.closeSubpath()
        path.moveTo(8, 16)
        path.lineTo(8, 26)
        path.lineTo(24, 26)
        path.lineTo(24, 16)
        path.moveTo(16, 16)
        path.lineTo(16, 26)
        path.moveTo(16, 12)
        path.cubicTo(13.3, 10.6, 8.6, 8.2, 9.4, 5.2)
        path.cubicTo(10, 2.8, 13.2, 4.2, 16, 12)
        path.moveTo(16, 12)
        path.cubicTo(18.7, 10.6, 23.4, 8.2, 22.6, 5.2)
        path.cubicTo(22, 2.8, 18.8, 4.2, 16, 12)
    else:
        path.addEllipse(QRectF(5, 5, 22, 22))
        path.addEllipse(QRectF(11, 5, 10, 22))
        path.moveTo(5, 16)
        path.lineTo(27, 16)
    color = QColor('#343434' if light_background else '#ffffff')
    painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


class DockIcon(QToolButton):
    def __init__(self, parent, label, icon, action, wheel='passthrough'):
        super().__init__(parent)
        self.wheel = wheel
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.light_icon = tool_icon(icon, light_background=True) if isinstance(icon, str) else None
        self.setIcon(tool_icon(icon) if self.light_icon is not None else icon)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(action)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QRectF(self.rect()).center()
        dock = self.parentWidget()
        opacity = max(0.0, min(1.0, (dock.progress - .76) / .24))
        painter.setOpacity(opacity * opacity * (3 - 2 * opacity))
        if self.hasFocus():
            painter.setPen(QPen(QColor('#e5e5e5'), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(center.x() - 19, center.y() - 19, 38, 38), 10, 10)
        size = round(min(self.width(), self.height()) * .68)
        if size > 0:
            area = QRect(round(center.x() - size / 2), round(center.y() - size / 2), size, size)
            light = (dock.layer.light if dock.glass_enabled and dock.layer.light is not None else
                     not (dock.theme_dark or dock.pure))
            icon = self.light_icon if light and self.light_icon is not None else self.icon()
            icon.paint(painter, area)


class DockHandle(QToolButton):
    ARROW_RIGHT_INSET = 5
    HIT_WIDTH = 18
    HIT_HEIGHT = 74

    def hit_path(self):
        rectangle = QRectF(self.width() - self.HIT_WIDTH,
                           (self.height() - self.HIT_HEIGHT) / 2,
                           self.HIT_WIDTH, self.HIT_HEIGHT)
        path = QPainterPath()
        path.addRoundedRect(rectangle, self.HIT_WIDTH / 2, self.HIT_WIDTH / 2)
        return path

    def hit_region(self):
        return QRegion(self.hit_path().toFillPolygon().toPolygon()).intersected(QRegion(self.rect()))

    def mouseMoveEvent(self, event):
        self.parentWidget().probe_hover()
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event):
        dock = self.parentWidget()
        menu = QMenu(self)
        hide_action = menu.addAction('Ocultar barra lateral')
        if menu.exec(event.globalPos()) is hide_action:
            dock.hide()
        event.accept()

    def paintEvent(self, event):
        dock = self.parentWidget()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        opacity = 1 - min(1.0, dock.progress / dock.HANDLE_OPACITY_END)
        if opacity <= 0:
            return
        painter.setOpacity(opacity * opacity * (3 - 2 * opacity))
        center = QPointF(self.width() - self.ARROW_RIGHT_INSET, self.height() / 2)
        arrow = QPainterPath(center + QPointF(1.5, -4))
        arrow.lineTo(center + QPointF(-2, 0))
        arrow.lineTo(center + QPointF(1.5, 4))
        light = (dock.layer.light if dock.glass_enabled and dock.layer.light is not None else
                 not (dock.theme_dark or dock.pure))
        ink = QColor('#343434' if light else '#f0f0f0')
        painter.setPen(QPen(ink, 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(arrow)


class DockEdgeHover(QWidget):
    def hit_path(self):
        width, height = DockHandle.HIT_WIDTH, DockHandle.HIT_HEIGHT
        rectangle = QRectF(self.width() - width, (self.height() - height) / 2, width, height)
        path = QPainterPath()
        path.addRoundedRect(rectangle, width / 2, width / 2)
        return path

    def hit_region(self):
        return QRegion(self.hit_path().toFillPolygon().toPolygon()).intersected(QRegion(self.rect()))

    def paintEvent(self, event):
        # Preserve a tiny native hit surface after the arrow fades, with the
        # same pill contour rather than a rectangular edge strip.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(self.hit_path(), QColor(255, 255, 255, 1))


class DockOptics(QOpenGLWidget):
    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide):
            owner = self.parentWidget()
            if obj is not self and isinstance(obj, QWidget) and owner.isAncestorOf(obj):
                self.update()
        return False

    def __init__(self, dock):
        super().__init__(dock)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setAlphaBufferSize(8)
        fmt.setSwapInterval(0)
        self.setFormat(fmt)
        self.program = None
        self.texture = None
        self.frame = None
        self.frame_bounds = None
        self.dirty = False
        self.texture_size = None
        self.error = None
        self.light = None
    def initializeGL(self):
        try:
            self.program, self.uniform = compile_lens()
            self.texture = make_lens_texture()
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
            self.texture_size = None
            self.dirty = True
        except Exception as error:
            self.error = str(error)

    def paintGL(self):
        GL.glClearColor(0, 0, 0, 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        owner = self.parentWidget()
        dock_fallback = isinstance(owner, EdgeDock) and owner.glass_enabled and owner.progress > 0
        if self.program is None or (self.frame is None and not dock_fallback):
            return
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        width, height = (self.frame.width(), self.frame.height()) if self.frame is not None else (1, 1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        if self.frame is not None and self.dirty:
            if self.texture_size == (width, height):
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, width, height,
                                  GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, self.frame.constBits())
            else:
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, width, height, 0,
                               GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, self.frame.constBits())
                self.texture_size = (width, height)
            GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
            self.dirty = False
        self.draw_glass(width)
        GL.glDisable(GL.GL_BLEND)

    def draw_glass(self, width):
        owner = self.parentWidget()
        dock = owner if isinstance(owner, EdgeDock) else owner.dock
        phase = time.monotonic() - dock.started
        viewport_w, viewport_h = self.width(), self.height()
        rect = owner.optic_rect()
        surface = (rect.x() / viewport_w, rect.y() / viewport_h,
                   rect.width() / viewport_w, rect.height() / viewport_h)
        current = client_bounds(int(owner.winId()))
        if current is None:
            return
        x, y, view_width, view_height = current
        left, top, captured_width, captured_height = self.frame_bounds or current
        physical_width, physical_height = surface[2] * view_width, surface[3] * view_height
        sample = ((x - left + surface[0] * view_width) / captured_width,
                  (y - top + surface[1] * view_height) / captured_height,
                  physical_width / captured_width, physical_height / captured_height)
        glass_mix = 1.0
        provisional = (0.0, 0.0, 0.0, 0.0)
        if owner is dock:
            if self.frame is None:
                glass_mix = 0.0
            light = self.light
            if light is None and dock.backdrop is None:
                light = not (dock.theme_dark or dock.pure)
            if light is not None:
                provisional = (.83, .83, .83, .28) if light else (.16, .16, .16, .28)
        if getattr(dock, 'pure', False):
            from window_glass import draw_clear_material
            draw_clear_material(self, self.program, self.uniform, rect, sample,
                                (physical_width, physical_height), owner.CORNER_RADIUS,
                                dock.glass_opacity() if owner is dock else 1.0,
                                controls=owner is not dock, light=bool(self.light),
                                glass_mix=glass_mix, provisional=provisional)
            return
        radius = owner.CORNER_RADIUS * view_width / viewport_w
        # Keep the shader's perimeter wave available; the dock rests still.
        paint_optic(self.program, self.uniform, physical_width, sample, QPointF(), phase,
                    ((-1, -1), (1, -1), (1, 1), (-1, 1)),
                    appearance=1.0 - .50 * dock.transparency,
                    body_height=physical_height, surface=surface,
                    panel_radius=min(physical_width / 2, physical_height / 2, radius),
                    glass_tone=float(bool(self.light)),
                    glass_blur=(2.35 if owner is dock else 3.2) - math.log2(captured_width / width),
                    glass_opacity=dock.glass_opacity() if owner is dock else 1.0,
                    glass_mix=glass_mix, provisional=provisional)

    def set_frame(self, frame, bounds, *, notify_parent=True):
        changed = self.frame_bounds != bounds or self.frame is not frame
        if changed:
            self.frame_bounds = bounds
            self.frame = frame
            self.dirty = True
        # Commit the detected tone with this exact frame, so the shader never
        # paints a dark capture using the previous bright-frame treatment.
        light = backdrop_is_light(frame, self.light)
        tone_changed = light != self.light
        if tone_changed:
            self.light = light
            if notify_parent and self.parentWidget().using_glass:
                self.parentWidget().apply_glass_tone(light)
        changed = changed or tone_changed
        if changed:
            self.update()
        return tone_changed

class AttachedPanel(QWidget):
    CORNER_RADIUS = 19
    INSET = 3
    CONTENT_MARGIN = 9

    def __init__(self, dock):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName('dockPanel')
        self.dock = dock
        self.content = None
        self.closing = False
        self.using_glass = False
        self.seeded_light = None
        self.capture_enabled = False
        self.capture_tile = None
        self.pending_geometry = None
        self.layer = DockOptics(self)
        self.layer.hide()
        self.apply_glass_tone(not dock.theme_dark)
        outer = QVBoxLayout(self)
        margin = self.CONTENT_MARGIN
        outer.setContentsMargins(margin, margin, margin, margin)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName('attachedViewport')
        self.stack = QStackedWidget()
        self.subpanel = None
        self.scroll.setWidget(self.stack)
        self.scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self.scroll)
        self.scroll.verticalScrollBar().valueChanged.connect(self.layer.update)
        self.resize(320, 220)
        self.shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        self.resize_animation = QPropertyAnimation(self, b'geometry', self)
        self.resize_animation.setDuration(180)
        self.resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.resize_animation.finished.connect(self.finish_resize)
        self.resize_wait_timer = QTimer(self)
        self.resize_wait_timer.setSingleShot(True)
        self.resize_wait_timer.setInterval(120)
        self.resize_wait_timer.timeout.connect(self.settle_resize)
        self.open_animation = QPropertyAnimation(self, b'windowOpacity', self)
        self.open_animation.setDuration(155)
        self.open_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def load_content(self, key, content, persistent):
        self.key, self.content, self.persistent = key, content, persistent
        self.closing = False
        preferred = content.size()
        self.original = (content.parentWidget(), content.windowFlags(), content.objectName(), preferred)
        self.setWindowTitle(content.windowTitle())
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if persistent
                                               else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.embed(content)
        margin = 2 * self.CONTENT_MARGIN
        self.resize(preferred.width() + margin, preferred.height() + margin)
        if isinstance(content, QDialog):
            content.finished.connect(self.dialog_finished)
        if hasattr(content, 'preferred_size_changed'):
            content.preferred_size_changed.connect(self.fit_content)

    def show_panel(self):
        start = .20 if self.dock.motion_enabled else 1.0
        self.setWindowOpacity(start)
        self.show()
        self.raise_()
        self.activateWindow()
        if start < 1:
            self.open_animation.setStartValue(start)
            self.open_animation.setEndValue(1.0)
            self.open_animation.start()

    def fit_content(self):
        if self.content.layout() is not None:
            self.content.layout().activate()
        self.content.ensurePolished()
        self.scroll.verticalScrollBar().setValue(0)
        height = self.content.sizeHint().height() + 2 * self.CONTENT_MARGIN
        expand_down = self.isVisible() and self.content.property('expandDown')
        target = self.dock.panel_geometry(self, height, keep_top=expand_down)
        self.resize_animation.stop()
        self.resize_wait_timer.stop()
        self.capture_tile = self.pending_geometry = None
        if not self.isVisible() or not self.dock.motion_enabled:
            self.setGeometry(target)
            self.finish_resize()
        elif target != self.geometry():
            current = client_bounds(int(self.winId())) if self.using_glass and not capture_mode() else None
            if current is not None:
                x, y, width, height = current
                scale = self.devicePixelRatioF()
                target_x = x + round((target.x() - self.x()) * scale)
                target_y = y + round((target.y() - self.y()) * scale)
                target_width = math.ceil(target.width() * scale)
                target_height = math.ceil(target.height() * scale)
                left, top = min(x, target_x), min(y, target_y)
                right = max(x + width, target_x + target_width)
                bottom = max(y + height, target_y + target_height)
                self.capture_tile = (left, top, right - left, bottom - top)
                self.pending_geometry = target
                self.resize_wait_timer.start()
                self.dock.capture()
            else:
                self.animate_to(target)
        else:
            self.finish_resize()

    def animate_to(self, target):
        self.resize_wait_timer.stop()
        self.pending_geometry = None
        if not self.dock.motion_enabled:
            self.setGeometry(target)
            self.finish_resize()
            return
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.resize_animation.setStartValue(self.geometry())
        self.resize_animation.setEndValue(target)
        self.resize_animation.start()

    def finish_resize(self):
        self.resize_wait_timer.stop()
        self.pending_geometry = self.capture_tile = None
        policy = (Qt.ScrollBarPolicy.ScrollBarAlwaysOff if self.persistent and self.subpanel is None
                  else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(policy)
        self.dock.capture()

    def resize_target(self):
        if self.pending_geometry is not None:
            return self.pending_geometry
        if self.resize_animation.state() == QPropertyAnimation.State.Running:
            return self.resize_animation.endValue()
        return None

    def settle_resize(self):
        target = self.resize_target()
        if target is not None:
            self.resize_animation.stop()
            self.setGeometry(target)
            self.finish_resize()

    def optic_rect(self):
        pad = self.INSET
        return QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)

    def apply_glass_tone(self, light):
        from center_ui import clear_styles, stylesheet
        tone_ready = self.layer.frame is not None or self.seeded_light is not None
        live_light = bool(light) and tone_ready
        if light is None or not tone_ready:
            light = not self.dock.theme_dark
        self.dark = not live_light if self.dock.pure else not self.dock.monochrome and not light
        line = '255,255,255' if self.dark else '0,0,0'
        monochrome = bool(getattr(self.dock, 'monochrome', False))
        ink = '#f5f6f8' if self.dark else '#202020'
        muted = '#bdc1c9' if self.dark else '#656565'
        menu = '#292b30' if self.dark else '#ffffff'
        diffused = self.dock.glass_enabled and not self.dock.pure
        if self.dark:
            fill = 'rgba(65,65,65,175)'
            hover = '#515151'
        else:
            fill = '#ffffff' if monochrome else 'rgba(247,248,250,185)'
            hover = '#e7edf8' if diffused else '#e7e9ed'
        button_fill = '#111111' if monochrome else fill
        button_ink = '#ffffff' if monochrome else ink
        button_hover = '#303030' if monochrome else hover
        quiet_fill = button_fill if monochrome else 'transparent'
        quiet_ink = button_ink if monochrome else ('white' if self.dark else '#202020')
        tabs_fill = '#eeeeee' if monochrome else f'rgba({line},24)'
        selected_tab_fill = button_fill if monochrome else fill
        selected_tab_ink = button_ink if monochrome else ink
        self.setStyleSheet(stylesheet(self.dark, False, monochrome=monochrome,
                                      neutral=not monochrome and not diffused) + f'''
            QWidget#dockContent, QDialog#dockContent, QWidget#attachedViewport {{ background: transparent; }}
            QWidget#dockPanel QFrame#card, QWidget#dockPanel QFrame#timeCard {{
                background: transparent; border: 0; border-radius: 12px;
            }}
            QWidget#dockPanel QPushButton {{
                background: {button_fill}; color: {button_ink}; border: 1px solid transparent; border-radius: 9px;
            }}
            QWidget#dockPanel QPlainTextEdit, QWidget#dockPanel QLineEdit, QWidget#dockPanel QComboBox,
            QWidget#dockPanel QDateEdit, QWidget#dockPanel QTimeEdit {{
                background: {fill}; color: {ink}; border: 1px solid transparent; border-radius: 9px;
                placeholder-text-color: {muted};
            }}
            QWidget#dockPanel QPushButton {{ padding: 5px 10px; }}
            QWidget#dockPanel QListWidget {{
                background: {fill}; color: {ink}; border: none; border-radius: 12px;
                padding: 4px 6px 9px;
            }}
            QWidget#dockPanel QListWidget::item {{ padding: 5px 8px; }}
            QWidget#dockPanel QListWidget::item:selected {{ background: {hover}; color: {ink}; }}
            QWidget#dockPanel QPushButton#quiet {{ background: {quiet_fill}; color: {quiet_ink}; }}
            QWidget#dockPanel QPushButton:hover, QWidget#dockPanel QPushButton:checked {{
                background: {button_hover}; border-color: transparent;
            }}
            QWidget#dockPanel QFrame#centerTabs {{
                background: {tabs_fill}; border: 1px solid rgba({line},46); border-radius: 13px;
            }}
            QWidget#dockPanel QFrame#centerTabs QPushButton#nav {{
                padding: 4px 8px; border-radius: 9px; background: transparent;
                border-color: transparent; color: {'white' if self.dark else '#202020'};
            }}
            QWidget#dockPanel QFrame#centerTabs QPushButton#nav:hover {{ background: rgba({line},26); }}
            QWidget#dockPanel QFrame#centerTabs QPushButton#nav:checked {{
                background: {selected_tab_fill}; color: {selected_tab_ink};
            }}
            QWidget#dockPanel QFrame#centerTabs QPushButton#nav:focus {{ border-color: #737373; }}
            QWidget#dockPanel QPushButton#advancedToggle {{ padding: 4px 9px; }}
            QWidget#dockPanel QPushButton#effectSwitch {{
                text-align: left; padding-left: 11px; padding-right: 27px;
            }}
            QWidget#dockPanel QPushButton:focus, QWidget#dockPanel QComboBox:focus,
            QWidget#dockPanel QLineEdit:focus, QWidget#dockPanel QPlainTextEdit:focus {{
                border-color: #737373;
            }}
            QWidget#dockPanel QPushButton#primary {{
                background: {button_fill}; color: {button_ink}; font-weight: 700;
            }}
            QWidget#dockPanel QComboBox QAbstractItemView {{
                background: {menu}; color: {ink}; selection-background-color: {hover}; selection-color: {ink};
            }}
            QWidget#dockPanel QScrollBar:vertical {{ width: 6px; }}
            QWidget#dockPanel QScrollBar::handle:vertical {{ background: rgba({line},88); }}
            QWidget#dockPanel QScrollArea#centerPage QScrollBar:vertical {{ width: 5px; }}
            QWidget#dockPanel QScrollArea#centerPage QScrollBar::handle:vertical:hover {{ background: rgba({line},160); }}
            QWidget#dockPanel QScrollArea#centerPage QScrollBar::handle:vertical:disabled {{ background: transparent; }}
        ''' + (clear_styles('QWidget#dockPanel', live_light,
                            frost_controls=self.using_glass and self.content is not None and
                            self.content.property('frostControls'), live_controls=self.using_glass)
               if self.dock.pure else ''))
        self.update()

    def prime_glass_tone(self, light=None):
        self.seeded_light = None if light is None else bool(light)
        self.apply_glass_tone(self.seeded_light)
        return self.seeded_light is not None

    def dialog_finished(self):
        if not self.closing:
            self.close()

    def embed(self, widget):
        widget.setParent(self.stack, Qt.WindowType.Widget)
        widget.setObjectName('dockContent')
        widget.setProperty('dockEmbedded', True)
        widget.setAutoFillBackground(False)
        self.stack.addWidget(widget)

    def open_subpanel(self, dialog):
        if self.subpanel is not None:
            self.subpanel.reject()
        self.subpanel = dialog
        self.embed(dialog)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.stack.setCurrentWidget(dialog)
        dialog.show()

        def restore():
            self.subpanel = None
            if not self.closing:
                self.stack.setCurrentWidget(self.content)
                if self.persistent:
                    self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.stack.removeWidget(dialog)
            dialog.deleteLater()

        dialog.finished.connect(restore)

    def paintEvent(self, event):
        if not self.using_glass:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            diffused = self.dock.glass_enabled and not self.dock.pure
            if diffused:
                base = QColor(35, 35, 35, 213) if self.dark else QColor(225, 235, 251, 213)
                rim = QColor(194, 194, 194, 130) if self.dark else QColor(168, 194, 236, 130)
            else:
                base = QColor('#212121' if self.dark else '#ffffff')
                rim = QColor(160, 160, 160, 255) if self.dark else QColor(210, 210, 210, 255)
            painter.setBrush(base)
            painter.setPen(QPen(rim, 1))
            painter.drawRoundedRect(self.optic_rect(), self.CORNER_RADIUS, self.CORNER_RADIUS)

    def prepare_layer(self, enabled):
        if enabled:
            self.layer.show()
            self.layer.lower()
            enabled = (self.layer.isValid() and not self.layer.error and
                       apply_capture_affinity(self, live=True))
        if not enabled:
            self.capture_enabled = False
            apply_capture_affinity(self, live=False)
            self.using_glass = False
            self.layer.hide()
            self.layer.frame = None
            seed = self.seeded_light if self.dock.glass_enabled and not capture_mode() else None
            self.seeded_light = seed
            self.layer.light = seed
            self.settle_resize()
            self.apply_glass_tone(seed)
            self.update()
        return enabled

    def resizeEvent(self, event):
        self.layer.setGeometry(self.rect())
        super().resizeEvent(event)

    def closeEvent(self, event):
        if self.closing:
            return
        self.closing = True
        self.open_animation.stop()
        self.resize_animation.stop()
        self.resize_wait_timer.stop()
        if self.subpanel is not None:
            self.subpanel.reject()
        content, self.content = self.content, None
        if content is not None:
            if isinstance(content, QDialog):
                content.finished.disconnect(self.dialog_finished)
            if hasattr(content, 'preferred_size_changed'):
                content.preferred_size_changed.disconnect(self.fit_content)
            if self.persistent:
                parent, flags, name, size = self.original
                content.hide()
                self.stack.removeWidget(content)
                content.setParent(parent, flags)
                content.setObjectName(name)
                content.setProperty('dockEmbedded', False)
                content.resize(size)
            else:
                if isinstance(content, QDialog) and content.isVisible():
                    content.reject()
                content.hide()
                self.stack.removeWidget(content)
                content.deleteLater()
        apply_capture_affinity(self, live=False)
        self.capture_enabled = self.using_glass = False
        self.capture_tile = self.pending_geometry = None
        self.seeded_light = None
        self.layer.frame = None
        self.layer.light = None
        self.dock.panel_closed(self)
        super().closeEvent(event)


class AppWheelFilter(QAbstractNativeEventFilter):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.previous_app = None
        self.remember_foreground()

    def remember_foreground(self):
        active = foreground_window()
        if is_external_window(active):
            self.previous_app = active

    def scrollable_widget_at_cursor(self, horizontal=False):
        widget = QApplication.widgetAt(QCursor.pos())
        while widget is not None and widget is not self.controller.window:
            if isinstance(widget, QAbstractScrollArea):
                bar = widget.horizontalScrollBar() if horizontal else widget.verticalScrollBar()
                return bar.maximum() > bar.minimum()
            widget = widget.parentWidget()
        return False

    def nativeEventFilter(self, event_type, message):
        if event_type != b'windows_generic_MSG':
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0021:  # WM_MOUSEACTIVATE, before the click takes focus
            self.remember_foreground()
        elif msg.message == 0x0006 and msg.wParam & 0xffff:  # WM_ACTIVATE
            previous = root_window(msg.lParam, 2) if msg.lParam else None
            if is_external_window(previous):
                self.previous_app = previous
        if msg.message not in (0x020A, 0x020E):
            return False, 0
        if self.scrollable_widget_at_cursor(horizontal=msg.message == 0x020E):
            return False, 0
        dock = self.controller.dock
        if dock is not None and dock.isVisible() and window_belongs_to(msg.hWnd, int(dock.winId())):
            icon = dock.childAt(dock.mapFromGlobal(QCursor.pos()))
            if isinstance(icon, DockIcon) and icon.wheel == 'consume':
                return True, 0
        self.remember_foreground()
        return forward_wheel(root_window(msg.hWnd, 2) or msg.hWnd, msg, self.previous_app), 0


class EdgeDock(QWidget):
    WIDTH = 55
    CAPSULE_WIDTH = 46
    EDGE_INSET = 2
    HANDLE_WIDTH = 26
    HANDLE_HEIGHT = 80
    PANEL_GAP = 6
    CORNER_RADIUS = 16
    STEP = 38
    DIAMETER = 34
    HOVER_DELAY_MS = 24
    HOVER_PROBE_MS = 40
    HIDE_DELAY = 0.04
    HANDLE_FADE_END = 0.90
    HANDLE_OPACITY_END = 0.62
    MAX_TRANSITION_STEP = 0.024

    def __init__(self, icon, open_settings, *, tray_geometry=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('Cicerón · Dock')
        self.setWindowIcon(icon)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.layer = DockOptics(self)
        self.panel = None
        self.panel_window = None
        self.panel_mouse_press = PanelMousePress()
        self.panel_session = 0
        self.tray_geometry = tray_geometry
        self.pending_panel = None
        self.pending_open_timer = QTimer(self)
        self.pending_open_timer.setSingleShot(True)
        self.pending_open_timer.timeout.connect(self.open_pending_panel)
        self.backdrop = None
        self.last_frames = None
        # Establish the GL composition before the native dock is first shown.
        self.layer.setVisible(QApplication.platformName() == 'windows')
        self.open_settings = open_settings
        self.entries = []
        self.gear = DockIcon(self, 'Ajustes de Cicerón', 'settings', open_settings)
        self.gear.hide()
        self.edge_hover = DockEdgeHover(self)
        self.edge_hover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.handle = DockHandle(self)
        self.handle.setMouseTracking(True)
        self.handle.setAccessibleName('Desplegar Cicerón')
        self.handle.setToolTip('Cicerón')
        self.handle.clicked.connect(self.reveal)
        self.using_glass = False
        self.glass_enabled = True
        self.theme_dark = False
        self.monochrome = False
        self.pure = False
        self.motion_enabled = True
        self.transparency = 0.0
        self.progress = 0.0
        self._capture_folded = True
        self.capacity = 1
        self.leave_at = 0.0
        self.transition_tick = 0.0
        self.transition_elapsed = 0.0
        self.transition_from = 0.0
        self.transition_to = 0.0
        self.started = time.monotonic()
        self.animation = QTimer(self)
        self.animation.setTimerType(Qt.TimerType.PreciseTimer)
        self.animation.timeout.connect(self.update_dock)
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.hover_timer.timeout.connect(self.confirm_hover)
        self.hover_probe = QTimer(self)
        self.hover_probe.setInterval(self.HOVER_PROBE_MS)
        self.hover_probe.timeout.connect(self.probe_hover)
        self.hover_blocked = False
        self.capture_timer = QTimer(self)
        self.capture_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.capture_timer.timeout.connect(self.capture)
        self.glass_timer = QTimer(self)
        self.glass_timer.setSingleShot(True)
        self.glass_timer.timeout.connect(self.prepare_layer)
        self.glass_idle_timer = QTimer(self)
        self.glass_idle_timer.setSingleShot(True)
        self.glass_idle_timer.timeout.connect(self.release_idle_capture)
        QApplication.instance().applicationStateChanged.connect(self.application_state_changed)
        self.screen = None
        QApplication.instance().primaryScreenChanged.connect(self.change_screen)
        self.change_screen(QApplication.primaryScreen())

    def change_screen(self, screen):
        if self.screen:
            for signal in ('availableGeometryChanged', 'geometryChanged'):
                try:
                    getattr(self.screen, signal).disconnect(self.position_on_edge)
                except (RuntimeError, TypeError):
                    pass
        self.screen = screen
        if screen:
            screen.availableGeometryChanged.connect(self.position_on_edge)
            screen.geometryChanged.connect(self.position_on_edge)
        self.position_on_edge()

    def set_entries(self, entries):
        for button in self.entries:
            button.hide()
            button.deleteLater()
        self.entries = [DockIcon(self, *entry) for entry in entries]
        for button in self.entries:
            button.hide()
        self.position_on_edge()

    def position_on_edge(self, *_):
        if not self.screen:
            return
        area = self.screen.availableGeometry()
        self.capacity = max(1, min(len(self.entries), (area.height() - 24) // self.STEP - 1))
        height = (self.capacity + 1) * self.STEP + 16
        self.setGeometry(area.right() + 1 - self.WIDTH, area.center().y() - height // 2, self.WIDTH, height)
        self.layer.setGeometry(self.rect())
        self.layer.lower()
        self.handle.setGeometry(self.WIDTH - self.HANDLE_WIDTH, (height - self.HANDLE_HEIGHT) // 2,
                                self.HANDLE_WIDTH, self.HANDLE_HEIGHT)
        self.edge_hover.setGeometry(self.handle.geometry())
        self.layout_icons()
        if self.panel is not None:
            self.position_panel(self.panel)
        self.capture()

    def apply_glass_tone(self, _light):
        self.handle.update()
        for button in (*self.entries, self.gear):
            button.update()

    def set_glass(self, enabled):
        changed = self.glass_enabled != bool(enabled)
        self.glass_enabled = bool(enabled)
        if changed and QApplication.platformName() == 'windows':
            self.layer.setVisible(self.glass_enabled)
        if changed and self.isVisible():
            if self.glass_enabled and self.progress > 0 and not capture_mode():
                self.glass_timer.start(180)
            elif not self.glass_enabled:
                self.stop_capture()
                if self.panel is not None:
                    self.panel.capture_enabled = self.panel.prepare_layer(False)

    def prepare_layer(self):
        if capture_mode() or not self.isVisible() or (self.progress < 1.0 and self.transition_to <= 0):
            return
        full = self.glass_enabled and not energy_saver_active()
        if full and (self.backdrop is None or self.layer.frame is None):
            self.layer.show()
            self.layer.lower()
            if self.layer.isValid() and not self.layer.error and apply_capture_affinity(self, live=True):
                if self.backdrop is None:
                    self.backdrop = DockBackdropCapture()
        if not full and self.backdrop is not None:
            self.stop_capture()
        if self.panel is not None:
            self.panel.capture_enabled = self.panel.prepare_layer(self.backdrop is not None)
        if self.backdrop is not None and not self.capture_timer.isActive():
            self.capture_timer.start(33)
            self.capture()
        self.set_capture_folded(False)

    def stop_capture(self):
        self.glass_idle_timer.stop()
        self.capture_timer.stop()
        if self.backdrop is not None:
            self.backdrop.close()
            self.backdrop = None
        self.last_frames = None
        self.using_glass = False
        self.layer.frame = None
        self.layer.frame_bounds = None
        self.layer.light = None
        self.layer.update()
        self._capture_folded = self.progress < 1.0
        apply_capture_affinity(self, live=False)
        self.apply_glass_tone(True)
        self.update()

    def release_idle_capture(self):
        if (self.progress == 0 and self.backdrop is not None and getattr(self.backdrop, 'lens', None) is None):
            self.stop_capture()

    def panel_shell(self):
        if self.panel_window is None:
            self.panel_window = AttachedPanel(self)
            self.destroyed.connect(self.panel_window.deleteLater)
        return self.panel_window

    def showEvent(self, event):
        super().showEvent(event)
        apply_capture_affinity(self)
        if self.progress == 0:
            self.hover_probe.start()

    def hideEvent(self, event):
        self.glass_timer.stop()
        self.hover_probe.stop()
        if self.panel is not None:
            self.panel.close()
        self.panel_mouse_press.stop()
        self.stop_capture()
        self.reset_to_handle()
        super().hideEvent(event)

    def reset_for_reopen(self):
        """Clear transient interaction and capture state before showing the dock again."""
        for timer in (self.animation, self.hover_timer, self.hover_probe, self.pending_open_timer,
                      self.capture_timer, self.glass_timer, self.glass_idle_timer):
            timer.stop()
        if self.panel is not None:
            self.panel.close()
        self.panel_mouse_press.stop()
        self.cancel_pending_panel()
        self.stop_capture()
        self.leave_at = 0.0
        self.transition_tick = time.monotonic()
        self.transition_elapsed = self.transition_from = self.transition_to = self.progress = 0.0
        self.hover_blocked = False
        self.layer.frame = None
        self.layer.frame_bounds = None
        self.layer.light = None
        self.layer.setVisible(self.glass_enabled and QApplication.platformName() == 'windows')
        self.set_capture_folded(True)
        self.layout_icons()
        self.layer.update()
        self.update()

    def shutdown(self):
        capture = self.backdrop
        self.close()
        self.panel_mouse_press.stop()
        if capture is not None:
            capture.thread.join(timeout=2)
        if self.panel_window is not None:
            self.panel_window.deleteLater()
            self.panel_window = None

    def reset_to_handle(self):
        self.animation.stop()
        self.hover_timer.stop()
        self.capture_timer.stop()
        self.glass_timer.stop()
        if self.backdrop is not None:
            self.glass_idle_timer.start(1200)
        self.cancel_pending_panel()
        self.leave_at = self.transition_to = self.progress = 0.0
        self.hover_blocked = self.pointer_over_dock()
        if self.isVisible():
            self.hover_probe.start()
        self.layout_icons()
        self.layer.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.probe_hover()

    def probe_hover(self):
        if not self.isVisible() or self.progress != 0 or self.transition_to != 0:
            return
        if not self.pointer_over_dock():
            self.hover_blocked = False
            self.hover_timer.stop()
        elif not self.hover_blocked and not self.hover_timer.isActive():
            self.hover_timer.start(self.HOVER_DELAY_MS)

    def pointer_over_dock(self):
        point = self.mapFromGlobal(QCursor.pos())
        return self.mask().contains(point)

    def confirm_hover(self):
        if self.isVisible() and not self.hover_blocked and self.pointer_over_dock():
            self.reveal()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.pointer_over_dock():
            return
        self.hover_blocked = False
        self.hover_timer.stop()
        self.leave_at = time.monotonic() + self.HIDE_DELAY
        if self.animation.isActive():
            self.animation.setInterval(16)
        elif (self.progress > 0 or self.transition_to > 0 or self.panel is not None or
              self.pending_panel is not None):
            self.animation.start(16)

    def reveal(self):
        self.hover_timer.stop()
        self.hover_probe.stop()
        self.hover_blocked = False
        self.glass_idle_timer.stop()
        self.leave_at = time.monotonic() + self.HIDE_DELAY
        if not self.animation.isActive():
            self.animation.start(16)
        self.update_dock()
        if (self.transition_to > 0 and self.glass_enabled and not capture_mode() and
                not energy_saver_active()):
            self.prepare_layer()
        if (self.progress == 1.0 and self.glass_enabled and not capture_mode() and
                not self.capture_timer.isActive() and not self.glass_timer.isActive()):
            self.glass_timer.start(24)

    def update_dock(self):
        now = time.monotonic()
        over_dock = self.pointer_over_dock()
        if over_dock:
            self.leave_at = now + self.HIDE_DELAY
        keep_open = capture_mode() and self.transition_to > 0
        target = float(self.panel is not None or self.pending_panel is not None or now < self.leave_at or keep_open)
        previous = self.progress
        if self.transition_to != target:
            if target and previous == 0 and self.glass_enabled and self.motion_enabled and not capture_mode():
                # A previously open dock must not show a different first frame after a quick revisit.
                self.last_frames = self.backdrop.latest if self.backdrop is not None else None
                self.capture_timer.stop()
                self.using_glass = False
                self.layer.frame = None
                self.layer.frame_bounds = None
                self.layer.light = None
            self.transition_tick = now
            self.transition_elapsed = 0.0
            self.transition_from = previous
            self.transition_to = target
        if self.motion_enabled and previous != target:
            distance = abs(target - self.transition_from)
            duration = (.22 if target else .32) * max(.45, distance)
            # Event-loop stalls must not consume unseen frames of the transition.
            self.transition_elapsed += min(now - self.transition_tick, self.MAX_TRANSITION_STEP)
            self.transition_tick = now
            t = min(1.0, self.transition_elapsed / duration)
            self.progress = self.transition_from + (target - self.transition_from) * t * t * (3 - 2 * t)
        else:
            self.progress = target
        if self.progress != previous:
            self.layout_icons()
            if self.layer.isVisible():
                self.layer.update()
            if self.progress == 1.0 and self.glass_enabled and not capture_mode():
                # Let the final frame of the reveal paint before resuming capture.
                self.glass_timer.start(24)
        if self.progress == 0.0 and not target:
            self.animation.stop()
            if not self.hover_probe.isActive():
                self.hover_probe.start()
            self.capture_timer.stop()
            self.glass_timer.stop()
            if self.backdrop is not None:
                self.glass_idle_timer.start(1200)
        else:
            waiting_to_hide = not over_dock and self.panel is None
            interval = 10 if self.progress != target or waiting_to_hide else 45
            if self.animation.interval() != interval:
                self.animation.setInterval(interval)
            if not self.animation.isActive():
                self.animation.start(interval)
        if (self.pending_panel is not None and self.progress >= 1.0 and
                not self.pending_open_timer.isActive()):
            self.pending_open_timer.start(0)

    def open_pending_panel(self):
        if self.motion_enabled and self.progress < 1.0:
            return
        request, self.pending_panel = self.pending_panel, None
        if request is None or not self.isVisible() or self.panel is not None:
            return
        self.toggle_panel(*request)

    def cancel_pending_panel(self):
        self.pending_open_timer.stop()
        self.pending_panel = None

    def set_capture_folded(self, folded):
        if self._capture_folded != folded:
            self._capture_folded = folded
            if self.isVisible() and not getattr(self, '_capture_live', False):
                apply_capture_affinity(self)

    def layout_icons(self):
        folded = self.progress < self.HANDLE_FADE_END
        self.set_capture_folded(self.progress < 1.0)
        rows = self.entries[:self.capacity] + [self.gear]
        icons_visible = self.progress > .76
        self.handle.setVisible(folded)
        self.handle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, icons_visible)
        handle_hit = self.handle.hit_region()
        if self.handle.mask() != handle_hit:
            self.handle.setMask(handle_hit)
        hover_hit = self.edge_hover.hit_region()
        if self.edge_hover.mask() != hover_hit:
            self.edge_hover.setMask(hover_hit)
        if folded:
            self.handle.raise_()
        self.handle.update()
        for button in self.entries[self.capacity:]:
            button.hide()
        outline = QPainterPath()
        rect = self.optic_rect()
        radius = min(self.CORNER_RADIUS, rect.width() / 2) + 1
        outline.addRoundedRect(rect.adjusted(-1, -1, 1, 1), radius, radius)
        region = QRegion(outline.toFillPolygon().toPolygon()).intersected(QRegion(self.rect()))
        for index, button in enumerate(rows):
            y = round(8 + index * self.STEP + (self.STEP - self.DIAMETER) / 2)
            button.setGeometry(round(self.WIDTH - self.EDGE_INSET - (self.CAPSULE_WIDTH + self.DIAMETER) / 2), y,
                               self.DIAMETER, self.DIAMETER)
            visible = icons_visible and region.contains(button.geometry().center())
            button.setVisible(visible)
            if visible and folded:
                button.raise_()
            button.update()
        # Keep the same hit surface while the arrow gives way to the icons.
        hit_region = region.united(hover_hit.translated(self.edge_hover.pos()))
        if self.mask() != hit_region:
            self.setMask(hit_region)
        if not self.using_glass:
            self.update()

    def optic_rect(self):
        shape = min(1.0, self.progress / .84)
        width = 18 + (self.CAPSULE_WIDTH - 18) * shape
        height = 42 + (self.height() - 46) * shape
        return QRectF(self.width() - width - self.EDGE_INSET, (self.height() - height) / 2, width, height)

    def glass_opacity(self):
        t = min(1.0, self.progress / .84)
        return t * t * (3 - 2 * t)

    def paintEvent(self, event):
        if self.progress == 0 or (self.glass_enabled and self.layer.isVisible()
                                 and self.layer.isValid() and self.layer.program is not None):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.glass_opacity())
        rect = self.optic_rect()
        if self.glass_enabled:
            frost = QLinearGradient(rect.topLeft(), rect.topRight())
            dark = (not self.layer.light if self.layer.light is not None
                    else self.theme_dark or self.pure)
            near, far = ((52, 52, 52), (30, 30, 30)) if dark else ((220, 220, 220), (194, 194, 194))
            frost.setColorAt(0, QColor(*near, round(120 - 120 * self.transparency)))
            frost.setColorAt(1, QColor(*far, round(76 - 90 * self.transparency)))
            painter.setPen(QPen(QColor(199, 199, 199, 150), 1))
            painter.setBrush(frost)
        else:
            painter.setPen(QPen(QColor('#757575' if self.theme_dark else '#a4a4a4'), 1))
            painter.setBrush(QColor('#2b2b2b' if self.theme_dark else '#f7f7f7'))
        radius = min(self.CORNER_RADIUS, rect.width() / 2)
        painter.drawRoundedRect(rect, radius, radius)

    def capture(self):
        if self.backdrop is None:
            return
        panel = self.panel if self.panel is not None and self.panel.capture_enabled else None
        bounds = (client_bounds(int(self.winId())),
                  (panel.capture_tile or client_bounds(int(panel.winId()))) if panel else None)
        frames = self.backdrop.latest
        if frames is not None and (frames is not self.last_frames or (
                panel is not None and (not panel.using_glass or panel.pending_geometry is not None))):
            self.last_frames = frames
            for owner, area, (captured, frame) in zip((self, panel), bounds, frames):
                if owner is not None and captured == area and frame is not None and not frame.isNull():
                    was_using_glass = owner.using_glass
                    owner.layer.set_frame(frame, captured, notify_parent=was_using_glass)
                    if not owner.using_glass:
                        owner.using_glass = True
                        owner.apply_glass_tone(owner.layer.light)
                        owner.update()
                    if owner is panel:
                        panel.seeded_light = None
                    if owner is panel and panel.pending_geometry is not None:
                        panel.animate_to(panel.pending_geometry)
        self.backdrop.submit(bounds)

    def update_capture_mode(self):
        if not self.isVisible():
            return
        if capture_mode():
            self.glass_timer.stop()
            self.stop_capture()
            if self.panel is not None:
                self.panel.capture_enabled = self.panel.prepare_layer(False)
        elif self.progress > 0 or self.panel is not None:
            self.update_dock()
            self.prepare_layer()

    def excluded_glass_windows(self):
        if self.backdrop is None or not self.isVisible():
            return ()
        if self.panel is not None and self.panel.capture_enabled and self.panel.isVisible():
            return self, self.panel
        return (self,)

    def lens_snapshot(self, window, area):
        """Draw the visible controls without reading back an OpenGL framebuffer."""
        dpr = window.devicePixelRatioF()
        frame = QImage(math.ceil(area.width() * dpr), math.ceil(area.height() * dpr),
                       QImage.Format.Format_ARGB32_Premultiplied)
        frame.setDevicePixelRatio(dpr)
        frame.fill(Qt.GlobalColor.transparent)
        offset = window.pos() - area.topLeft()
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = window.optic_rect().translated(QPointF(offset))
        radius = min(window.CORNER_RADIUS, rect.width() / 2, rect.height() / 2)
        outline = QPainterPath()
        outline.addRoundedRect(rect, radius, radius)
        opacity = self.glass_opacity() if window is self else window.windowOpacity()
        painter.setOpacity(opacity)
        painter.fillPath(outline, QColor(245, 245, 245, 70) if window.layer.light else QColor(32, 33, 35, 95))
        painter.setPen(QPen(QColor(243, 246, 250, 158), 1))
        painter.drawPath(outline)
        painter.setOpacity(1)
        widgets = [*self.entries, self.gear, self.handle] if window is self else [window.scroll]
        for widget in widgets:
            if widget.isVisible() and widget.geometry().translated(offset).intersects(QRect(QPoint(), area.size())):
                widget.render(painter, offset + widget.pos(), QRegion(), QWidget.RenderFlag.DrawChildren)
        painter.end()
        return frame

    def nativeEvent(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == PanelMousePress.MESSAGE:
            session, target = msg.lParam, msg.wParam
            QTimer.singleShot(0, self, lambda: self.dismiss_outside_click(session, target))
            return True, 0
        if msg.message == 0x0218 and msg.wParam in (0x000A, 0x0012):
            QTimer.singleShot(0, self.prepare_layer)
        return super().nativeEvent(event_type, message)

    def application_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive and self.panel is not None:
            session = self.panel_session
            QTimer.singleShot(0, self, lambda: self.dismiss_inactive_panel(session))

    def dismiss_inactive_panel(self, session):
        if QApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
            self.dismiss_outside_click(session, foreground_window())

    def dismiss_outside_click(self, session, target):
        panel = self.panel
        if panel is None or session != self.panel_session or capture_mode():
            return
        if window_belongs_to(target, int(self.winId())) or self.is_panel_window(panel, target):
            return
        # The tray icon handles its own click to toggle the center.
        if self.tray_geometry is not None and self.tray_geometry().contains(QCursor.pos()):
            return
        # A confirmation owned by this panel may be running a nested event loop.
        modal = QApplication.activeModalWidget()
        while modal is not None:
            if modal is panel:
                return
            modal = modal.parentWidget()
        panel.close()
        self.reset_to_handle()

    @staticmethod
    def is_panel_window(panel, handle):
        if window_belongs_to(handle, int(panel.winId())):
            return True
        widget = (QWidget.find(handle) or QWidget.find(root_window(handle, 2) or 0)) if handle else None
        while widget is not None:
            if widget is panel:
                return True
            widget = widget.parentWidget()
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.panel is not None:
                self.panel.close()
            self.reset_to_handle()
            event.accept()
        else:
            super().keyPressEvent(event)

    def toggle_panel(self, key, factory, persistent=False):
        if self.pending_panel is not None:
            if self.pending_panel[0] == key:
                self.cancel_pending_panel()
                return
            self.pending_panel = (key, factory, persistent)
            self.reveal()
            return
        previous = self.panel
        if previous is not None:
            previous.close()
            if previous.key == key:
                return
        if self.motion_enabled and self.progress < 1.0:
            self.pending_panel = (key, factory, persistent)
            self.reveal()
            return
        content = factory()
        if content is None:
            return
        content.hide()
        self.panel = self.panel_shell()
        self.panel.load_content(key, content, persistent)
        self.progress = 1.0
        self.layout_icons()
        self.position_panel(self.panel)
        self.panel.content.show()
        live = self.capture_timer.isActive()
        if not persistent:
            self.panel.fit_content()
        self.panel.prime_glass_tone()
        self.panel.layer.setVisible(live)
        self.panel.layer.lower()
        self.panel.show_panel()
        self.panel.capture_enabled = self.panel.prepare_layer(live)
        self.panel_session += 1
        if QApplication.platformName() == 'windows':
            self.panel_mouse_press.start(int(self.winId()), self.panel_session)
        if live:
            self.capture()
        self.reveal()

    def position_panel(self, panel):
        target = panel.resize_target()
        panel.resize_animation.stop()
        panel.setGeometry(self.panel_geometry(panel, target.height() if target is not None else panel.height()))
        if target is not None:
            panel.finish_resize()

    def panel_geometry(self, panel, height, keep_top=False):
        if not self.screen:
            return panel.geometry()
        area = self.screen.availableGeometry()
        anchors = dict(zip(('clock', 'browser', 'effects'), self.entries))
        anchor = anchors.get(panel.key, self.gear)
        seam = self.x() + round(self.optic_rect().left()) + panel.INSET - self.PANEL_GAP
        available = seam - area.left()
        width = min(panel.width(), max(1, available))
        height = min(height, area.height() - 12)
        x = seam - width
        if keep_top:
            return QRect(x, panel.y(), width, min(height, area.bottom() - panel.y() - 4))
        y = self.y() + anchor.geometry().center().y() - height // 2
        return QRect(x, max(area.top() + 6, min(y, area.bottom() - height - 4)), width, height)

    def panel_closed(self, panel):
        if self.panel is panel:
            self.panel = None
            self.panel_mouse_press.stop()
            self.leave_at = time.monotonic() + self.HIDE_DELAY
