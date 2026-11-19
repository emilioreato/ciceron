"""Native Windows tray and birthday balloons. No external Python dependencies."""
import os
from time import monotonic


def app_name(data_folder):
    from hashlib import sha256
    return "HappyBirthday.Ciceron." + sha256(os.fsencode(os.path.normcase(str(data_folder)))).hexdigest()[:24]


if os.name == "nt":
    import ctypes as C
    from ctypes import wintypes as W

    USER = C.WinDLL("user32", use_last_error=True)
    KERNEL = C.WinDLL("kernel32", use_last_error=True)
    SHELL = C.WinDLL("shell32", use_last_error=True)
    WNDPROC = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    CALLBACK = 0x8001
    ACTIVATE = 0x8002

    class WNDCLASS(C.Structure):
        _fields_ = [
            ("style", W.UINT), ("proc", WNDPROC), ("cls_extra", C.c_int), ("win_extra", C.c_int),
            ("instance", W.HINSTANCE), ("icon", W.HICON), ("cursor", W.HANDLE),
            ("background", W.HBRUSH), ("menu", W.LPCWSTR), ("name", W.LPCWSTR),
        ]

    class NotifyIcon(C.Structure):
        _fields_ = [
            ("size", W.DWORD), ("hwnd", W.HWND), ("id", W.UINT), ("flags", W.UINT),
            ("callback", W.UINT), ("icon", W.HICON), ("tip", W.WCHAR * 128),
            ("state", W.DWORD), ("state_mask", W.DWORD), ("info", W.WCHAR * 256),
            ("timeout_or_version", W.UINT), ("title", W.WCHAR * 64), ("info_flags", W.DWORD),
            ("guid", C.c_ubyte * 16), ("balloon_icon", W.HICON),
        ]

    def api(dll, name, result, *args):
        function = getattr(dll, name)
        function.restype = result
        function.argtypes = args
        return function

    FindWindow = api(USER, "FindWindowW", W.HWND, W.LPCWSTR, W.LPCWSTR)
    PostMessage = api(USER, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    Module = api(KERNEL, "GetModuleHandleW", W.HINSTANCE, W.LPCWSTR)
    Register = api(USER, "RegisterClassW", W.ATOM, C.POINTER(WNDCLASS))
    Unregister = api(USER, "UnregisterClassW", W.BOOL, W.LPCWSTR, W.HINSTANCE)
    RegisterMessage = api(USER, "RegisterWindowMessageW", W.UINT, W.LPCWSTR)
    CreateWindow = api(USER, "CreateWindowExW", W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                       C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p)
    DefWindow = api(USER, "DefWindowProcW", C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    DestroyWindow = api(USER, "DestroyWindow", W.BOOL, W.HWND)
    LoadImage = api(USER, "LoadImageW", W.HANDLE, W.HINSTANCE, W.LPCWSTR,
                    W.UINT, C.c_int, C.c_int, W.UINT)
    DestroyIcon = api(USER, "DestroyIcon", W.BOOL, W.HICON)
    Notify = api(SHELL, "Shell_NotifyIconW", W.BOOL, W.DWORD, C.POINTER(NotifyIcon))
    QueryState = api(SHELL, "SHQueryUserNotificationState", C.c_long, C.POINTER(C.c_int))
    CreateMenu = api(USER, "CreatePopupMenu", W.HMENU)
    AppendMenu = api(USER, "AppendMenuW", W.BOOL, W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR)
    DestroyMenu = api(USER, "DestroyMenu", W.BOOL, W.HMENU)
    SetForeground = api(USER, "SetForegroundWindow", W.BOOL, W.HWND)
    WindowProcess = api(USER, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
    AllowForeground = api(USER, "AllowSetForegroundWindow", W.BOOL, W.DWORD)
    WindowStyle = api(USER, "GetWindowLongW", C.c_long, W.HWND, C.c_int)
    SetPosition = api(USER, "SetWindowPos", W.BOOL, W.HWND, W.HWND,
                      C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
    GetCursor = api(USER, "GetCursorPos", W.BOOL, C.POINTER(W.POINT))
    TrackMenu = api(USER, "TrackPopupMenu", W.UINT, W.HMENU, W.UINT,
                    C.c_int, C.c_int, C.c_int, W.HWND, C.c_void_p)


def activate_existing(data_folder):
    if os.name == "nt":
        name = app_name(data_folder)
        target = FindWindow(name, name)
        if target:
            owner = W.DWORD()
            if WindowProcess(target, C.byref(owner)) and owner.value:
                AllowForeground(owner.value)
        return bool(target and PostMessage(target, ACTIVATE, 0, 0))
    return False


def bring_to_front(hwnd):
    if os.name != "nt" or SetForeground(hwnd):
        return
    flags = 0x0013  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    if WindowStyle(hwnd, -20) & 0x8:  # WS_EX_TOPMOST
        SetPosition(hwnd, -1, 0, 0, 0, 0, flags)
    elif SetPosition(hwnd, -1, 0, 0, 0, 0, flags):  # HWND_TOPMOST
        # Return to the top of the normal band immediately (HWND_NOTOPMOST).
        SetPosition(hwnd, -2, 0, 0, 0, 0, flags)


def ellipsize(value, utf16_units):
    encoded = value.encode("utf-16-le")
    if len(encoded) <= utf16_units * 2:
        return value
    return encoded[: (utf16_units - 1) * 2].decode("utf-16-le", "ignore") + "…"


class Tray:
    def __init__(self, root, data_folder, icon, restore, quit_app, on_clock=None, on_click=None, *,
                 hidden=False):
        self.available = False
        self.in_flight = None
        if os.name != "nt":
            return
        self.root, self.restore, self.quit_app = root, restore, quit_app
        self.on_clock, self.on_click = on_clock, on_click
        self.hidden = hidden
        self.name = app_name(data_folder)
        self.instance = Module(None)
        self.proc = WNDPROC(self._events)
        self.taskbar = RegisterMessage("TaskbarCreated")
        self.registered = bool(Register(C.byref(WNDCLASS(instance=self.instance, proc=self.proc, name=self.name))))
        self.hwnd = self.icon = None
        self.visible = False
        if not self.registered:
            return
        self.hwnd = CreateWindow(0, self.name, self.name, 0x80000000, 0, 0, 0, 0,
                                 None, None, self.instance, None)
        self.icon = LoadImage(None, str(icon), 1, 0, 0, 0x0010 | 0x0040)
        self.available = bool(self.hwnd and self.icon)

    def _events(self, hwnd, message, w_param, l_param):
        event = l_param & 0xffff  # Also handles legacy (pre-version-4) callbacks.
        if message == ACTIVATE or (message == CALLBACK and event in (0x0202, 0x0203, 0x0400, 0x0401)):
            self.root.after_idle(self.restore)
            return 0
        if message == CALLBACK and event in (0x0205, 0x007B):
            self.root.after_idle(self._menu)
            return 0
        if message == CALLBACK and event in (0x0402, 0x0404, 0x0405):
            # A show, dismissal by the user, or a timeout confirms display.
            if self.in_flight:
                callback, started = self.in_flight
                self.in_flight = (None, started) if event == 0x0402 else None
                if callback:
                    self.root.after_idle(callback)
            if event == 0x0405:
                self.root.after_idle(self.on_click or self.restore)
            return 0
        if message == CALLBACK and event == 0x0403:
            self.in_flight = None
            return 0
        if (message == 0x001E or (message == 0x0218 and w_param in (0x0007, 0x0012))) and self.on_clock:
            self.root.after_idle(self.on_clock)
        if self.taskbar and message == self.taskbar:
            self.in_flight = None
            if self.visible:
                self.visible = False
                self.root.after_idle(self._restore_after_restart)
            return 0
        return DefWindow(hwnd, message, w_param, l_param)

    def _restore_after_restart(self):
        if not self.ensure() and not self.hidden and self.root.state() == "withdrawn":
            self.restore()

    def _menu(self):
        if not self.hwnd:
            return
        menu = CreateMenu()
        if not menu:
            return
        try:
            AppendMenu(menu, 0, 1, "Abrir Happy Birthday")
            if self.quit_app is not None:
                AppendMenu(menu, 0x0800, 0, None)
                AppendMenu(menu, 0, 2, "Salir y pausar avisos")
            point = W.POINT()
            if not GetCursor(C.byref(point)):
                return
            SetForeground(self.hwnd)
            choice = TrackMenu(menu, 0x0100 | 0x0080 | 0x0002, point.x, point.y, 0, self.hwnd, None)
            PostMessage(self.hwnd, 0, 0, 0)
            if choice:
                self.root.after_idle(self.restore if choice == 1 else self.quit_app)
        finally:
            DestroyMenu(menu)

    def _data(self):
        return NotifyIcon(size=C.sizeof(NotifyIcon), hwnd=self.hwnd, id=1)

    def ensure(self):
        if not self.available:
            return False
        if not self.visible:
            data = self._data()
            data.flags = 1 | 2 | 4 | 0x80  # NIF_SHOWTIP for version 4
            if self.hidden:
                data.flags |= 8  # NIF_STATE
                data.state = data.state_mask = 1  # NIS_HIDDEN
            data.icon = self.icon
            data.tip = "Happy Birthday · Abrir agenda"
            data.callback = CALLBACK
            self.visible = bool(Notify(0, C.byref(data)))
            if self.visible:
                data.timeout_or_version = 4
                Notify(4, C.byref(data))
        return self.visible

    def show(self, title, body, on_shown=lambda: None):
        if not self.ensure():
            return False
        if self.in_flight and monotonic() - self.in_flight[1] < 180:
            return False
        state = C.c_int()
        if QueryState(C.byref(state)) == 0 and state.value != 5:  # QUNS_ACCEPTS_NOTIFICATIONS
            return False
        data = self._data()
        data.flags = 0x10
        data.info = ellipsize(body, 255)
        data.title = ellipsize(title, 63)
        data.info_flags = (4 if self.hidden else 1) | 0x80  # NIIF_USER or NIIF_INFO, with quiet time
        if self.hidden:
            data.balloon_icon = self.icon
        data.timeout_or_version = 10000
        self.in_flight = (on_shown, monotonic())
        if Notify(1, C.byref(data)):
            return True
        if self.hidden:
            # Some shells accept a hidden icon but reject a custom balloon icon.
            data.info_flags = 1 | 0x80
            data.balloon_icon = None
            if Notify(1, C.byref(data)):
                return True
        self.in_flight = None
        return False

    def close(self):
        if os.name != "nt":
            return
        self.available = False
        if self.hwnd:
            if self.visible:
                Notify(2, C.byref(self._data()))
            DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.icon:
            DestroyIcon(self.icon)
            self.icon = None
        if self.registered:
            Unregister(self.name, self.instance)
            self.registered = False
