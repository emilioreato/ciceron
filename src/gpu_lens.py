"""GPU glass lens for the Windows desktop; the background is never saved."""
import time
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QCursor, QImage, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication
from OpenGL import GL
from OpenGL.GL import shaders
from lens_capture import LensCapture
from windows_glass import client_bounds, set_affinity

VERTEX = '''#version 120
varying vec2 uv;
void main() { gl_Position = gl_Vertex; uv = gl_MultiTexCoord0.xy; }
'''
# Inverse optical map, in screen pixels. The lip skips the first strip of
# background, then packs the next strip into a narrow band of glass.
EDGE_OPTICS = '''
float lip_inset(float depth, float width) {
    float t = clamp(depth / width, 0.0, 1.0);
    // The steepest bend is at the silhouette. A nearby line can run along
    // the lip before it is visible across the flatter face of the glass.
    return width * 0.94 * (1.0 - t) * (1.0 - t);
}
'''

FRAGMENT = '''#version 120
uniform sampler2D backdrop;
uniform float pixels;
uniform float body_height;
uniform vec2 interaction;
uniform vec4 surface;
uniform float panel_radius;
uniform float glass_tone;
uniform float clear_mode;
uniform float glass_blur;
uniform float glass_opacity;
uniform float elapsed;
uniform vec2 sample_origin;
uniform vec2 sample_scale;
uniform vec2 motion;
uniform float appearance;
varying vec2 uv;
''' + EDGE_OPTICS + '''
void main() {
    bool interface_glass = body_height > 0.0;
    float tall = panel_radius > 0.0 ? body_height : max(body_height, pixels);
    vec2 extent = vec2(pixels, tall);
    vec2 local = (uv - surface.xy) / surface.zw;
    vec2 relative = (local - vec2(0.5)) * extent;
    float axis = max((tall - pixels) * 0.5, 0.0);
    vec2 spine = vec2(0.0, clamp(relative.y, -axis, axis));
    float diameter = pixels;
    if (panel_radius > 0.0) {
        vec2 limit = extent * 0.5 - panel_radius;
        spine = clamp(relative, -limit, limit);
        diameter = panel_radius * 2.0;
    }
    vec2 p = (relative - spine) * (2.0 / diameter);
    float r = length(p);
    vec2 normal = p / max(r, 0.00001);
    if (interface_glass) {
        float edge = r;
        // Keep the optional perimeter wave off the static glass path.
        if (dot(motion, motion) > 0.0) {
            float reach = length((local - interaction) * extent / diameter);
            float pulse = sin(reach * 3.8 - elapsed * 17.0);
            edge -= (0.12 * pulse + 0.085 * dot(normal, motion)) * min(length(motion), 1.0) * exp(-reach * 0.85);
        }
        if (edge >= 0.975) {
            gl_FragColor = vec4(0.0);
            return;
        }
        float bevel = smoothstep(0.74, 0.94, edge);
        float depth = (0.975 - edge) * diameter * 0.5;
        vec2 lookup = local - normal * lip_inset(depth, diameter * 0.35) / extent;
        vec2 coord = sample_origin + clamp(lookup, 0.0, 1.0) * sample_scale;
        if (clear_mode > 0.5) {
            vec2 pixel = sample_scale / extent;
            // Binomial weights approximate a Gaussian on the button's backdrop.
            vec2 d = pixel * (clear_mode > 1.5 ? 3.2 : 0.38);
            vec3 color = texture2D(backdrop, coord).rgb * 0.25;
            color += (texture2D(backdrop, coord + vec2(d.x, 0.0)).rgb
                    + texture2D(backdrop, coord - vec2(d.x, 0.0)).rgb
                    + texture2D(backdrop, coord + vec2(0.0, d.y)).rgb
                    + texture2D(backdrop, coord - vec2(0.0, d.y)).rgb) * 0.125;
            color += (texture2D(backdrop, coord+d).rgb + texture2D(backdrop, coord-d).rgb
                    + texture2D(backdrop, coord+vec2(d.x,-d.y)).rgb
                    + texture2D(backdrop, coord+vec2(-d.x,d.y)).rgb) * 0.0625;
            if (clear_mode < 1.5) {
                vec2 fringe = pixel * normal * 2.2 * bevel;
                vec2 split = vec2(texture2D(backdrop, coord-fringe).r,
                                  texture2D(backdrop, coord+fringe).b);
                color.rb += clamp(split-color.rb, -0.18, 0.18) * bevel;
            }
            float alpha = glass_opacity * (1.0-smoothstep(0.975-1.5/diameter, 0.975, edge));
            gl_FragColor = vec4(color*alpha, alpha);
            return;
        }
        float blur = glass_blur + (appearance - 1.0) * 3.0;
        vec3 color = texture2D(backdrop, coord, blur).rgb;
        float luma = dot(color, vec3(0.2126, 0.7152, 0.0722));
        color = glass_tone < 0.5
            ? color * min(1.0, 0.41 / max(luma, 0.001))
            : mix(color, vec3(1.0), max(0.0, (0.64 - luma) / max(1.0 - luma, 0.001)));
        if (bevel > 0.0) {
            vec3 edge_color = texture2D(backdrop, coord).rgb;
            float chroma = max(edge_color.r, max(edge_color.g, edge_color.b))
                         - min(edge_color.r, min(edge_color.g, edge_color.b));
            if (chroma > 0.06) {
                float lobe = 0.55 + 0.45 * (-0.079 * (normal.x*normal.x - normal.y*normal.y)
                                           - 1.994 * normal.x * normal.y);
                vec2 fringe = normal * (bevel * (0.45 + 0.65 * lobe) / extent);
                float red = texture2D(backdrop, sample_origin + clamp(lookup + fringe, 0.0, 1.0) * sample_scale).r;
                float blue = texture2D(backdrop, sample_origin + clamp(lookup - fringe, 0.0, 1.0) * sample_scale).b;
                edge_color.rb = mix(edge_color.rb, vec2(red, blue), 0.44 * smoothstep(0.06, 0.30, chroma));
            }
            color = mix(color, edge_color, bevel * 0.90);
            float light = clamp(0.4 - normal.y * 0.47 - normal.x * 0.22, 0.0, 1.0);
            float reflection = smoothstep(0.79, 0.95, edge);
            color *= 1.0 - reflection * (0.07 + 0.18 * (1.0 - light));
            float glint = smoothstep(0.88, 0.965, edge) * (0.12 + 0.37 * light);
            float rim = smoothstep(0.946, 0.968, edge) * (1.0-smoothstep(0.970, 0.977, edge));
            color = mix(color, vec3(1.0), glint + rim * 0.10);
        }
        float alpha = (1.0 - smoothstep(0.975 - 1.5 / diameter, 0.975, edge)) * glass_opacity;
        gl_FragColor = vec4(color * alpha, alpha);
        return;
    }
    float angle = r > 0.00001 ? atan(p.y, p.x) : 0.0;
    float energy = min(length(motion), 1.0);
    float lead = dot(normal, motion);
    // The crest travels around the shoulder and dies out when the mouse stops.
    float phase = r * 26.0 - elapsed * 15.0 - lead * 3.0 + sin(angle * 3.0);
    float shoulder = smoothstep(0.46, 0.82, r) * (1.0 - smoothstep(0.91, 1.0, r));
    float wave = sin(phase) * shoulder * energy;
    float edge = r - (0.018 * lead + 0.012 * sin(3.0 * angle - elapsed * 9.0) * energy);
    if (edge >= 0.975) {
        gl_FragColor = vec4(0.0);
        return;
    }
    float bevel = smoothstep(0.74, 0.94, edge);
    vec2 tangent = vec2(-normal.y, normal.x);
    vec2 unit = diameter / extent;
    float depth = (0.975 - edge) * diameter * 0.5;
    float width = diameter * 0.18;
    float body_inset = r * diameter * 0.085 * smoothstep(0.0, width, depth);
    vec2 lookup = local - normal * (body_inset + lip_inset(depth, width)) / extent;
    lookup += normal * (0.018 * wave) * unit;
    lookup += tangent * (cos(phase) * shoulder * energy * 0.014) * unit;
    if (energy > 0.025) {
        vec2 travel = normalize(motion);
        float front = smoothstep(0.28, 0.94, dot(normal, travel));
        float hold = 1.0 - smoothstep(5.0, 7.1, depth);
        float crest = smoothstep(4.6, 5.7, depth) * (1.0 - smoothstep(7.0, 9.0, depth));
        float displacement = (7.2 * hold - 3.4 * crest) * front * smoothstep(0.025, 0.31, energy);
        lookup -= travel * displacement / extent;
    }
    vec2 coord = sample_origin + clamp(lookup, 0.0, 1.0) * sample_scale;
    // Four bilinear taps give a separable, Gaussian-like 3x3 footprint.
    vec2 delta = (0.30 + 0.20 * bevel) * sample_scale / extent;
    vec4 source = 0.25 * (texture2D(backdrop, coord + delta)
                        + texture2D(backdrop, coord - delta)
                        + texture2D(backdrop, coord + vec2(delta.x, -delta.y))
                        + texture2D(backdrop, coord + vec2(-delta.x, delta.y)));
    // The green channel follows refraction; red and blue sample either side near the lip.
    float prism = smoothstep(0.79, 0.935, edge);
    if (prism > 0.0) {
        float lobe = 0.55 + 0.45 * cos(2.0 * angle + 1.65 - lead * 2.0);
        float spread = prism * (1.60 + 1.80 * lobe + 0.65 * energy * max(lead, 0.0));
        vec2 fringe = (normal + tangent * (0.20 * lead)) * (spread / extent);
        float red = texture2D(backdrop, sample_origin + clamp(lookup - fringe, 0.0, 1.0) * sample_scale).r;
        float blue = texture2D(backdrop, sample_origin + clamp(lookup + fringe, 0.0, 1.0) * sample_scale).b;
        vec2 split = vec2(red, blue) - source.rb;
        float strength = 0.44 + lobe * 0.33 + energy * 0.10;
        source.rb += prism * clamp(split * strength, -0.18, 0.18);
    }
    float aa = 1.5 / diameter;
    float mask = 1.0 - smoothstep(0.975-aa, 0.975, edge);
    float light = clamp(0.4 - normal.y * 0.47 - normal.x * 0.22 + 0.25 * wave, 0.0, 1.0);
    float rim = smoothstep(0.946, 0.968, edge) * (1.0-smoothstep(0.970, 0.977, edge));
    vec3 color = mix(source.rgb, vec3(1.0), rim * (0.06 + 0.18 * light));
    float alpha = source.a * mask * appearance;
    gl_FragColor = vec4(color * alpha, alpha);
}
'''


def pointer_motion(previous, delta, dt, half_life=0.05):
    travel = QPointF(delta) / (dt * 1050)
    speed = (travel.x() ** 2 + travel.y() ** 2) ** 0.5
    if speed > 1:
        travel /= speed
    return previous + (travel - previous) * (1 - 2 ** (-dt / half_life))


def compile_lens():
    program = shaders.compileProgram(shaders.compileShader(VERTEX, GL.GL_VERTEX_SHADER),
                                     shaders.compileShader(FRAGMENT, GL.GL_FRAGMENT_SHADER))
    names = ('backdrop', 'pixels', 'body_height', 'interaction', 'surface', 'panel_radius',
             'glass_tone', 'clear_mode', 'glass_blur', 'glass_opacity', 'sample_origin', 'sample_scale',
             'motion', 'elapsed', 'appearance')
    return program, {name: GL.glGetUniformLocation(program, name) for name in names}


def make_lens_texture():
    texture = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
    for parameter, value in (
        (GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
        (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE),
    ):
        GL.glTexParameteri(GL.GL_TEXTURE_2D, parameter, value)
    return texture


def paint_optic(program, uniform, pixel_width, sample_rect, motion, elapsed, vertices, appearance=1.0,
                body_height=0.0, interaction=(0.0, 0.0), panel_radius=0.0,
                surface=(0.0, 0.0, 1.0, 1.0), glass_tone=0.0, glass_blur=0.0, glass_opacity=1.0, clear_mode=0.0):
    GL.glUseProgram(program)
    GL.glUniform1i(uniform['backdrop'], 0)
    GL.glUniform1f(uniform['pixels'], pixel_width)
    GL.glUniform1f(uniform['body_height'], body_height)
    GL.glUniform2f(uniform['interaction'], *interaction)
    GL.glUniform4f(uniform['surface'], *surface)
    GL.glUniform1f(uniform['panel_radius'], panel_radius)
    GL.glUniform1f(uniform['clear_mode'], clear_mode)
    GL.glUniform1f(uniform['glass_tone'], glass_tone)
    GL.glUniform1f(uniform['glass_blur'], glass_blur)
    GL.glUniform1f(uniform['glass_opacity'], glass_opacity)
    GL.glUniform2f(uniform['sample_origin'], *sample_rect[:2])
    GL.glUniform2f(uniform['sample_scale'], *sample_rect[2:])
    GL.glUniform2f(uniform['motion'], motion.x(), motion.y())
    GL.glUniform1f(uniform['elapsed'], elapsed)
    GL.glUniform1f(uniform['appearance'], appearance)
    GL.glBegin(GL.GL_QUADS)
    for (x, y), (u, v) in zip(vertices, ((0, 1), (1, 1), (1, 0), (0, 0))):
        GL.glTexCoord2f(u, v)
        GL.glVertex2f(x, y)
    GL.glEnd()
    GL.glUseProgram(0)


class DesktopBubble(QOpenGLWidget):
    MARGIN = 40
    TILE_STEP = 16
    def __init__(self, dock_provider=None):
        flags=(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
               Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
               Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None,flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        fmt=QSurfaceFormat(); fmt.setVersion(2,1); fmt.setAlphaBufferSize(8); fmt.setSwapInterval(0); self.setFormat(fmt)
        self.setWindowTitle('Burbuja de Cicerón'); self.setFixedSize(116,116)
        self.frame=None; self.program=None; self.texture=None; self.gl_error=None; self.frame_dirty=False; self.texture_size=None; self.started=time.monotonic()
        self.dock_provider = dock_provider
        self.surface_patches = []
        self.last_surface_grab = 0.0
        self.frame_origin = QPoint()
        self.worker = None
        self.capture_source = object()
        self.native_frame = None
        self.last_native_sample = (0.0, 0.0)
        self.last_request = None
        self.photo_timer = QTimer(self)
        self.photo_timer.setSingleShot(True)
        self.photo_timer.timeout.connect(self.resume_capture)
        self.renderer = ''
        self.capture_error = None
        self.motion = QPointF()
        self.previous_tick = 0.0
        self.timer=QTimer(self); self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)

    def initializeGL(self):
        try:
            self.renderer = GL.glGetString(GL.GL_RENDERER).decode(errors='replace')
            self.program, self.uniform = compile_lens()
            self.texture = make_lens_texture()
        except Exception as e: self.gl_error=str(e)

    def start(self):
        self.follow_cursor(); self.show()
        if not self.isValid() or self.gl_error:
            reason=self.gl_error or 'No se pudo iniciar la aceleración gráfica.'
            self.close(); raise RuntimeError(reason)
        if not set_affinity(int(self.winId()), 0x11):
            self.close()
            raise RuntimeError('Windows no permitió separar el fondo de la lente.')
        self.tick()
        self.timer.start()
        self.raise_()

    def follow_cursor(self):
        pos=QCursor.pos()-QPoint(self.width()//2,self.height()//2)
        if pos!=self.pos(): self.move(pos)

    def tick(self):
        previous_position = self.pos()
        self.follow_cursor()
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            return
        # Leave time for Qt to dispatch input and compose the other windows.
        interval = 1 / min(60, max(30, screen.refreshRate()))
        timer_ms = max(4, round(1000 * interval))
        if self.timer.interval() != timer_ms:
            self.timer.setInterval(timer_ms)

        now = time.perf_counter()
        dt = min(0.1, max(0.001, now - self.previous_tick))
        self.previous_tick = now
        was_moving = self.motion.manhattanLength() > 0.01
        self.motion = pointer_motion(self.motion, self.pos() - previous_position, dt)
        self.update_surface_patches(now)
        self.select_capture()
        if self.worker is not None:
            request = self.capture_request(screen, interval)
            if request != self.last_request:
                self.worker.submit(request)
                self.last_request = request
            if self.worker.error is not None:
                self.capture_error = self.worker.error
                self.stop_capture_worker()
            else:
                latest = self.worker.latest
                if latest is not None and latest is not self.native_frame and self.tile_covers_window(latest):
                    self.native_frame = latest
                    (x, y, dpr), size, _, _ = latest
                    self.last_native_sample = ((self.x() - x) * dpr / size,
                                               (self.y() - y) * dpr / size)
                    self.frame_dirty = True
        if self.native_frame is not None and (
                self.frame_dirty or was_moving or previous_position != self.pos()):
            self.update()

    def select_capture(self):
        dock = self.dock_provider() if self.dock_provider is not None else None
        source = dock.backdrop if dock is not None else None
        if source is not None and source.closed.is_set():
            source = None
        if self.capture_source is source:
            return
        self.stop_capture_worker()
        self.capture_source = source
        self.last_request = None
        try:
            self.worker = source.lens_reader() if source is not None else LensCapture()
        except (ImportError, OSError, RuntimeError) as error:
            self.capture_error = str(error)

    def stop_capture_worker(self):
        if self.worker is None:
            return
        self.worker.close()
        self.worker = None

    def capture_request(self, screen, interval):
        tile = self.geometry().adjusted(-self.MARGIN, -self.MARGIN, self.MARGIN, self.MARGIN)
        step = self.TILE_STEP
        tile.moveTopLeft(QPoint(tile.x() // step * step, tile.y() // step * step))
        scale = screen.devicePixelRatio()
        origin = (tile.x(), tile.y(), scale)
        if self.last_request is not None and self.last_request[0] == origin and self.last_request[2] == interval:
            return self.last_request
        size = round(tile.width() * scale)
        regions = []
        for monitor in QApplication.screens():
            geometry = monitor.geometry()
            area = tile.intersected(geometry)
            if area.isEmpty():
                continue
            dpr = monitor.devicePixelRatio()
            x, y = area.x() - geometry.x(), area.y() - geometry.y()
            bounds = (round(x * dpr), round(y * dpr),
                      round((x + area.width()) * dpr), round((y + area.height()) * dpr))
            x, y = area.x() - tile.x(), area.y() - tile.y()
            left, top = round(x * scale), round(y * scale)
            target = (left, top, round((x + area.width()) * scale) - left,
                      round((y + area.height()) * scale) - top)
            regions.append((monitor.name().casefold(), bounds, target))
        client = client_bounds(int(self.winId()))
        physical = (client[0] + round((tile.x()-self.x()) * scale),
                    client[1] + round((tile.y()-self.y()) * scale)) if client is not None else None
        return origin, size, interval, tuple(regions), physical

    def tile_covers_window(self, frame):
        (x, y, scale), size, _, _ = frame
        return (0 <= self.x() - x <= size / scale - self.width() + .5 and
                0 <= self.y() - y <= size / scale - self.height() + .5)

    def update_surface_patches(self, now):
        if self.dock_provider is None:
            return
        dock = self.dock_provider()
        windows = dock.excluded_glass_windows() if dock is not None else ()
        lens = self.geometry()
        if not any(window.geometry().intersects(lens) for window in windows):
            if self.surface_patches:
                self.surface_patches = []
                self.frame_dirty = True
            self.last_surface_grab = 0.0
            return
        if now - self.last_surface_grab < 1 / 20:
            return
        self.last_surface_grab = now
        padding = self.MARGIN + self.TILE_STEP
        tile = lens.adjusted(-padding, -padding, padding, padding)
        patches = []
        for window in windows:
            area = tile.intersected(window.geometry())
            if not area.isEmpty():
                image = dock.lens_snapshot(window, area)
                if not image.isNull():
                    patches.append((area.topLeft(), image))
        self.surface_patches = patches
        self.frame_dirty = True

    def show_in_screenshots(self):
        if not self.isVisible() or not set_affinity(int(self.winId()), 0):
            return False
        self.timer.stop()
        if self.worker is not None:
            self.worker.submit(None)
        self.photo_timer.start(20000)
        return True

    def resume_capture(self):
        if not self.isVisible():
            return
        if not set_affinity(int(self.winId()), 0x11):
            self.close()
            return
        self.last_request = None
        self.native_frame = None
        if self.worker is not None:
            self.worker.latest = None
        self.tick()
        self.timer.start()

    def paintGL(self):
        GL.glClearColor(0,0,0,0); GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self.gl_error or self.program is None:
            return
        origin_x, origin_y, scale = 0.0, 0.0, 1.0
        if self.frame is not None:
            width, height = self.frame.width(), self.frame.height()
            pixel_format = GL.GL_RGBA
            pixels = self.frame.constBits()
            position, dpr = self.frame_origin, self.frame.devicePixelRatio()
        elif self.native_frame is not None:
            (x, y, dpr), width, pixels, _ = self.native_frame
            height = width
            if self.tile_covers_window(self.native_frame):
                self.last_native_sample = ((self.x() - x) * dpr / width,
                                           (self.y() - y) * dpr / height)
            origin_x, origin_y = self.last_native_sample
            scale = self.width() * dpr / width
            pixel_format = GL.GL_BGRA
            position = QPoint(x, y)
        else:
            return
        GL.glDisable(GL.GL_BLEND); GL.glBindTexture(GL.GL_TEXTURE_2D,self.texture)
        if self.frame_dirty:
            if self.surface_patches:
                if self.frame is not None:
                    composed = self.frame.copy()
                else:
                    composed = QImage(pixels.data, width, height, width * 4,
                                      QImage.Format.Format_RGB32).copy()
                    composed.setDevicePixelRatio(dpr)
                painter = QPainter(composed)
                for origin, patch in self.surface_patches:
                    painter.drawImage(origin - position, patch)
                painter.end()
                pixels = composed.constBits()
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT,1)
            size=(width,height)
            if self.texture_size != size:
                GL.glTexImage2D(GL.GL_TEXTURE_2D,0,GL.GL_RGBA,width,height,0,pixel_format,GL.GL_UNSIGNED_BYTE,pixels); self.texture_size=size
            else:
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D,0,0,0,width,height,pixel_format,GL.GL_UNSIGNED_BYTE,pixels)
            self.frame_dirty=False
        paint_optic(self.program, self.uniform, width * scale,
                    (origin_x, origin_y, scale, scale), self.motion,
                    time.monotonic() - self.started, ((-1, -1), (1, -1), (1, 1), (-1, 1)))

    def closeEvent(self,event):
        self.timer.stop()
        self.photo_timer.stop()
        self.stop_capture_worker()
        self.frame = None
        self.native_frame = None
        if self.isValid():
            self.makeCurrent()
            if self.texture is not None: GL.glDeleteTextures([self.texture]); self.texture=None
            if self.program is not None: GL.glDeleteProgram(self.program); self.program=None
            self.doneCurrent()
        super().closeEvent(event)


def check_desktop_lens(app):
    """Return the active renderer and whether native capture delivers a frame."""
    lens = DesktopBubble()
    try:
        lens.start()
        result = {}

        def finish():
            worker = lens.worker
            result.update(
                renderer=lens.renderer,
                native_capture=worker is not None and worker.latest is not None,
                error=lens.capture_error or (worker.error if worker else None),
                backend=worker.backend if worker else None,
            )
            app.exit()

        QTimer.singleShot(4200, finish)
        app.exec()
        return result
    finally:
        lens.close()
