"""Refract live desktop pixels through the controls of a native Qt window."""

from OpenGL import GL
from OpenGL.GL import shaders
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QCheckBox, QComboBox, QFrame, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QStyle, QStyleOptionButton, QWidget
)

from center_ui import APP_CARD_IDENTITY_RADIUS, AppCardIdentity, V3_CONTROL_RADIUS
from gpu_lens import (EDGE_OPTICS, VERTEX, backdrop_is_dark, backdrop_is_light,
                      compile_lens, paint_optic)
from lens_capture import WindowBackdropCapture
from windows_glass import apply_capture_affinity, capture_mode, client_bounds, get_style


FRAGMENT = '''#version 120
uniform sampler2D backdrop;
uniform vec2 pixels;
uniform vec4 surface;
uniform vec3 tint;
uniform float material;
uniform float transparency;
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
    float direction = 0.55 - normal.y * 0.36 - normal.x * 0.13;
    // Keep the surface stable while the captured desktop moves underneath it.
    vec2 refracted = uv - normal * lip_inset(-distance, width) / pixels;
    vec2 spread = normal * (shoulder * (0.36 + direction * 0.5) / pixels);
    vec3 desktop = texture2D(backdrop, refracted).rgb;
    float chroma = max(desktop.r, max(desktop.g, desktop.b)) - min(desktop.r, min(desktop.g, desktop.b));
    desktop.rb = mix(desktop.rb, vec2(texture2D(backdrop, refracted + spread).r,
                                     texture2D(backdrop, refracted - spread).b),
                     0.42 * smoothstep(0.06, 0.30, chroma));
    float reflection = (1.0 - smoothstep(0.0, 1.8, -distance)) * (0.22 + direction * 0.30);
    vec3 body = legible_surface(softened_desktop(refracted), transmission - (window_face ? 0.0 : 0.05));
    if (material > 0.80) {
        vec3 active_tint = tint.r < 0.5 ? tint * 0.88 : tint * vec3(0.74, 0.88, 1.0) + vec3(0.0, 0.015, 0.07);
        body = mix(body, active_tint, 0.33);
    }
    vec3 glass = mix(body, desktop, shoulder * 0.72);
    float alpha = mix(1.0, window_face ? 0.79 * (1.0 - smoothstep(-1.0, 0.0, distance)) : 0.88, floating_panel);
    gl_FragColor = vec4(mix(glass, vec3(1.0), reflection) * alpha, alpha);
}
'''


# Cambio 88: a stable, display-paced capture avoids stale glass while another window scrolls.
def glass_capture_interval(refresh_rate):
    """Track the display at 30–60 fps, regardless of window activation."""
    hz = min(60.0, max(30.0, float(refresh_rate or 30.0)))
    return max(4, round(1000.0 / hz))


def glass_text_rect(widget):
    if not isinstance(widget, (QLabel, QCheckBox)) or not widget.text().strip():
        return QRect()
    if isinstance(widget, QLabel):
        margin = widget.margin()
        area = widget.contentsRect().adjusted(margin, margin, -margin, -margin)
        flags = widget.alignment().value
        if widget.wordWrap():
            flags |= Qt.TextFlag.TextWordWrap.value
    else:
        option = QStyleOptionButton()
        widget.initStyleOption(option)
        area = widget.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, option, widget)
        flags = Qt.AlignmentFlag.AlignVCenter.value | Qt.TextFlag.TextShowMnemonic.value
    text = widget.fontMetrics().boundingRect(area, flags, widget.text()).intersected(area)
    return text.adjusted(-12, -8, 12, 8) if not text.isEmpty() else text


def draw_clear_material(layer, program, uniforms, rect, sample, physical, radius, opacity=1.0, *,
                        controls=True, light=False, glass_mix=1.0,
                        provisional=(0.0, 0.0, 0.0, 0.0)):
    """Draw the panel and its visible native controls from one desktop texture."""
    owner = layer.parentWidget()
    width, height = layer.width(), layer.height()
    sx, sy = physical[0] / rect.width(), physical[1] / rect.height()
    viewport = GL.glGetIntegerv(GL.GL_VIEWPORT)

    def scissor(clip):
        GL.glScissor(round(clip.x()*viewport[2]/width),
                     round((height-clip.y()-clip.height())*viewport[3]/height),
                     round(clip.width()*viewport[2]/width), round(clip.height()*viewport[3]/height))

    def draw(area, corner, mode):
        l, t = area.x(), area.y()
        w, h = area.width(), area.height()
        x, y = 2*l/width-1, 1-2*t/height
        right, bottom = x+2*w/width, y-2*h/height
        region = (sample[0]+(l-rect.x())/rect.width()*sample[2],
                  sample[1]+(t-rect.y())/rect.height()*sample[3],
                  w/rect.width()*sample[2], h/rect.height()*sample[3])
        paint_optic(program, uniforms, w*sx, region, QPointF(), 0,
                    ((x,bottom),(right,bottom),(right,y),(x,y)), body_height=h*sy,
                    panel_radius=min(corner*sx, w*sx/2, h*sy/2),
                    clear_mode=mode, glass_tone=float(light), glass_opacity=opacity,
                    glass_mix=glass_mix, provisional=provisional)
    draw(rect, radius, 1)
    if not controls:
        return
    GL.glEnable(GL.GL_SCISSOR_TEST)
    blend_was_enabled = GL.glIsEnabled(GL.GL_BLEND)
    GL.glEnable(GL.GL_BLEND)
    GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
    text_surfaces = []
    try:
        for widget in owner.findChildren(QWidget):
            if not isinstance(widget, (AppCardIdentity, QLabel, QAbstractButton, QLineEdit,
                                       QComboBox, QAbstractSpinBox, QPlainTextEdit)):
                continue
            if widget.window() != owner.window() or not widget.isVisible() or not widget.width() or not widget.height():
                continue
            if isinstance(widget, QLineEdit) and isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
                continue
            grouped = isinstance(widget, AppCardIdentity)
            is_label = isinstance(widget, (QLabel, QCheckBox))
            if is_label and isinstance(widget.parentWidget(), AppCardIdentity):
                continue
            is_text = grouped or is_label
            area = glass_text_rect(widget) if is_label else widget.rect()
            if area.isEmpty():
                continue
            area.translate(widget.mapTo(owner, QPoint()))
            clip = area.intersected(rect.toRect())
            frost = owner.property('frostControls')
            parent = widget.parentWidget()
            while parent is not None and parent is not owner and not clip.isEmpty():
                frost = frost or parent.property('frostControls')
                clip = clip.intersected(QRect(parent.mapTo(owner, QPoint()), parent.size()))
                parent = parent.parentWidget()
            if clip.isEmpty():
                continue
            if is_text:
                text_surfaces.append((area, clip, APP_CARD_IDENTITY_RADIUS if grouped else 12))
                continue
            scissor(clip)
            draw(QRectF(area), V3_CONTROL_RADIUS, 3 if frost else 2)
        for area, clip, corner in text_surfaces:
            scissor(clip)
            draw(QRectF(area), corner, 5 if light else 4)
    finally:
        if not blend_was_enabled:
            GL.glDisable(GL.GL_BLEND)
        GL.glDisable(GL.GL_SCISSOR_TEST)


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
        self.capture_source = None
        self.dark = False
        self.light = None
        self.floating_panel = False
        self.transparency = 0.0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.refresh)
        self.capture_hwnd = None
        self.ready = False
        self.hide()

    def initializeGL(self):
        try:
            self.clear_program, self.clear_uniforms = compile_lens()
            self.program = shaders.compileProgram(
                shaders.compileShader(VERTEX, GL.GL_VERTEX_SHADER),
                shaders.compileShader(FRAGMENT, GL.GL_FRAGMENT_SHADER))
            self.uniform = {name: GL.glGetUniformLocation(self.program, name) for name in
                            ('backdrop', 'pixels', 'surface', 'tint', 'material',
                             'transparency', 'floating_panel')}
            self.texture = GL.glGenTextures(1)
            self.mipmapped = False
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
            for parameter, value in (
                (GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE),
            ):
                GL.glTexParameteri(GL.GL_TEXTURE_2D, parameter, value)
        except Exception as error:
            self.error = str(error)

    def start(self):
        if self.timer.isActive() or capture_mode() or not self.window().isVisible() or self.window().isMinimized():
            return
        hwnd = int(self.window().winId())
        if not get_style(hwnd, -20) & 0x00080000:
            return
        if not apply_capture_affinity(self.window(), live=True):
            return
        self.capture_hwnd = hwnd
        self.setGeometry(self.window().rect())
        self.lower()
        self.show()
        if self.error or not self.isValid():
            self.stop()
            return
        self.capture_source = WindowBackdropCapture()
        self.ready = False
        self.timer.start(self.capture_interval())
        self.refresh()
        self.update()

    def capture_interval(self):
        screen = self.window().screen()
        return glass_capture_interval(screen.refreshRate() if screen is not None else 60.0)

    def stop(self):
        active = self.timer.isActive() or self.frame is not None or self.ready
        self.timer.stop()
        if self.capture_hwnd is not None:
            apply_capture_affinity(self.window(), live=False)
            self.capture_hwnd = None
        self.hide()
        self.frame = None
        self.light = None
        source, self.capture_source = self.capture_source, None
        if source is not None:
            source.close()
        self.ready = False
        if active:
            self.on_ready(False)

    def refresh(self):
        owner = self.window()
        if owner.isMinimized() or not owner.isVisible():
            self.stop()
            return
        self.setGeometry(owner.rect())
        interval = self.capture_interval()
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        source = self.capture_source
        if source is None:
            return
        if source.error is not None:
            self.stop()
            return
        source.submit(self.capture_hwnd)
        latest = source.latest
        if latest is None:
            return
        hwnd, bounds, frame = latest
        if hwnd != self.capture_hwnd or bounds != client_bounds(hwnd):
            return
        if frame is not self.frame:
            changed = self.set_frame(frame)
            if not self.ready or changed:
                self.ready = True
                self.on_ready(True)
            self.update()

    def set_frame(self, frame):
        # Keep the visual treatment in step with this captured frame. A stale
        # tone briefly makes dark captures look washed out.
        light = backdrop_is_light(frame, self.light)
        changed = light != self.light
        self.frame = frame
        self.texture_dirty = True
        self.light = light
        return changed

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
        pure = getattr(self, 'pure', False)
        dark = backdrop_is_dark(self.dark, self.light)
        base = 0.0 if pure else (0.14 if dark else 0.94)
        GL.glClearColor(base, base, base, float(not pure and not self.floating_panel))
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self.frame is None or self.program is None:
            return
        GL.glDisable(GL.GL_BLEND)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        width, height = self.frame.width(), self.frame.height()
        frame_changed = self.texture_dirty
        if frame_changed:
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            if self.size_on_gpu == (width, height):
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, width, height,
                                  GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, self.frame.constBits())
            else:
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, width, height, 0,
                               GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, self.frame.constBits())
                self.size_on_gpu = (width, height)
            self.texture_dirty = False
        if pure and (frame_changed or not self.mipmapped):
            GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        if pure != self.mipmapped:
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER,
                               GL.GL_LINEAR_MIPMAP_LINEAR if pure else GL.GL_LINEAR)
            self.mipmapped = pure
        if pure:
            draw_clear_material(self, self.clear_program, self.clear_uniforms, QRectF(self.rect()),
                                (0, 0, 1, 1), (width, height), 19, light=bool(self.light))
            return
        scale_x, scale_y = width / self.width(), height / self.height()
        GL.glUseProgram(self.program)
        GL.glUniform1i(self.uniform['backdrop'], 0)
        GL.glUniform2f(self.uniform['pixels'], width, height)
        GL.glUniform1f(self.uniform['transparency'], self.transparency)
        GL.glUniform1f(self.uniform['floating_panel'], float(self.floating_panel))
        GL.glUniform3f(self.uniform['tint'], *((.105, .105, .105) if dark else (.97, .985, 1.0)))
        GL.glUniform1f(self.uniform['material'], -1.0)
        self.draw_quad(self.rect())
        for surface, clip, material in self.surfaces():
            GL.glUniform4f(self.uniform['surface'], surface.x() * scale_x, surface.y() * scale_y,
                           surface.width() * scale_x, surface.height() * scale_y)
            GL.glUniform1f(self.uniform['material'], material)
            self.draw_quad(clip)
        GL.glUseProgram(0)
