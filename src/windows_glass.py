"""Windows backdrop capture that keeps layered Cicerón surfaces screenshot-visible."""
import ctypes as C
from ctypes import wintypes as W
import os

from PySide6.QtGui import QImage


def bind(library, name, result, *args):
    call = getattr(library, name)
    call.argtypes = args
    call.restype = result
    return call


user = C.WinDLL('user32')
gdi = C.WinDLL('gdi32')
kernel = C.WinDLL('kernel32')
get_dc = bind(user, 'GetDC', W.HDC, W.HWND)
release_dc = bind(user, 'ReleaseDC', C.c_int, W.HWND, W.HDC)
get_rect = bind(user, 'GetClientRect', W.BOOL, W.HWND, C.POINTER(W.RECT))
screen_origin = bind(user, 'ClientToScreen', W.BOOL, W.HWND, C.POINTER(W.POINT))
get_style = bind(user, 'GetWindowLongW', W.LONG, W.HWND, C.c_int)
set_affinity = bind(user, 'SetWindowDisplayAffinity', W.BOOL, W.HWND, W.DWORD)
compatible_dc = bind(gdi, 'CreateCompatibleDC', W.HDC, W.HDC)
delete_dc = bind(gdi, 'DeleteDC', W.BOOL, W.HDC)
select = bind(gdi, 'SelectObject', W.HANDLE, W.HDC, W.HANDLE)
delete = bind(gdi, 'DeleteObject', W.BOOL, W.HANDLE)
make_dib = bind(gdi, 'CreateDIBSection', W.HANDLE, W.HDC, C.c_void_p, W.UINT,
                C.POINTER(C.c_void_p), W.HANDLE, W.DWORD)
blit = bind(gdi, 'BitBlt', W.BOOL, W.HDC, C.c_int, C.c_int, C.c_int, C.c_int,
            W.HDC, C.c_int, C.c_int, W.DWORD)
stretch_blit = bind(gdi, 'StretchBlt', W.BOOL, W.HDC, C.c_int, C.c_int, C.c_int, C.c_int,
                   W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.DWORD)
stretch_mode = bind(gdi, 'SetStretchBltMode', C.c_int, W.HDC, C.c_int)


class BitmapHeader(C.Structure):
    _fields_ = [('size', W.DWORD), ('width', W.LONG), ('height', W.LONG),
                ('planes', W.WORD), ('bits', W.WORD), ('compression', W.DWORD),
                ('image_size', W.DWORD), ('x_ppm', W.LONG), ('y_ppm', W.LONG),
                ('used', W.DWORD), ('important', W.DWORD)]


def client_bounds(hwnd):
    rect, origin = W.RECT(), W.POINT()
    if not get_rect(hwnd, C.byref(rect)) or not screen_origin(hwnd, C.byref(origin)):
        return None
    return origin.x, origin.y, rect.right, rect.bottom


class BackdropCapture:
    def __init__(self):
        self.dc = self.bitmap = self.previous = None
        self.data = C.c_void_p()
        self.size = (0, 0)

    def close(self):
        if self.previous:
            select(self.dc, self.previous)
        if self.bitmap:
            delete(self.bitmap)
        if self.dc:
            delete_dc(self.dc)
        self.dc = self.bitmap = self.previous = None
        self.size = (0, 0)

    def prepare(self, source, width, height):
        self.close()
        self.dc = compatible_dc(source)
        header = BitmapHeader(C.sizeof(BitmapHeader), width, -height, 1, 32)
        if self.dc:
            self.bitmap = make_dib(source, C.byref(header), 0, C.byref(self.data), None, 0)
        if self.bitmap:
            self.previous = select(self.dc, self.bitmap)
        if not self.previous or self.previous == C.c_void_p(-1).value:
            self.previous = None
            self.close()
            return False
        self.size = (width, height)
        return True

    def capture_behind(self, hwnd):
        # The caller excludes its window from capture while the material is live.
        geometry = client_bounds(hwnd)
        if geometry is None:
            return QImage()
        return self.capture_region(geometry)

    def capture_region(self, bounds):
        _, _, width, height = bounds
        pixels = self.read_bgra(*bounds)
        if pixels is None:
            return QImage()
        return QImage(pixels, width, height, width * 4, QImage.Format.Format_RGB32).convertToFormat(
            QImage.Format.Format_RGBA8888)

    def capture_reduced(self, bounds):
        pixels = self.read_bgra(*bounds, reduced=True)
        if pixels is None:
            pixels = self.read_bgra(*bounds)
        if pixels is None:
            return QImage()
        width, height = self.size
        # Publish an image owned by Qt to consumers on the GUI thread.
        return QImage(pixels, width, height, width * 4, QImage.Format.Format_RGB32).copy()

    def read_bgra(self, x, y, width, height, include_layered=False, reduced=False):
        if width < 1 or height < 1:
            return None
        source = get_dc(None)
        if not source:
            return None
        try:
            size = ((width + 1) // 2, (height + 1) // 2) if reduced else (width, height)
            if self.size != size and not self.prepare(source, *size):
                return None
            operation = 0x00CC0020 | (0x40000000 if include_layered else 0)
            if reduced:
                stretch_mode(self.dc, 3)  # COLORONCOLOR; the GPU filters the smaller texture.
                copied = stretch_blit(self.dc, 0, 0, *size, source, x, y, width, height, operation)
            else:
                copied = blit(self.dc, 0, 0, width, height, source, x, y, operation)
            if not copied:
                return None
            return C.string_at(self.data, size[0] * size[1] * 4)
        finally:
            release_dc(None, source)


class PowerStatus(C.Structure):
    _fields_ = [('ac', W.BYTE), ('flags', W.BYTE), ('percentage', W.BYTE),
                ('saving', W.BYTE), ('seconds', W.DWORD), ('total_seconds', W.DWORD)]


get_power = bind(kernel, 'GetSystemPowerStatus', W.BOOL, C.POINTER(PowerStatus))


def energy_saver_active():
    status = PowerStatus()
    return bool(get_power(C.byref(status)) and status.saving == 1)


next_window = bind(user, 'GetWindow', W.HWND, W.HWND, W.UINT)
window_rect = bind(user, 'GetWindowRect', W.BOOL, W.HWND, C.POINTER(W.RECT))
visible = bind(user, 'IsWindowVisible', W.BOOL, W.HWND)
enabled = bind(user, 'IsWindowEnabled', W.BOOL, W.HWND)
minimized = bind(user, 'IsIconic', W.BOOL, W.HWND)
window_class = bind(user, 'GetClassNameW', C.c_int, W.HWND, W.LPWSTR, C.c_int)
to_client = bind(user, 'ScreenToClient', W.BOOL, W.HWND, C.POINTER(W.POINT))
child_at = bind(user, 'ChildWindowFromPointEx', W.HWND, W.HWND, W.POINT, W.UINT)
post_message = bind(user, 'PostMessageW', W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
foreground_window = bind(user, 'GetForegroundWindow', W.HWND)
root_window = bind(user, 'GetAncestor', W.HWND, W.HWND, W.UINT)
window_thread = bind(user, 'GetWindowThreadProcessId', W.DWORD, W.HWND, C.POINTER(W.DWORD))
window_at = bind(user, 'WindowFromPoint', W.HWND, W.POINT)
set_window_pos = bind(user, 'SetWindowPos', W.BOOL, W.HWND, W.HWND,
                      C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
mouse_hook_proc = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, W.WPARAM, W.LPARAM)
install_mouse_hook = bind(user, 'SetWindowsHookExW', W.HANDLE, C.c_int, mouse_hook_proc, W.HINSTANCE, W.DWORD)
uninstall_mouse_hook = bind(user, 'UnhookWindowsHookEx', W.BOOL, W.HANDLE)
next_mouse_hook = bind(user, 'CallNextHookEx', C.c_ssize_t, W.HANDLE, C.c_int, W.WPARAM, W.LPARAM)
module_handle = bind(kernel, 'GetModuleHandleW', W.HMODULE, W.LPCWSTR)
dwm = C.WinDLL('dwmapi')
get_dwm_attribute = bind(dwm, 'DwmGetWindowAttribute', W.LONG, W.HWND, W.DWORD, C.c_void_p, W.DWORD)


def restore_above_taskbar(hwnd):
    bounds = client_bounds(hwnd)
    if not bounds:
        return
    x, y, width, height = bounds
    hit = window_at(W.POINT(x + width // 2, y + height // 2))
    if not hit or hit == hwnd:
        return
    root = root_window(hit, 2)  # GA_ROOT
    name = C.create_unicode_buffer(64)
    if root and window_class(root, name, len(name)) and name.value in ('Shell_TrayWnd', 'Shell_SecondaryTrayWnd'):
        # Explorer can raise the taskbar above other topmost windows on click.
        set_window_pos(hwnd, -1, 0, 0, 0, 0, 0x0013)  # TOPMOST, NOSIZE | NOMOVE | NOACTIVATE


class PanelMousePress:
    """Post the target of a button press without grabbing or consuming it."""
    MESSAGE = 0x8351

    def __init__(self):
        self.hook = None
        self.receiver = None
        self.procedure = mouse_hook_proc(self.notify)

    def start(self, receiver, panel):
        self.receiver = receiver
        self.panel = panel
        if self.hook is None:
            self.hook = install_mouse_hook(14, self.procedure, module_handle(None), 0)  # WH_MOUSE_LL

    def stop(self):
        self.receiver = None
        if self.hook is not None and uninstall_mouse_hook(self.hook):
            self.hook = None

    def notify(self, code, message, data):
        if self.receiver and code == 0 and message in (0x0201, 0x0204, 0x0207):
            point = W.POINT.from_address(data)  # MSLLHOOKSTRUCT starts with the screen point.
            post_message(self.receiver, self.MESSAGE, window_at(point) or 0, self.panel)
        return next_mouse_hook(None, code, message, data)


def window_belongs_to(hwnd, top):
    current = root_window(hwnd, 2) if hwnd else None  # GA_ROOT
    while current:
        if current == top:
            return True
        current = next_window(current, 4)  # GW_OWNER
    return False


def window_below(hwnd, point):
    candidate = next_window(hwnd, 2)  # GW_HWNDNEXT
    seen = {hwnd}
    rect = W.RECT()
    while candidate and candidate not in seen:
        seen.add(candidate)
        cloaked = W.DWORD()
        if (is_external_window(candidate) and not get_style(candidate, -20) & 0x20
                and window_rect(candidate, C.byref(rect))
                and rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom):
            get_dwm_attribute(candidate, 14, C.byref(cloaked), C.sizeof(cloaked))
            if not cloaked.value:
                while True:
                    local = W.POINT(point.x, point.y)
                    if not to_client(candidate, C.byref(local)):
                        break
                    child = child_at(candidate, local, 0x0007)
                    if not child or child in seen:
                        break
                    candidate = child
                    seen.add(child)
                return candidate
        candidate = next_window(candidate, 2)
    return None


def is_external_window(hwnd):
    if not hwnd or not visible(hwnd) or not enabled(hwnd) or minimized(hwnd):
        return False
    pid = W.DWORD()
    if not window_thread(hwnd, C.byref(pid)) or pid.value == os.getpid():
        return False
    name = C.create_unicode_buffer(64)
    window_class(hwnd, name, len(name))
    return name.value not in ('Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'NotifyIconOverflowWindow',
                              'Progman', 'WorkerW')


def wheel_point(active, overlay, point):
    bounds = client_bounds(active)
    if bounds is None:
        return None
    left, top, width, height = bounds
    if width <= 0 or height <= 0:
        return None
    surface = client_bounds(overlay)
    xs = [point.x]
    if surface is not None:
        xs.extend((surface[0] - 2, surface[0] + surface[2] + 2))
    xs.extend(left + width * n // 4 for n in (2, 1, 3))
    ys = (point.y, top + height // 2, top + height * 3 // 4)
    # Chromium checks the real window at the supplied screen coordinates.
    for y in ys:
        for x in xs:
            if left <= x < left + width and top <= y < top + height:
                hit = window_at(W.POINT(x, y))
                if hit and (hit == active or root_window(hit, 2) == active):
                    target = active if get_style(hit, -20) & 0x20 else hit
                    return target, (x & 0xffff) | ((y & 0xffff) << 16)
    return None


def forward_wheel(hwnd, message, previous_app):
    """Redirect the wheel from a Cicerón surface to the user's other app."""
    point = W.POINT(C.c_short(message.lParam & 0xffff).value,
                    C.c_short((message.lParam >> 16) & 0xffff).value)
    below = window_below(hwnd, point)
    active = foreground_window()
    if not is_external_window(active):
        active = previous_app if is_external_window(previous_app) else None
    for candidate in dict.fromkeys((active, root_window(below, 2) if below else None)):
        if candidate:
            result = wheel_point(candidate, hwnd, point)
            if result is not None:
                target, position = result
                if post_message(target, message.message, message.wParam, position):
                    return True
    return False
