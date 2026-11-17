"""Refract live desktop pixels through the controls of a native Qt window."""
import time

from OpenGL import GL
from OpenGL.GL import shaders
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCursor, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QFrame, QLineEdit, QPlainTextEdit, QPushButton
)

from gpu_lens import EDGE_OPTICS, VERTEX
from windows_glass import BackdropCapture, get_style, set_affinity


FRAGMENT = '''#version 120
uniform sampler2D backdrop;
uniform vec2 pixels;
uniform vec2 cursor;
uniform vec4 surface;
uniform vec3 tint;
uniform float material;
uniform float transparency;
uniform float elapsed;
uniform float floating_panel;
varying vec2 uv;
''' + EDGE_OPTICS + '''

vec3 softened_desktop(vec2 position) {
    vec2 delta = 0.85 / pixels;
    return 0.25 * (texture2D(backdrop, position + delta).rgb
                 + texture2D(backdrop, position - delta).rgb
                 + texture2D(backdrop, position + vec2(delta.x, -delta.y)).rgb
                 + texture2D(backdrop, position + vec2(-delta.x, delta.y)).rgb);
}

vec3 legible_surface(vec3 desktop, float transmission) {
    // Even pure black and white wallpaper must leave enough contrast for labels.
    return mix(tint, desktop, clamp(transmission, 0.05, 0.22));
}

void main() {
    float transmission = 0.15 + transparency * 0.35;
    vec2 pos = uv * pixels;
    bool window_face = material < 0.0;
    vec4 rect = window_face ? vec4(0.0, 0.0, pixels) : surface;
    vec2 half_size = rect.zw * 0.5;
    vec2 local = pos - rect.xy - half_size;
    float radius = min(19.0, min(half_size.x, half_size.y));
    vec2 q = abs(local) - half_size + radius;
    float distance = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
    if (distance > 0.0) {
        if (!window_face || floating_panel > 0.5) discard;
        gl_FragColor = vec4(legible_surface(softened_desktop(uv), transmission), 1.0);
        return;
    }
    vec2 corner = max(q, 0.0);
    vec2 normal = length(corner) > 0.0 ? corner / length(corner) * sign(local)
                : (q.x > q.y ? vec2(sign(local.x), 0.0) : vec2(0.0, sign(local.y)));
    float width = radius * 0.70;
    float shoulder = 1.0 - smoothstep(0.0, width, -distance);
    float near_pointer = exp(-length(pos - cursor) / 115.0);
    float wave = sin(distance * 0.47 - elapsed * 8.0) * near_pointer * 0.95;
    float direction = 0.55 - normal.y * 0.36 - normal.x * 0.13;
    vec2 refracted = uv - normal * (lip_inset(-distance, width) + shoulder * wave) / pixels;
    vec2 spread = normal * (shoulder * (0.36 + direction * 0.5) / pixels);
    vec3 desktop = texture2D(backdrop, refracted).rgb;
    float chroma = max(desktop.r, max(desktop.g, desktop.b)) - min(desktop.r, min(desktop.g, desktop.b));
    desktop.rb = mix(desktop.rb, vec2(texture2D(backdrop, refracted + spread).r,
                                     texture2D(backdrop, refracted - spread).b),
                     0.42 * smoothstep(0.06, 0.30, chroma));
    float reflection = (1.0 - smoothstep(0.0, 1.8, -distance)) * (0.22 + direction * 0.30);
    vec3 body = legible_surface(softened_desktop(refracted), transmission - (window_face ? 0.0 : 0.05));
    if (material > 0.80) {
        body = mix(body, tint * vec3(0.74, 0.88, 1.0) + vec3(0.0, 0.015, 0.07), 0.33);
    }
    vec3 glass = mix(body, desktop, shoulder * 0.72);
    float alpha = mix(1.0, window_face ? 0.79 * (1.0 - smoothstep(-1.0, 0.0, distance)) : 0.88, floating_panel);
    gl_FragColor = vec4(mix(glass, vec3(1.0), reflection) * alpha, alpha);
}
'''


class GlassBackdrop(QOpenGLWidget):
    """A background OpenGL layer. The Qt controls keep their native input."""

    def __init__(self, window, on_ready):
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setAlphaBufferSize(8)
        fmt.setSwapInterval(0)
        self.setFormat(fmt)
        self.on_ready = on_ready
        self.frame = None
        self.texture_dirty = False
        self.program = None
        self.texture = None
        self.size_on_gpu = None
        self.uniform = {}
        self.error = None
        self.capture_source = BackdropCapture()
        self.dark = False
        self.floating_panel = False
        self.transparency = 0.0
        self.started = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.capture_hwnd = None
        self.photo_timer = QTimer(self)
        self.photo_timer.setSingleShot(True)
        self.photo_timer.timeout.connect(self.resume_capture)
        self.hide()

    def initializeGL(self):
        try:
            self.program = shaders.compileProgram(
                shaders.compileShader(VERTEX, GL.GL_VERTEX_SHADER),
                shaders.compileShader(FRAGMENT, GL.GL_FRAGMENT_SHADER))
            self.uniform = {name: GL.glGetUniformLocation(self.program, name) for name in
                            ('backdrop', 'pixels', 'cursor', 'surface', 'tint', 'material',
                             'transparency', 'elapsed', 'floating_panel')}
            self.texture = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
            for parameter, value in (
                (GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE),
            ):
                GL.glTexParameteri(GL.GL_TEXTURE_2D, parameter, value)
        except Exception as error:
            self.error = str(error)

    def start(self):
        if self.timer.isActive() or self.photo_timer.isActive() or not self.window().isVisible():
            return
        hwnd = int(self.window().winId())
        if not get_style(hwnd, -20) & 0x00080000:
            return
        if not set_affinity(hwnd, 0x11):
            return
        self.capture_hwnd = hwnd
        frame = self.capture_source.capture_behind(hwnd)
        if frame.isNull():
            self.stop()
            return
        self.setGeometry(self.window().rect())
        self.lower()
        self.show()
        if self.error or not self.isValid():
            self.stop()
            return
        self.frame = frame
        self.texture_dirty = True
        self.on_ready(True)
        self.timer.start(40)
        self.update()

    def stop(self):
        active = self.timer.isActive() or self.frame is not None
        self.timer.stop()
        self.photo_timer.stop()
        if self.capture_hwnd is not None:
            set_affinity(self.capture_hwnd, 0)
            self.capture_hwnd = None
        self.hide()
        self.frame = None
        self.capture_source.close()
        if active:
            self.on_ready(False)

    def show_in_screenshots(self):
        if self.capture_hwnd is not None and set_affinity(self.capture_hwnd, 0):
            self.timer.stop()
            self.photo_timer.start(20000)

    def resume_capture(self):
        if self.capture_hwnd is None or not set_affinity(self.capture_hwnd, 0x11):
            self.stop()
            return
        self.timer.start(40)
        self.refresh()

    def refresh(self):
        owner = self.window()
        if owner.isMinimized() or not owner.isVisible():
            self.stop()
            return
        self.setGeometry(owner.rect())
        interval = 40 if owner.isActiveWindow() else 120
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        frame = self.capture_source.capture_behind(self.capture_hwnd)
        if not frame.isNull():
            self.frame = frame
            self.texture_dirty = True
            self.update()

    def surfaces(self):
        owner = self.window()
        items = []
        for widget in owner.findChildren(QFrame):
            if widget.window() is owner and widget.isVisible() and widget.objectName() in (
                'sidebar', 'card', 'timeCard', 'libraryBanner'
            ):
                items.append((widget, .68))
        for widget in owner.findChildren(QPushButton):
            if widget.window() is owner and widget.isVisible():
                active = widget.isChecked() or widget.isDown() or widget.underMouse()
                items.append((widget, .86 if active else .72))
        for kind in (QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit):
            for widget in owner.findChildren(kind):
                if widget.window() is owner and widget.isVisible():
                    items.append((widget, .68))
        for widget, material in items:
            area = QRect(widget.mapTo(owner, QPoint()), widget.size())
            clip = area.intersected(owner.rect())
            parent = widget.parentWidget()
            while not clip.isEmpty() and parent is not owner and parent is not None:
                clip = clip.intersected(QRect(parent.mapTo(owner, QPoint()), parent.size()))
                parent = parent.parentWidget()
            if not clip.isEmpty():
                yield area, clip, material

    def draw_quad(self, rectangle):
        x1, y1 = rectangle.x() / self.width(), rectangle.y() / self.height()
        x2 = (rectangle.x() + rectangle.width()) / self.width()
        y2 = (rectangle.y() + rectangle.height()) / self.height()
        GL.glBegin(GL.GL_QUADS)
        for x, y in ((x1, y2), (x2, y2), (x2, y1), (x1, y1)):
            GL.glTexCoord2f(x, y)
            GL.glVertex2f(x * 2 - 1, 1 - y * 2)
        GL.glEnd()

    def paintGL(self):
        GL.glClearColor(.12, .16, .24, float(not self.floating_panel))
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self.frame is None or self.program is None:
            return
        GL.glDisable(GL.GL_BLEND)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        width, height = self.frame.width(), self.frame.height()
        if self.texture_dirty:
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            if self.size_on_gpu == (width, height):
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, width, height,
                                  GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, self.frame.constBits())
            else:
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, width, height, 0,
                               GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, self.frame.constBits())
                self.size_on_gpu = (width, height)
            self.texture_dirty = False
        scale_x, scale_y = width / self.width(), height / self.height()
        pointer = self.mapFromGlobal(QCursor.pos())
        GL.glUseProgram(self.program)
        GL.glUniform1i(self.uniform['backdrop'], 0)
        GL.glUniform2f(self.uniform['pixels'], width, height)
        GL.glUniform2f(self.uniform['cursor'], pointer.x() * scale_x, pointer.y() * scale_y)
        GL.glUniform1f(self.uniform['elapsed'], time.monotonic() - self.started)
        GL.glUniform1f(self.uniform['transparency'], self.transparency)
        GL.glUniform1f(self.uniform['floating_panel'], float(self.floating_panel))
        GL.glUniform3f(self.uniform['tint'], *((.075, .105, .17) if self.dark else (.97, .985, 1.0)))
        GL.glUniform1f(self.uniform['material'], -1.0)
        self.draw_quad(self.rect())
        for surface, clip, material in self.surfaces():
            GL.glUniform4f(self.uniform['surface'], surface.x() * scale_x, surface.y() * scale_y,
                           surface.width() * scale_x, surface.height() * scale_y)
            GL.glUniform1f(self.uniform['material'], material)
            self.draw_quad(clip)
        GL.glUseProgram(0)
