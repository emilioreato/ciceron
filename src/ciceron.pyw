"""Cicerón: centro personal para Windows, interfaz Qt."""
import ctypes, datetime as dt, json, math, os, sys, time, winreg
from ctypes import wintypes
from _ctypes import COMError
from app_identity import AppIdentity, file_icon_reference, resource_icon
from app_paths import (application_root, data_root, development_mode, instance_suffix,
                       resolve_app_path, source_installation_root, stored_app_path, windows_appdata_root)
from app_packages import PACKAGE_EXT, PackageStore, app_tags, fold_search
from browser_ui import BrowserDialog
from center_ui import (UI_VERSIONS, AppCardIdentity, clear_styles, CenterWindow, GlassDialog,
                       LibraryBanner, PreferenceBox, dark_mode, panel, scrolled_page, stylesheet)
from visual_playground import VisualDialog
from pathlib import Path
from PySide6.QtCore import (QAbstractNativeEventFilter, QFileSystemWatcher, QPoint, QSize, Qt,
                            QTimer, QDate, QTime, Signal)
from PySide6.QtGui import QIcon, QPainter, QColor, QPixmap, QPen
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QDateEdit, QTimeEdit, QCheckBox, QButtonGroup, QComboBox,
    QFrame, QFileDialog, QFileIconProvider, QInputDialog, QMessageBox, QSystemTrayIcon, QMenu,
    QAbstractSpinBox, QCalendarWidget, QStackedWidget, QToolButton)
from package_ui import edit_settings, install_packages
from data_ui import export_dialog, import_dialog
from power_state import low_power
from start_menu import StartMenuApps, pending_launches, request_launch
from windows_glass import CapturePrivacy, capture_mode, restore_above_taskbar

DATA = data_root()
CONFIG = DATA / 'config.json'; APPS = DATA / 'apps.json'
PACKAGE_TAGS = DATA / 'etiquetas-paquetes.json'
LAUNCH_REQUESTS = DATA / 'arranques-paquetes'
DEFAULT = dict(title='Mi objetivo', target='', show_timer=True, guardian=True,
               words='youtube, x.com, twitter, instagram', interval=3, topmost=True, geometry='', count_x_ratio=None,
               theme='system', glass=True, clarity='balanced',
               ui_version='v2', dock_motion=True, include_in_captures=True)
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'Ciceron'
STARTUP_ARGUMENT = '--inicio-silencioso'

def startup_target(value):
    """Extrae el ejecutable de una entrada Run, con o sin argumentos."""
    if not isinstance(value, str):
        return None
    command = os.path.expandvars(value.strip())
    if command.startswith('"'):
        end = command.find('"', 1)
        if end < 0:
            return None
        return command[1:end]
    return command.split(None, 1)[0] if command else None

def startup_command(executable):
    return f'"{executable}" {STARTUP_ARGUMENT}'

def read(path, default):
    try:
        with path.open(encoding='utf-8') as f: return json.load(f), False
    except FileNotFoundError: return default, False
    except (OSError, ValueError): return default, True

def write(path, value):
    DATA.mkdir(parents=True, exist_ok=True); tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def icon():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    image = base / 'assets' / 'ciceron.png'
    if image.is_file(): return QIcon(str(image))
    pix=QPixmap(64,64); pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#343946')); p.drawRoundedRect(2,2,60,60,16,16)
    p.setPen(QColor('white')); p.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,'C'); p.end()
    return QIcon(pix)

def activation_event_signaled(kernel, handle):
    result = kernel.WaitForSingleObject(handle, 0)
    if result == 0:  # WAIT_OBJECT_0; an auto-reset event is consumed.
        return True
    if result == 0x102:  # WAIT_TIMEOUT
        return False
    if result == 0xFFFFFFFF:  # WAIT_FAILED
        raise ctypes.WinError(kernel.GetLastError())
    raise OSError(f'WaitForSingleObject devolvió un estado inesperado: {result:#x}')

def watch_activation_event(app, kernel, handle, callback, power_changed=None, *, read_power=low_power,
                          additional_events=()):
    timer = QTimer(app)
    next_power_check = 0.0
    previous = None

    def update_power(now):
        nonlocal next_power_check, previous
        next_power_check = now + 15
        saving = read_power()
        if saving != previous:
            previous = saving
            timer.setInterval(1000 if saving else 200)
            if power_changed is not None:
                power_changed(saving)

    def poll():
        try:
            main_signaled = activation_event_signaled(kernel, handle)
            additional_callbacks = []
            for event_handle, action in additional_events:
                while activation_event_signaled(kernel, event_handle):
                    additional_callbacks.append(action)
        except (OSError, RuntimeError):
            timer.stop()
            return
        if main_signaled:
            callback()
        for action in additional_callbacks:
            action()
        now = time.monotonic()
        if now >= next_power_check:
            update_power(now)

    update_power(time.monotonic())
    timer.timeout.connect(poll)
    timer.start()
    return timer

class SuspendResumeFilter(QAbstractNativeEventFilter):
    """Oculta el centro antes de suspender o al reanudar automáticamente."""
    WM_POWERBROADCAST = 0x0218
    PBT_APMSUSPEND = 0x0004
    PBT_APMRESUMECRITICAL = 0x0006
    PBT_APMRESUMEAUTOMATIC = 0x0012

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.user32 = None
        self.registration = None

    def register(self, window):
        try:
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            register = user32.RegisterSuspendResumeNotification
            register.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            register.restype = wintypes.HANDLE
            handle = register(wintypes.HWND(int(window)), 0)
        except (AttributeError, OSError, TypeError, ValueError):
            return False
        if not handle:
            return False
        self.user32 = user32
        self.registration = handle
        return True

    def nativeEventFilter(self, event_type, message):
        if event_type == b'windows_generic_MSG':
            msg = wintypes.MSG.from_address(int(message))
            if (msg.message == self.WM_POWERBROADCAST and
                    msg.wParam in (self.PBT_APMSUSPEND, self.PBT_APMRESUMECRITICAL,
                                   self.PBT_APMRESUMEAUTOMATIC)):
                self.controller.prepare_for_power_transition()
        return False, 0

    def stop(self):
        if self.registration is None:
            return
        try:
            unregister = self.user32.UnregisterSuspendResumeNotification
            unregister.argtypes = [wintypes.HANDLE]
            unregister.restype = wintypes.BOOL
            unregister(self.registration)
        except (AttributeError, OSError, TypeError, ValueError):
            pass
        self.registration = None
        self.user32 = None

def watch_launch_requests(app, directory, callback):
    watcher = QFileSystemWatcher(app)
    scan = QTimer(watcher)
    scan.setSingleShot(True)

    def reconnect():
        paths = watcher.directories()
        if paths and not directory.is_dir():
            watcher.removePaths(paths)
        if not watcher.directories():
            try:
                directory.mkdir(parents=True, exist_ok=True)
                watcher.addPath(str(directory))
            except OSError:
                pass
        callback()
        if not watcher.directories():
            scan.start(1000)

    # The sender writes a temporary file and then publishes it by renaming it.
    watcher.directoryChanged.connect(lambda _: scan.start(40))
    scan.timeout.connect(reconnect)
    scan.start(0)
    return watcher

def caption(text,kind=None):
    return panel(kind or '', text)

def button(text,fn,primary=False):
    b=QPushButton(text); b.clicked.connect(fn)
    if primary: b.setObjectName('primary')
    return b

def target(cfg):
    try:
        value = dt.datetime.fromisoformat(cfg.get('target', ''))
        return value.astimezone().replace(tzinfo=None) if value.tzinfo is not None else value
    except (ValueError, TypeError, OverflowError, OSError):
        return None

def remaining(t, *, show_seconds=False):
    seconds=(t-dt.datetime.now()).total_seconds()
    if show_seconds:
        minutes, seconds = divmod(max(0, math.ceil(seconds)), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        clock = f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{days}d {clock}' if days else clock
    if seconds<=0: return 'Fecha alcanzada'
    days,minutes=divmod(int(seconds//60),1440); hours,minutes=divmod(minutes,60)
    if days:
        return f'{days}d {hours}h {minutes}m'
    if hours:
        return f'{hours}h {minutes}m'
    return f'{minutes}m' if minutes else '<1m'

def foreground():
    u=ctypes.windll.user32; u.GetForegroundWindow.restype=ctypes.c_void_p
    hwnd=u.GetForegroundWindow(); pid=ctypes.c_ulong()
    u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    u.GetWindowTextLengthW.argtypes=[ctypes.c_void_p]; u.GetWindowTextW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
    if not hwnd: return ''
    u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    if pid.value == os.getpid(): return ''
    n=u.GetWindowTextLengthW(hwnd); buf=ctypes.create_unicode_buffer(n+1)
    u.GetWindowTextW(hwnd,buf,n+1); return buf.value

def taskbar_y(screen, work, height):
    """Use only a horizontal area reserved by Windows, never the work area."""
    top=work.y()-screen.y()
    bottom=(screen.y()+screen.height())-(work.y()+work.height())
    if bottom >= height:
        return work.y()+work.height()+(bottom-height)//2
    if top >= height:
        return screen.y()+(top-height)//2
    return None

class ClearCheckBox(QCheckBox):
    """Keep the native checkbox behavior with a visible, understated indicator."""
    def paintEvent(self, event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked=self.isChecked(); enabled=self.isEnabled(); y=(self.height()-16)//2
        painter.setPen(QPen(QColor('#343943' if checked else '#a1a8b3'),1))
        painter.setBrush(QColor('#343943' if checked else '#ffffff'))
        painter.drawRoundedRect(1,y,15,15,4,4)
        if checked:
            pen=QPen(QColor('#ffffff')); pen.setWidthF(1.7); painter.setPen(pen)
            painter.drawLine(4,y+8,7,y+11); painter.drawLine(7,y+11,13,y+4)
        painter.setPen(self.palette().windowText().color() if enabled else QColor('#8b95a7'))
        painter.drawText(26,0,max(0,self.width()-26),self.height(),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,self.text())
        if self.hasFocus():
            painter.setPen(QPen(QColor('#8e96a3'),1,Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawRoundedRect(0,y-1,17,17,4,4)
        painter.end()

class CountdownButton(QPushButton):
    moved=Signal(int)
    visibility_changed=Signal()
    STACKING_RECHECK_MS = 300
    def __init__(self):
        super().__init__()
        self._closing = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._stacking_check = QTimer(self)
        self._stacking_check.setInterval(150)
        self._stacking_check.setSingleShot(True)
        self._stacking_check.timeout.connect(self._restore_stacking)
        self._stacking_monitor = QTimer(self)
        self._stacking_monitor.setInterval(self.STACKING_RECHECK_MS)
        self._stacking_monitor.timeout.connect(self._restore_stacking)

    def showEvent(self, event):
        super().showEvent(event)
        if self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            self._stacking_check.start()
            self._stacking_monitor.start()
        self.visibility_changed.emit()

    def hideEvent(self, event):
        self._stacking_check.stop()
        self._stacking_monitor.stop()
        super().hideEvent(event)
        self.visibility_changed.emit()

    def closeEvent(self, event):
        self._closing = True
        self._stacking_check.stop()
        self._stacking_monitor.stop()
        super().closeEvent(event)

    def _restore_stacking(self):
        if self.isVisible() and self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            restore_above_taskbar(int(self.winId()))

    def mousePressEvent(self, event):
        self._drag_start=event.globalPosition().toPoint()
        self._drag_origin=self.pos()
        self._dragging=False
        super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, '_drag_start'):
            delta=event.globalPosition().toPoint()-self._drag_start
            if not self._dragging and delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging=True; self.setDown(False)
            if self._dragging:
                screen=QApplication.primaryScreen()
                if screen:
                    bounds=screen.geometry()
                    x=max(bounds.x(),min(self._drag_origin.x()+delta.x(),bounds.x()+max(0,bounds.width()-self.width())))
                    self.move(x,self.y())
                return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event):
        if getattr(self,'_dragging',False):
            self._dragging=False; self.setDown(False); self.moved.emit(self.x()); event.accept(); return
        super().mouseReleaseEvent(event)

class TimerDialog(GlassDialog):
    preferred_size_changed = Signal()


class App:
    def __init__(self):
        data, broken=read(CONFIG,{}); self.cfg=DEFAULT.copy()
        if isinstance(data,dict): self.cfg.update({k:v for k,v in data.items() if k in DEFAULT})
        if self.cfg['theme'] not in ('system', 'light', 'dark'):
            self.cfg['theme'] = DEFAULT['theme']
        if self.cfg['clarity'] not in ('clear', 'balanced', 'contrast'):
            self.cfg['clarity'] = DEFAULT['clarity']
        if self.cfg['ui_version'] not in UI_VERSIONS:
            self.cfg['ui_version'] = DEFAULT['ui_version']
        try:
            self.cfg['interval'] = max(1, int(self.cfg['interval']))
        except (ValueError, TypeError, OverflowError):
            self.cfg['interval'] = DEFAULT['interval']
        self.apps, self.bad_apps=read(APPS,[])
        if not isinstance(self.apps,list) or any(not isinstance(i,dict) or not isinstance(i.get('name'),str) or not isinstance(i.get('path'),str) for i in self.apps): self.apps=[]; self.bad_apps=True
        else:
            try:
                self.apps = [dict(item, path=str(resolve_app_path(item['path']))) for item in self.apps]
            except (OSError, ValueError):
                self.apps=[]; self.bad_apps=True
        self.package_tags, self.bad_package_tags = read(PACKAGE_TAGS, {})
        if not isinstance(self.package_tags, dict):
            self.package_tags, self.bad_package_tags = {}, True
        self.packages = PackageStore(DATA / 'paquetes', DATA / 'datos-apps')
        self.start_menu = StartMenuApps(windows_appdata_root() / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Ciceron',
                                        self.install_dir() / 'Ciceron.exe')
        self.managed_apps = []
        self.birthday_host = None
        self.package_error = None
        try:
            self.packages.sweep()
        except (OSError, ValueError):
            pass  # A locked record can be read safely; debris can be retired at the next start.
        self.reload_packages()
        self.last_poll=0; self.last_alert=float('-inf'); self.alert=None
        self.background_low_power = False
        self.broken_config = broken or not isinstance(data, dict)
        self.dock = None
        self.dock_signature = None
        self.capture_privacy = CapturePrivacy(QApplication.instance())
        from edge_dock import AppWheelFilter
        self.wheel_filter = AppWheelFilter(self)
        QApplication.instance().installNativeEventFilter(self.wheel_filter)
        self.library_snapshot = None
        self.build_window()
        self.apply_appearance()
        QApplication.styleHints().colorSchemeChanged.connect(self.apply_appearance)
        self.count=CountdownButton(); self.count.setWindowTitle('Timer')
        self.count.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.count.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,bool(self.cfg['topmost']))
        self.count.setFixedSize(160,24); self.count.setWindowOpacity(0.9)
        self.update_timer_style()
        self.count.setToolTip('Clic para configurar · arrastra para mover en la barra')
        self.count.moved.connect(self._remember_count_position)
        self._count_fits=False
        self._count_hidden_by_layout=False
        self._count_screen=None
        QApplication.instance().primaryScreenChanged.connect(self._set_count_screen)
        self._set_count_screen(QApplication.primaryScreen())
        self.count.clicked.connect(lambda: self.open_tool('clock'))
        self.tray=QSystemTrayIcon(icon()); menu=QMenu(self.window)
        self.dock_visibility_action = menu.addAction('Ocultar barra lateral', self.toggle_edge_dock_visibility)
        menu.addSeparator()
        self.photo_timer = QTimer(self.window)
        self.photo_timer.setSingleShot(True)
        self.photo_timer.timeout.connect(self.finish_photo_mode)
        self.photo_action = menu.addAction('Captura de pantalla · 20 segundos', self.start_photo_mode)
        menu.addSeparator()
        menu.addAction('Salir', QApplication.quit)
        menu.aboutToShow.connect(self.update_tray_actions)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(self.window.windowTitle())
        self.tray.activated.connect(self.tray_clicked)
        self.tray.show()
        QTimer.singleShot(0, self.window, self.prepare_birthday)
        self.render()
        self.timer = QTimer(self.count)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.count.visibility_changed.connect(self.count_visibility_changed,
                                              Qt.ConnectionType.QueuedConnection)
        self.tick()
        if self.cfg['show_timer'] and target(self.cfg): self._show_count()
        if self.broken_config: QMessageBox.warning(self.window,'Configuración','No se pudo leer la configuración; se conservó el archivo original.')
        self.show_edge_dock()
    def save(self):
        if self.broken_config:
            QMessageBox.warning(self.window, 'Configuración no disponible',
                                'Revisa el archivo de configuración desde Estado antes de guardar cambios.')
            return False
        try: write(CONFIG,self.cfg); return True
        except OSError as e: QMessageBox.warning(self.window,'No se pudo guardar',str(e)); return False
    def _set_count_screen(self, screen):
        if self._count_screen is not None:
            try:
                self._count_screen.availableGeometryChanged.disconnect(self._position_count)
                self._count_screen.geometryChanged.disconnect(self._position_count)
            except (RuntimeError, TypeError): pass
        self._count_screen=screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self._position_count)
            screen.geometryChanged.connect(self._position_count)
            self._position_count()
    def _position_count(self, *args):
        if self._count_screen is None: return
        screen=self._count_screen.geometry(); work=self._count_screen.availableGeometry()
        y=taskbar_y(screen,work,self.count.height())
        self._count_fits=y is not None
        if y is None:
            if self.count.isVisible(): self._count_hidden_by_layout=True
            self.count.hide(); return
        ratio=self.cfg.get('count_x_ratio')
        if not isinstance(ratio,(float,int)) or isinstance(ratio,bool) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
            # Original position, shifted only 40 logical pixels to the left.
            desired_x=screen.x()+screen.width()*3//4-140
        else:
            desired_x=screen.x()+round((screen.width()-self.count.width())*ratio)
        x=max(screen.x(), min(desired_x, screen.x()+max(0,screen.width()-self.count.width())))
        self.count.move(x,y)
        if self._count_hidden_by_layout:
            self._count_hidden_by_layout=False
            if self.cfg['show_timer'] and target(self.cfg): self._show_count()
    def _show_count(self):
        if self._count_fits:
            self._count_hidden_by_layout=False
            self.count.show(); self.count.raise_()
            return True
        self._count_hidden_by_layout=True
        if hasattr(self,'tray'):
            self.tray.showMessage('Cicerón','No hay espacio horizontal disponible en la barra de tareas para mostrar el contador.',QSystemTrayIcon.MessageIcon.Information,5000)
        return False
    def _hide_count(self):
        self._count_hidden_by_layout=False
        self.count.hide()
    def count_visibility_changed(self):
        if (not self.count.isVisible() and not self.count._closing and
                not self._count_hidden_by_layout and self._count_fits and
                self.cfg['show_timer'] and target(self.cfg)):
            self._show_count()
        self.tick()
    def _remember_count_position(self, x):
        if self._count_screen is None: return
        screen=self._count_screen.geometry(); available=max(1,screen.width()-self.count.width())
        previous=self.cfg.get('count_x_ratio')
        self.cfg['count_x_ratio']=max(0.0,min(1.0,(x-screen.x())/available))
        if not self.save(): self.cfg['count_x_ratio']=previous
    def tray_clicked(self,reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_center()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_center()
    def build_window(self):
        self.window = CenterWindow()
        self.window.setWindowTitle('Cicerón · desarrollo' if development_mode() else 'Cicerón')
        self.window.resize(418, 400)
        self.window.setMinimumSize(340, 315)
        outer = QVBoxLayout(self.window)
        outer.setContentsMargins(11, 10, 6, 8)
        outer.setSpacing(10)
        tab_header = QHBoxLayout()
        tab_header.setContentsMargins(0, 0, 12, 0)
        selector = QFrame()
        selector.setObjectName('centerTabs')
        selector.setAccessibleName('Secciones de Cicerón')
        menu = QHBoxLayout(selector)
        menu.setContentsMargins(4, 4, 4, 4)
        menu.setSpacing(3)
        tab_header.addWidget(selector)
        self.nav = QButtonGroup(self.window)
        self.pages = QStackedWidget()
        self.page_ids = {}
        for key, title, build in (
            ('general', 'General', self.build_general),
            ('settings', 'Ajustes', self.build_settings),
            ('status', 'Estado', self.build_status),
        ):
            page, content = scrolled_page(self.pages)
            build(content)
            index = self.pages.addWidget(page)
            self.page_ids[key] = index
            item = button(title, lambda checked=False, page_key=key: self.select_page(page_key))
            item.setObjectName('nav')
            item.setCheckable(True)
            self.nav.addButton(item, index)
            menu.addWidget(item, 1)
        outer.addLayout(tab_header)
        outer.addWidget(self.pages, 1)
        self.nav.button(self.page_ids['general']).setChecked(True)

    def apply_appearance(self, *_):
        from edge_dock import tool_icon

        ui_version = self.cfg['ui_version']
        monochrome = ui_version == 'v1'
        self.window.monochrome = monochrome
        self.window.dark = False if monochrome else dark_mode(self.cfg['theme'])
        pure_versions = ('v3', 'v4')
        self.window.glass = ui_version in pure_versions or (ui_version == 'v2' and bool(self.cfg['glass']))
        for frame, _ in self.builtin_cards:
            key = frame.objectName().removesuffix('Card')
            frame.findChild(AppCardIdentity).set_icon(tool_icon(
                'lens' if key == 'effects' else key,
                light_background=not (self.window.glass or self.window.dark)))
        self.window.transparency = {'clear': 0.20, 'balanced': 0.0, 'contrast': -0.18}.get(
            self.cfg['clarity'], 0.0)
        pure = ui_version in pure_versions and self.window.glass
        QApplication.instance().setProperty('ciceronUIVersion', ui_version)
        QApplication.instance().setProperty('pureGlass', pure)
        if self.dock is not None:
            self.dock.pure = pure
            self.dock.theme_dark = self.window.dark
            self.dock.monochrome = monochrome
            self.dock.set_glass(self.window.glass)
            self.dock.motion_enabled = bool(self.cfg['dock_motion'])
            self.dock.transparency = self.window.transparency
            if self.dock.panel is not None:
                self.dock.panel.apply_glass_tone(self.dock.panel.layer.light if self.window.glass else not self.window.dark)
                self.dock.panel.layer.update()
            self.dock.layer.update()
            self.dock.update()
        if hasattr(self, 'glass_control'):
            blocked = self.glass_control.blockSignals(True)
            self.glass_control.setChecked(self.window.glass)
            self.glass_control.setEnabled(ui_version == 'v2')
            self.glass_control.setToolTip(
                'V1 es opaco y no utiliza Liquid Glass.' if monochrome else
                'V3 mantiene Liquid Glass y difumina sus controles.' if ui_version == 'v3' else
                'V4 aplica Gaussian blur a toda la superficie.' if ui_version == 'v4' else
                'Activa o desactiva Liquid Glass en esta versión.')
            self.glass_control.blockSignals(blocked)
            self.clarity_control.setEnabled(ui_version == 'v2' and self.window.glass)
            self.theme_control.setEnabled(self.cfg['ui_version'] == 'v2')
        self.update_capture_preference()
        self.update_window_style()
        if hasattr(self, 'count'):
            self.update_timer_style()

    def update_timer_style(self):
        self.count.setStyleSheet('''QPushButton {
            background: #1c1c1c; color: white; border: 0;
            border-radius: 0; padding: 0; font: 10pt "Segoe UI";
        }''')

    def update_window_style(self):
        self.banner.glass = not self.window.monochrome
        app = QApplication.instance()
        appearance = stylesheet(self.window.dark, self.window.glass, self.window.monochrome)
        pure_glass = bool(app.property('pureGlass'))
        # Keep the V2 painted banner artwork in every UI version.
        self.banner.live = False
        if pure_glass:
            appearance += clear_styles()
        if self.window.monochrome:
            selected_fill, selected_ink = '#111111', '#ffffff'
        elif self.window.dark:
            selected_fill, selected_ink = '#dddddd', '#212121'
        else:
            selected_fill, selected_ink = '#265ebc', '#ffffff'
        appearance += f"""
            QFrame#centerTabs QPushButton#nav:checked {{
                background: {selected_fill}; color: {selected_ink};
                border: 1px solid {selected_fill}; font-weight: 700;
            }}
        """
        if app.styleSheet() != appearance:
            app.setStyleSheet(appearance)
        self.window.update()
        self.banner.update()
        if self.pages.currentIndex() == self.page_ids['status']:
            self.refresh_status()

    def build_general(self, content):
        from edge_dock import tool_icon
        self.banner = LibraryBanner()
        layout = QVBoxLayout(self.banner)
        layout.setContentsMargins(14, 9, 14, 10)
        layout.setSpacing(2)
        layout.addWidget(caption('Mis aplicaciones', 'heroTitle'))
        self.library_summary = caption('', 'heroDetail')
        self.library_summary.setFixedHeight(self.library_summary.fontMetrics().height())
        layout.addWidget(self.library_summary)
        layout.addStretch()
        self.import_button = button('Importar aplicaciones', self.add_app)
        self.import_button.setObjectName('heroAction')
        actions = QHBoxLayout()
        actions.addWidget(self.import_button)
        actions.addStretch(1)
        self.search_button = QPushButton()
        self.search_button.setObjectName('heroAction')
        self.search_button.setIcon(tool_icon('search'))
        self.search_button.setAccessibleName('Buscar aplicaciones')
        self.search_button.setToolTip('Buscar aplicaciones')
        self.search_button.setCheckable(True)
        actions.addWidget(self.search_button)
        layout.addLayout(actions)
        content.addWidget(self.banner)
        self.build_library(content)
        self.builtin_cards = []
        for key, title, description, tags in (
            ('clock', 'Timer y enfoque', '', ('temporizador', 'cuenta atrás', 'exámenes', 'productividad')),
            ('browser', 'Navegador', 'Pausa Feed', ('bloqueo', 'YouTube', 'Twitter', 'X')),
            ('effects', 'Efectos de escritorio', 'Burbuja y partículas', ('Liquid Glass', 'lente', 'animación')),
        ):
            detail = self.card(content, title, description,
                               [('Abrir', lambda checked=False, tool=key: self.open_tool(tool))],
                               image=tool_icon('lens' if key == 'effects' else key),
                               style=key + 'Card')
            self.builtin_cards.append((detail.parentWidget().parentWidget(),
                                       fold_search(' '.join((title, description, *tags)))))
            if key == 'clock':
                self.goal_detail = detail

    def build_library(self, content):
        self.app_search = QLineEdit()
        self.app_search.setAccessibleName('Buscar aplicaciones')
        self.app_search.setClearButtonEnabled(True)
        content.addWidget(self.app_search)
        self.app_search.hide()
        self.search_button.toggled.connect(self.toggle_app_search)
        self.library_rows = QVBoxLayout()
        self.library_rows.setSpacing(8)
        content.addLayout(self.library_rows)
        self.file_icons = QFileIconProvider()
        self.app_search.textChanged.connect(self.render_library)

    def toggle_app_search(self, opened):
        self.app_search.setVisible(opened)
        if opened:
            self.app_search.setFocus()
            self.pages.currentWidget().ensureWidgetVisible(self.app_search)
        else:
            self.app_search.clear()

    def build_settings(self, content):
        content.addWidget(caption('Apariencia', 'heading'))
        version = PreferenceBox()
        self.version_control = version
        version.setAccessibleName('Versión de la interfaz')
        for key, label in UI_VERSIONS.items():
            version.addItem(label, key)
        version.setCurrentIndex(version.findData(self.cfg['ui_version']))
        version.currentIndexChanged.connect(
            lambda index: self.change_preference('ui_version', version.itemData(index), version))
        self.card(content, 'Interfaz', '', control=version)
        theme = PreferenceBox()
        theme.setAccessibleName('Tema')
        self.theme_control = theme
        for label, value in (('Sistema', 'system'), ('Claro', 'light'), ('Oscuro', 'dark')):
            theme.addItem(label, value)
        theme.setCurrentIndex(max(0, theme.findData(self.cfg['theme'])))
        theme.currentIndexChanged.connect(
            lambda index: self.change_preference('theme', theme.itemData(index), theme))
        self.card(content, 'Tema', '', control=theme)
        glass = ClearCheckBox()
        glass.setFixedSize(22, 22)
        glass.setAccessibleName('Material Liquid Glass')
        glass.setChecked(bool(self.cfg['glass']))
        self.glass_control = glass
        glass.toggled.connect(lambda checked: self.change_preference('glass', checked, glass))
        self.card(content, 'Liquid Glass', '', control=glass)
        clarity = PreferenceBox()
        self.clarity_control = clarity
        clarity.setAccessibleName('Transparencia del vidrio')
        for label, value in (('Alta', 'clear'), ('Media', 'balanced'), ('Baja', 'contrast')):
            clarity.addItem(label, value)
        clarity.setCurrentIndex(max(0, clarity.findData(self.cfg['clarity'])))
        clarity.setEnabled(self.cfg['ui_version'] == 'v2' and glass.isChecked())
        glass.toggled.connect(lambda _: clarity.setEnabled(
            self.cfg['ui_version'] == 'v2' and glass.isChecked()))
        clarity.currentIndexChanged.connect(
            lambda index: self.change_preference('clarity', clarity.itemData(index), clarity))
        self.card(content, 'Transparencia', '', control=clarity)
        content.addSpacing(4)
        content.addWidget(caption('Inicio', 'heading'))
        self.card(content, 'Windows y enfoque', '', [('Opciones', self.options)])
        content.addSpacing(4)
        content.addWidget(caption('Capturas', 'heading'))
        capture = ClearCheckBox()
        capture.setFixedSize(22, 22)
        capture.setAccessibleName('Incluir Cicerón en capturas')
        capture.setChecked(bool(self.cfg['include_in_captures']))
        self.capture_control = capture
        capture.toggled.connect(lambda checked: self.change_preference('include_in_captures', checked, capture))
        self.card(content, 'Incluir Cicerón en capturas',
                  'V1 se incluye siempre. Con Liquid Glass, usa la captura de 20 segundos desde el icono de Cicerón.',
                  control=capture)
        content.addSpacing(4)
        content.addWidget(caption('Datos', 'heading'))
        self.card(content, 'Trasladar datos de aplicaciones', '', [
            ('Exportar', lambda: self.transfer_data(export=True)),
            ('Importar', self.transfer_data),
        ])

    def transfer_data(self, *, export=False):
        parent = self.window.window()
        try:
            if export:
                export_dialog(parent, self.packages,
                              [item['package'] for item in self.managed_apps], self.cfg)
            else:
                import_dialog(parent, self.packages, self.restore_preferences)
        except (OSError, ValueError) as error:
            QMessageBox.warning(parent, 'Datos de Cicerón', str(error))

    def restore_preferences(self, values):
        old = self.cfg.copy()
        self.cfg.update(values)
        if not self.save():
            self.cfg = old
            return False
        for key, control in (
            ('ui_version', self.version_control), ('theme', self.theme_control),
            ('clarity', self.clarity_control), ('glass', self.glass_control),
            ('include_in_captures', self.capture_control),
        ):
            blocked = control.blockSignals(True)
            if isinstance(control, QComboBox):
                control.setCurrentIndex(control.findData(self.cfg[key]))
            else:
                control.setChecked(self.cfg[key])
            control.blockSignals(blocked)
        self.count.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.cfg['topmost'])
        if self.cfg['show_timer'] and target(self.cfg):
            self._show_count()
        else:
            self._hide_count()
        self.last_poll = 0
        self.apply_appearance()
        self.tick()
        self.render()
        return True

    def build_status(self, content):
        content.addWidget(button('Volver a comprobar', self.refresh_status),
                          alignment=Qt.AlignmentFlag.AlignLeft)
        self.status_fields = {}
        for name, title, actions in (
            ('program', 'Instalación de Cicerón', [('Abrir carpeta', self.open_install_folder)] +
             ([('Reparar integración', self.repair_integration)] if not development_mode() else [])),
            ('shortcut', 'Acceso en el menú Inicio', []),
            ('startup', 'Inicio automático', []),
            ('data', 'Configuración y biblioteca', [('Abrir datos', lambda: self.open_location(DATA))]),
            ('glass', 'Material Liquid Glass', []),
            ('browser', 'Integración con el navegador', [('Abrir', lambda: self.open_tool('browser'))]),
        ):
            self.status_fields[name] = self.card(content, title, '', actions)

    @staticmethod
    def card(content, name, description, actions=(), control=None, image=None, style='card'):
        frame = QFrame()
        frame.setObjectName(style)
        if len(actions) > 1:
            outer = QVBoxLayout(frame)
            outer.setContentsMargins(11, 7, 9, 7)
            outer.setSpacing(6)
            box = QHBoxLayout()
            outer.addLayout(box)
        else:
            box = QHBoxLayout(frame)
            box.setContentsMargins(11, 4, 9, 4)
        box.setSpacing(12)
        title = caption(name, 'heading')
        detail = caption(description, 'muted')
        if image is not None:
            box.addWidget(AppCardIdentity(image, title, detail), 1)
        else:
            text = QVBoxLayout()
            text.setSpacing(3)
            text.addWidget(title)
            text.addWidget(detail)
            box.addLayout(text, 1)
        if not description:
            detail.hide()
        actions_row = box
        if len(actions) > 1:
            actions_row = QHBoxLayout()
            actions_row.addStretch()
            outer.addLayout(actions_row)
        for label, callback in actions:
            actions_row.addWidget(button(label, callback))
        if control is not None:
            box.addWidget(control)
        content.addWidget(frame)
        return detail

    def change_preference(self, key, value, control):
        previous = self.cfg[key]
        self.cfg[key] = value
        if not self.save():
            self.cfg[key] = previous
            blocked = control.blockSignals(True)
            if isinstance(control, QComboBox):
                control.setCurrentIndex(max(0, control.findData(previous)))
            else:
                control.setChecked(bool(previous))
            control.blockSignals(blocked)
            return
        if key == 'include_in_captures':
            self.update_capture_preference()
            return
        if key == 'ui_version' and value != previous:
            # Let the activated control finish handling the click before its
            # window is detached from the dock or hidden.
            QTimer.singleShot(0, self.window, self.switch_ui)
            return
        self.apply_appearance()

    def switch_ui(self):
        dock = self.dock
        reopen_settings = (dock is not None and dock.panel is not None and
                           dock.panel.key == 'settings' and dock.panel.content is self.window)
        if reopen_settings:
            dock.panel.close()
            self.window.hide()
        self.apply_appearance()
        self.show_edge_dock()
        if reopen_settings:
            dock.toggle_panel('settings', lambda: self.window, persistent=True)

    def select_page(self, key):
        index = self.page_ids[key]
        self.nav.button(index).setChecked(True)
        self.pages.setCurrentIndex(index)
        if key == 'general':
            self.render_library()
        elif key == 'status':
            self.refresh_status()

    def open_page(self, key):
        self.wheel_filter.remember_foreground()
        self.select_page(key)
        self.show_edge_dock()
        screen = self.dock.current_screen()
        if screen is not None:
            if self.dock.pending_panel is not None and self.dock.pending_panel[0] == 'settings':
                return
            if self.dock.panel is None or self.dock.panel.key != 'settings':
                self.dock.toggle_panel('settings', lambda: self.window, persistent=True)
            else:
                self.dock.panel.raise_()
                self.dock.panel.activateWindow()
            return
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def open_center(self):
        self.show()
        self.open_page('general')

    def toggle_center(self):
        dock = self.dock
        if dock is not None:
            pending = dock.pending_panel
            if pending is not None and pending[0] == 'settings':
                dock.reset_to_handle()
                return
            if dock.panel is not None and dock.panel.key == 'settings':
                dock.panel.close()
                dock.reset_to_handle()
                return
        if self.window.isVisible():
            self.window.hide()
            if dock is not None:
                dock.reset_to_handle()
            return
        self.open_center()

    def prepare_for_power_transition(self):
        dock = self.dock
        if dock is not None:
            pending = dock.pending_panel
            if pending is not None and pending[0] == 'settings':
                dock.cancel_pending_panel()
            if dock.panel is not None and dock.panel.key == 'settings':
                dock.panel.close()
            if dock.panel is None:
                dock.reset_to_handle()
        self.window.hide()

    def update_tray_actions(self):
        dock_visible = self.dock is not None and self.dock.isVisible()
        self.dock_visibility_action.setEnabled(True)
        self.dock_visibility_action.setText(
            'Ocultar barra lateral' if dock_visible else 'Mostrar barra lateral')
        self.photo_action.setEnabled(self.window.glass)

    def toggle_edge_dock_visibility(self):
        if self.dock is not None and self.dock.isVisible():
            self.dock.hide()
        else:
            self.show_edge_dock()
            self.dock.reveal()

    def restart_edge_dock(self):
        """Recreate only the sidebar and its native interaction state."""
        dock = self.dock
        if dock is None:
            return
        dock.shutdown()
        dock.deleteLater()
        self.dock = None
        self.dock_signature = None
        self.create_edge_dock()

    def create_edge_dock(self):
        from edge_dock import EdgeDock
        self.dock = EdgeDock(icon(), self.toggle_settings_panel, tray_geometry=self.tray.geometry)
        QApplication.instance().aboutToQuit.connect(self.dock.shutdown)

    def show(self):
        self.show_edge_dock()
        self.dock.reveal()

    def show_edge_dock(self):
        if self.dock is None:
            self.create_edge_dock()
        elif not self.dock.isVisible():
            self.restart_edge_dock()
        self.dock.pure = bool(QApplication.instance().property('pureGlass'))
        self.dock.theme_dark = self.window.dark
        self.dock.monochrome = self.window.monochrome
        self.refresh_dock()
        self.dock.set_glass(self.window.glass)
        self.dock.motion_enabled = bool(self.cfg['dock_motion'])
        self.dock.transparency = self.window.transparency
        self.dock.show()
        self.dock.raise_()

    def toggle_settings_panel(self):
        self.wheel_filter.remember_foreground()
        def settings():
            self.select_page('general')
            return self.window
        self.dock.toggle_panel('settings', settings, persistent=True)

    def refresh_dock(self):
        if self.dock is None:
            return
        dock_apps = [item for item in self.library_apps()
                     if not item.get('package') or item['package']['dock']['visible']]
        signature = tuple((entry['name'], entry['path']) for entry in dock_apps)
        if signature == self.dock_signature:
            return
        entries = [
            ('Timer', 'clock', lambda: self.open_tool('clock')),
            ('Navegador', 'browser', lambda: self.open_tool('browser')),
            ('Efectos de escritorio', 'lens', lambda: self.open_tool('effects')),
        ]
        for entry in dock_apps:
            wheel = entry['package']['dock']['wheel'] if entry.get('package') else 'passthrough'
            icon = ('gift' if entry.get('package', {}).get('id') == 'emilioreato.happy-birthday'
                    else self.app_icon(entry))
            entries.append((entry['name'], icon,
                            lambda checked=False, item=entry: self.launch(item), wheel))
        self.dock.set_entries(entries)
        self.dock_signature = signature

    def open_tool(self, key, *, from_start=False):
        self.wheel_filter.remember_foreground()
        factories = {
            'clock': lambda: self.goal_dialog(attached=True),
            'browser': lambda: BrowserDialog(self.window, attached=True),
            'effects': lambda: VisualDialog(self.window, attached=True, dock_provider=lambda: self.dock),
        }
        factory = factories.get(key)
        if factory is None:
            return
        self.show_edge_dock()
        if from_start and self.dock.panel is not None and self.dock.panel.key == key:
            self.dock.panel.raise_()
            self.dock.panel.activateWindow()
            return
        if from_start and self.dock.pending_panel is not None and self.dock.pending_panel[0] == key:
            return
        self.dock.toggle_panel(key, factory)
        if from_start and self.dock.panel is not None:
            self.dock.panel.activateWindow()

    def render(self):
        t = target(self.cfg)
        if t:
            state = 'Detenida' if not self.cfg['show_timer'] else (
                'Fecha alcanzada' if t <= dt.datetime.now() else 'En marcha')
            self.goal_detail.setText(f"{self.cfg['title']} · {state} · {t:%d-%m-%Y %H:%M}")
        else:
            self.goal_detail.setText('Sin objetivo')
        self.goal_detail.show()
        if self.bad_apps or self.package_error:
            self.library_summary.setText('Biblioteca pendiente de revisión')
        else:
            self.library_summary.clear()
        self.refresh_dock()
        if self.pages.currentIndex() == self.page_ids['general']:
            self.render_library()
        elif self.pages.currentIndex() == self.page_ids['status']:
            self.refresh_status()

    def render_library(self, *_):
        snapshot = (self.app_search.text(), self.apps, self.managed_apps,
                    self.package_tags, self.bad_apps, self.package_error)
        if snapshot == self.library_snapshot:
            return
        self.library_snapshot = snapshot
        while self.library_rows.count():
            widget = self.library_rows.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        if self.bad_apps:
            self.library_rows.addWidget(caption('La lista de archivos vinculados requiere revisión en Estado.', 'muted'))
        if self.package_error:
            self.library_rows.addWidget(caption(f'Paquetes no disponibles. {self.package_error}', 'muted'))
        query = fold_search(self.app_search.text()).split()
        def matches_query(text):
            return all(word in text for word in query)

        builtin_matches = False
        for card, search_text in self.builtin_cards:
            visible = matches_query(search_text)
            card.setVisible(visible)
            builtin_matches |= visible
        matches = []
        for item in self.library_apps():
            tags = self.tags_for(item)
            description = (item.get('package') or {}).get('description', '')
            if matches_query(fold_search(' '.join((item['name'], item['path'], description, *tags)))):
                matches.append((item, tags))
        if not matches and (not query or not builtin_matches):
            message = 'No hay aplicaciones que coincidan con la búsqueda.' if query else (
                'Importa un .ciceron, un EXE o un acceso directo.')
            hint = caption(message, 'muted')
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setContentsMargins(6, 3, 6, 3)
            hint.setWordWrap(bool(query))
            self.library_rows.addWidget(hint)
        for item, tags in matches:
            path = Path(item['path'])
            exists = path.is_file()
            more = QPushButton('···')
            more.setObjectName('more')
            more.setAccessibleName(f"Opciones de {item['name']}")
            menu = QMenu(more)
            spec = item.get('package')
            if spec:
                if spec['settings']:
                    menu.addAction('Configurar', lambda checked=False, i=item: edit_settings(self.window, self.packages, i))
                menu.addAction('Abrir datos', lambda checked=False, s=spec: self.open_package_data(s))
            else:
                menu.addAction('Cambiar nombre', lambda checked=False, i=item: self.rename_app(i))
                menu.addAction('Cambiar archivo vinculado', lambda checked=False, i=item: self.relink_app(i))
            menu.addAction('Editar etiquetas', lambda checked=False, i=item: self.edit_app_tags(i))
            start = menu.addMenu('Inicio de Windows')
            start.setEnabled(not development_mode())
            add_shortcut = start.addAction('Añadir acceso', lambda checked=False, i=item: self.add_start_shortcut(i))
            add_shortcut.setEnabled(exists)
            if not spec:
                start.addAction('Quitar acceso', lambda checked=False, i=item: self.remove_start_shortcut(i))
            folder = menu.addAction('Abrir carpeta', lambda checked=False, p=path.parent: self.open_location(p))
            folder.setEnabled(path.parent.is_dir())
            menu.addSeparator()
            menu.addAction('Desinstalar paquete' if spec else 'Quitar de Cicerón',
                           lambda checked=False, i=item: self.remove(i))
            more.setMenu(menu)
            description = (spec['description'] or f"Versión {spec['version']}") if spec else 'Acceso vinculado'
            if not exists:
                description = 'Archivo no encontrado'
            detail = self.card(self.library_rows, item['name'], description,
                               [('Abrir', lambda checked=False, i=item: self.launch(i))] if exists else (),
                               control=more, image=self.app_icon(item), style='appCard')
            tooltip = self.app_description(item)
            if tags:
                tooltip += '\nEtiquetas: ' + ', '.join(tags)
            detail.parentWidget().parentWidget().setToolTip(tooltip)

    def tags_for(self, item):
        return list(AppIdentity.from_entry(item, self.package_tags).tags)

    def edit_app_tags(self, item):
        value, accepted = QInputDialog.getText(self.window, 'Editar etiquetas', 'Separá las etiquetas con comas',
                                               text=', '.join(self.tags_for(item)))
        if not accepted:
            return
        try:
            tags = app_tags([tag.strip() for tag in value.split(',') if tag.strip()])
            package = item.get('package')
            if not package:
                self.replace_linked_app(item, tags=tags)
                return
            if self.bad_package_tags:
                raise ValueError('No se pudo leer el archivo de etiquetas de paquetes.')
            updated = {**self.package_tags, package['id']: tags}
            write(PACKAGE_TAGS, updated)
            self.package_tags = updated
            self.render()
            self.add_start_shortcut(item, previous=item)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self.window, 'No se pudieron guardar las etiquetas', str(error))

    def reload_packages(self):
        previous = {item['package']['id']: item for item in self.managed_apps}
        try:
            self.managed_apps = self.packages.entries()
            self.package_error = None
        except (OSError, ValueError) as error:
            self.managed_apps = []
            self.package_error = str(error)
        for item in self.managed_apps:
            old = previous.get(item['package']['id'])
            if old != item and self.start_menu.ciceron.is_file():
                self.add_start_shortcut(item, report_error=False)
        if hasattr(self, 'tray'):
            self.prepare_birthday()

    def add_start_shortcut(self, item, previous=None, *, report_error=True):
        try:
            self.start_menu.update(item, self.tags_for(item), previous)
        except (OSError, ValueError, COMError) as error:
            if report_error:
                QMessageBox.warning(self.window, 'Inicio de Windows', str(error))

    def remove_start_shortcut(self, item):
        try:
            self.start_menu.remove(item)
        except (OSError, ValueError, COMError) as error:
            QMessageBox.warning(self.window, 'Inicio de Windows', str(error))

    def library_apps(self):
        return self.apps + self.managed_apps

    def app_icon(self, item):
        path = AppIdentity.from_entry(item).icon
        if path:
            bundled = QIcon(str(path))
            if not bundled.isNull():
                return bundled
        reference = file_icon_reference(Path(item['path']))
        if reference:
            path, index = reference
            try:
                embedded = resource_icon(path, index, path.stat().st_mtime_ns)
            except OSError:
                pass
            else:
                if not embedded.isNull():
                    return embedded
        return self.file_icons.icon(QFileIconProvider.IconType.File)

    @staticmethod
    def app_description(item):
        if not Path(item['path']).is_file():
            return 'Falta el ejecutable. Vuelve a importar el paquete.' if item.get('package') else f"Archivo no encontrado · {item['path']}"
        spec = item.get('package')
        if spec:
            return f"Versión {spec['version']}" + (f" · {spec['description']}" if spec['description'] else '')
        return item['path']

    def open_package_data(self, spec):
        path = self.packages.data_folder(spec)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.warning(self.window, 'Carpeta de datos', str(error))
            return
        self.open_location(path)

    def open_location(self, location):
        try:
            os.startfile(str(location))
        except OSError as error:
            QMessageBox.warning(self.window, 'No se pudo abrir', str(error))

    @staticmethod
    def install_dir():
        return application_root()

    def open_install_folder(self):
        folder = self.install_dir()
        self.open_location(folder if folder.is_dir() else Path(sys.executable).parent)

    def repair_integration(self):
        command = self.install_dir() / 'Reparar integracion.bat'
        if command.is_file():
            self.open_location(command)
        else:
            QMessageBox.information(self.window, 'Reparar integración',
                                    'Abre Instalar.bat con la opción -Reparar desde la carpeta del proyecto.')

    def refresh_status(self):
        from browser_bridge import sessions
        install = self.install_dir() / 'Ciceron.exe'
        running_installed = (source_installation_root() is not None or
                             (getattr(sys, 'frozen', False) and Path(sys.executable) == install))
        installed = install.is_file()
        state = 'Instalado y en ejecución' if installed and running_installed else (
            'Instalado · esta ventana se ejecuta desde otra copia' if installed else
            'Instalación de usuario no encontrada')
        fields = self.status_fields
        for detail in fields.values():
            detail.show()
        if development_mode():
            state = 'Perfil de desarrollo'
        linked_source = os.environ.get('CICERON_LIVE_SOURCE')
        source_path = Path(__file__).resolve().parent
        if running_installed and linked_source:
            state = ('Instalado · código del repositorio' if source_path == Path(linked_source).resolve()
                     else 'Instalado · respaldo en uso')
        fields['program'].setText(state)
        fields['program'].setToolTip(str(source_path if linked_source else install))
        shortcuts = Path(os.environ.get('APPDATA', str(Path.home()))) / 'Microsoft/Windows/Start Menu/Programs'
        shortcut = shortcuts / 'Cicerón.lnk'
        legacy_shortcut = shortcuts / 'Mi centro.lnk'
        fields['shortcut'].setText('Acceso encontrado' if shortcut.is_file() or legacy_shortcut.is_file() else 'Acceso no encontrado')
        if development_mode():
            fields['shortcut'].setText('Deshabilitado en desarrollo')
            startup = 'Deshabilitado en desarrollo'
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as registry:
                    raw, _ = winreg.QueryValueEx(registry, RUN_VALUE)
                target_path = startup_target(raw)
                owns_startup = bool(target_path and
                                    os.path.normcase(os.path.abspath(target_path)) ==
                                    os.path.normcase(os.path.abspath(install)))
                startup = 'Activado' if owns_startup and installed else 'La entrada apunta a otra ruta'
            except FileNotFoundError:
                startup = 'Desactivado'
            except OSError:
                startup = 'No se pudo consultar'
        fields['startup'].setText(startup)
        config_state = 'Requiere revisión' if self.broken_config or self.bad_apps else (
            'Datos disponibles' if CONFIG.is_file() or APPS.is_file() else 'Se crearán al guardar cambios')
        fields['data'].setText(config_state)
        fields['data'].setToolTip(str(DATA))
        if self.dock is not None and self.dock.isVisible():
            glass_state = ('Dock · refracción en directo' if self.dock.using_glass else
                           'Dock · vidrio básico' if self.dock.glass_enabled else 'Desactivado en Ajustes')
        else:
            glass_state = 'Disponible en el dock V2' if self.window.glass else 'Desactivado en Ajustes'
        fields['glass'].setText(glass_state)
        connected = sessions()
        if connected:
            state = 'Con error de conexión' if any(item.get('error') for item in connected) else 'En comunicación'
        else:
            state = 'Puente presente · sin navegador conectado' if (
                self.install_dir() / 'ciceron-native-host.json').is_file() else 'Integración pendiente de preparar'
        fields['browser'].setText(state)
    def stop_visual_effects(self):
        from desktop_bubble import stop_desktop_effects
        stop_desktop_effects()

    def update_capture_preference(self):
        allowed = bool(self.cfg['include_in_captures'])
        self.capture_control.setEnabled(not self.window.monochrome)
        if capture_mode() and not self.window.glass:
            self.set_capture_mode(False)
        photo_override = (hasattr(self, 'photo_timer') and self.photo_timer.isActive() and
                          capture_mode() and self.window.glass)
        self.capture_privacy.set_private(
            not self.window.monochrome and not allowed and not photo_override)

    def start_photo_mode(self):
        if self.window.glass:
            self.set_capture_mode(True)
            self.photo_timer.start(20000)
            self.update_capture_preference()

    def finish_photo_mode(self):
        self.set_capture_mode(False)
        self.update_capture_preference()

    def set_capture_mode(self, mode):
        self.photo_timer.stop()
        if capture_mode() == mode:
            return
        app = QApplication.instance()
        app.setProperty('captureMode', mode)
        bubble = getattr(app, '_ciceron_overlay', None)
        if mode and bubble is not None:
            bubble.update_capture_mode()
        if self.dock is not None:
            self.dock.update_capture_mode()
        for widget in app.topLevelWidgets():
            material = getattr(widget, 'material', None)
            if material is not None and widget.isVisible() and widget.isWindow():
                if mode:
                    material.stop()
                elif self.window.glass and widget.glass:
                    material.start()
        if not mode and bubble is not None:
            bubble.update_capture_mode()

    def visual_playground(self):
        dialog = VisualDialog(self.window, dock_provider=lambda: self.dock)
        screen = (self.dock.current_screen() if self.dock is not None and self.dock.isVisible()
                  else None)
        if screen is not None:
            area = screen.availableGeometry()
            dialog.move(max(area.x(), area.right() - self.dock.WIDTH - dialog.width() - 12),
                        area.center().y() - dialog.height() // 2)
        dialog.exec()
    def browser_settings(self):
        dialog=BrowserDialog(self.window)
        dialog.exec()
    def prepare_birthday(self):
        from birthday_host import APP_ID, BirthdayHost, remove_legacy_startup

        item = next((entry for entry in self.managed_apps if entry['package']['id'] == APP_ID), None)
        if item is None:
            if self.birthday_host is not None:
                self.birthday_host.close()
                self.birthday_host = None
            return None
        if self.birthday_host is None:
            self.birthday_host = BirthdayHost(self, item)
        else:
            self.birthday_host.update_entry(item)
        first_load = self.birthday_host.agenda is None
        try:
            agenda = self.birthday_host.prepare()
            if first_load and agenda is not None and source_installation_root() is not None:
                try:
                    remove_legacy_startup(self.packages.data_folder(item['package']))
                except OSError:
                    pass
            return agenda
        except (OSError, ValueError):
            return None

    def launch(self,item):
        try:
            if item.get('package'):
                from birthday_host import APP_ID, agenda_module
                if item['package']['id'] == APP_ID and agenda_module() is not None:
                    agenda = self.prepare_birthday()
                    if agenda is None:
                        raise ValueError('Cierra la agenda anterior o revisa su archivo de datos antes de abrir Happy Birthday.')
                    self.show_edge_dock()
                    pending = self.dock.pending_panel
                    if pending is not None and pending[0] == APP_ID:
                        return
                    self.dock.toggle_panel(APP_ID, lambda: agenda, persistent=True)
                    return
                self.packages.launch(item)
            else:
                if not Path(item['path']).is_file(): raise FileNotFoundError('No se encuentra el archivo; puede que se haya movido.')
                os.startfile(item['path'])
        except (OSError, ValueError) as e: QMessageBox.warning(self.window,'No se pudo abrir',str(e))

    def launch_requested_apps(self):
        packages_refreshed = False
        for kind, app_id in pending_launches(LAUNCH_REQUESTS):
            if kind == 'control':
                if source_installation_root() is not None:
                    QApplication.quit()
                    return
                continue
            if kind == 'tool':
                self.open_tool(app_id, from_start=True)
                continue
            if not packages_refreshed:
                previous = self.managed_apps
                self.reload_packages()
                if previous != self.managed_apps:
                    self.render()
                packages_refreshed = True
            item = next((item for item in self.managed_apps if item['package']['id'] == app_id), None)
            if item is not None:
                self.launch(item)

    def add_app(self):
        selected, _ = QFileDialog.getOpenFileNames(
            self.window, 'Importar aplicaciones', '', 'Aplicaciones (*.ciceron *.exe *.lnk *.bat *.cmd *.pyw);;Paquetes (*.ciceron);;Todos los archivos (*)')
        if not selected:
            return
        known = {Path(item['path']) for item in self.apps}
        added = []
        results = []
        packages = []
        for path in dict.fromkeys(map(Path, selected)):
            if path.suffix.lower() == PACKAGE_EXT:
                packages.append(path)
                continue
            if self.bad_apps:
                results.append(f'{path.name} · Revisa la lista de archivos vinculados en Estado.')
                continue
            if path in known or not path.is_file():
                continue
            name = path.stem
            if len(selected) == 1:
                name, ok = QInputDialog.getText(self.window, 'Importar aplicación', 'Nombre', text=name)
                if not ok or not name.strip():
                    return
            added.append(dict(name=name.strip(), path=str(path)))
        if packages:
            results.extend(install_packages(self.window, self.packages, packages))
        if added:
            self.save_library(self.apps + added)
        if results:
            self.reload_packages()
            self.render()
            QMessageBox.information(self.window, 'Importar aplicaciones', '\n'.join(results))
        elif not added:
            QMessageBox.information(self.window, 'Importar aplicaciones', 'La selección no contiene archivos nuevos disponibles.')

    def save_library(self, entries):
        try:
            saved = [dict(item, path=stored_app_path(item['path'])) for item in entries]
            write(APPS, saved)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self.window, 'No se pudo guardar', str(error))
            return False
        self.apps = entries
        self.render()
        return True

    def replace_linked_app(self, item, **changes):
        updated = dict(item, **changes)
        if self.save_library([updated if entry is item else entry for entry in self.apps]):
            self.add_start_shortcut(updated, previous=item)

    def rename_app(self, item):
        name, ok = QInputDialog.getText(self.window, 'Cambiar nombre', 'Nombre', text=item['name'])
        if ok and name.strip() and name.strip() != item['name']:
            self.replace_linked_app(item, name=name.strip())

    def relink_app(self, item):
        filename, _ = QFileDialog.getOpenFileName(
            self.window, 'Cambiar archivo vinculado', str(Path(item['path']).parent))
        if not filename:
            return
        path = Path(filename)
        if path == Path(item['path']):
            return
        if any(Path(entry['path']) == path for entry in self.apps):
            QMessageBox.information(self.window, 'Cambiar archivo vinculado', 'Ese archivo ya está en la biblioteca.')
            return
        if not path.is_file():
            QMessageBox.warning(self.window, 'Cambiar archivo vinculado', 'El archivo seleccionado ya no está disponible.')
            return
        self.replace_linked_app(item, path=str(path))

    def remove(self,item):
        spec = item.get('package')
        if spec:
            answer = QMessageBox.question(self.window, 'Desinstalar paquete',
                                          f"¿Desinstalar «{item['name']}»? Se conservarán sus datos.")
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    cleaned = self.packages.remove(spec['id'])
                except (OSError, ValueError) as error:
                    QMessageBox.warning(self.window, 'No se pudo desinstalar', str(error))
                    return
                self.remove_start_shortcut(item)
                self.reload_packages()
                self.render()
                if not cleaned:
                    QMessageBox.information(self.window, 'Paquete desinstalado',
                                            'Cierra la aplicación. Cicerón volverá a intentar retirar los archivos al iniciar.')
            return
        question = f"¿Quitar «{item['name']}» de la biblioteca? Se conservará el archivo vinculado."
        answer = QMessageBox.question(self.window, 'Quitar de Cicerón', question,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and self.save_library([entry for entry in self.apps if entry is not item]):
            self.remove_start_shortcut(item)

    def goal_dialog(self, attached=False):
        d=TimerDialog(self.window, attached=attached); d.setWindowTitle('Timer')
        d.setProperty('frostControls', True)
        d.setProperty('expandDown', True)
        box=QVBoxLayout(d); box.setContentsMargins(12,9,12,11); box.setSpacing(8)
        box.addWidget(caption('Timer', 'title'))
        name=QLineEdit(str(self.cfg['title'])); name.setAccessibleName('Nombre del objetivo'); box.addWidget(name)
        guard = ClearCheckBox('Avisos de distracción')
        guard.setChecked(bool(self.cfg['guardian']))
        box.addWidget(guard)
        t=target(self.cfg); date=QDateEdit(); date.setAccessibleName('Fecha'); date.setDisplayFormat('dd-MM-yyyy'); date.setDate(QDate(t.year,t.month,t.day) if t else QDate.currentDate())
        date.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        date.setFixedHeight(36)
        editor_style = 'background: transparent; border: 0; padding: 0;'
        date.lineEdit().setStyleSheet(editor_style)
        date_field = QFrame()
        date_row = QHBoxLayout(date_field)
        date_row.setContentsMargins(0, 0, 0, 0)
        date_row.setSpacing(8)
        date_row.addWidget(date, 1)
        calendar_popup = None

        def build_calendar():
            picker = QDialog(d, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            picker.setWindowTitle('Elegir fecha')
            picker_layout = QVBoxLayout(picker)
            picker_layout.setContentsMargins(7, 6, 7, 6)
            picker_layout.setSpacing(4)
            calendar = QCalendarWidget(picker)
            calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
            for control_name, arrow in (('qt_calendar_prevmonth', '‹'), ('qt_calendar_nextmonth', '›')):
                control = calendar.findChild(QToolButton, control_name)
                if control is not None:
                    control.setIcon(QIcon())
                    control.setText(arrow)
                    control.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            picker_layout.addWidget(calendar)
            picker_layout.addWidget(button('Cerrar', picker.reject), alignment=Qt.AlignmentFlag.AlignRight)

            def selected(value):
                date.setDate(value)
                picker.accept()

            calendar.clicked.connect(selected)
            calendar.activated.connect(selected)
            return picker, calendar

        def choose_date():
            nonlocal calendar_popup
            if calendar_popup is None:
                calendar_popup = build_calendar()
            picker, calendar = calendar_popup
            if picker.isVisible():
                picker.reject()
                return
            owner = d.window()
            picker.setStyleSheet(stylesheet(getattr(owner, 'dark', d.dark), False,
                                            monochrome=self.window.monochrome))
            calendar.setSelectedDate(date.date())
            picker.adjustSize()
            point = date_field.mapToGlobal(QPoint(0, date_field.height() + 4))
            area = date_field.screen().availableGeometry()
            if point.y() + picker.height() > area.bottom():
                point.setY(date_field.mapToGlobal(QPoint()).y() - picker.height() - 4)
            point.setY(max(area.top(), point.y()))
            point.setX(max(area.left(), min(point.x(), area.right() + 1 - picker.width())))
            picker.move(point)
            picker.show()

        calendar_button = button('Calendario', choose_date)
        calendar_button.setObjectName('calendarButton')
        calendar_button.setAutoDefault(False)
        calendar_button.setFixedHeight(36)
        date_row.addWidget(calendar_button)
        box.addWidget(date_field)
        time_row=QHBoxLayout(); use_time=ClearCheckBox('Elegir una hora'); use_time.setChecked(bool(t and (t.hour,t.minute)!=(0,0)))
        clock=QTimeEdit(); clock.setDisplayFormat('HH:mm'); clock.setTime(QTime(t.hour,t.minute) if t else QTime(0,0)); clock.setEnabled(use_time.isChecked()); clock.setMaximumWidth(108)
        clock.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        clock.lineEdit().setStyleSheet(editor_style)
        clock.setAccessibleName('Hora')
        use_time.setToolTip('Si dejas la hora desactivada, la fecha vence a las 00:00.')
        chosen_time=[QTime(clock.time())]
        def change_time(enabled):
            if enabled: clock.setTime(chosen_time[0])
            else: chosen_time[0]=QTime(clock.time()); clock.setTime(QTime(0,0))
            clock.setEnabled(enabled)
        use_time.toggled.connect(change_time); time_row.addWidget(use_time); time_row.addStretch(); time_row.addWidget(clock)
        box.addLayout(time_row)
        box.addStretch()
        row=QHBoxLayout(); stop=button('Detener',lambda: d.done(2)); stop.setObjectName('destructive'); stop.setEnabled(bool(self.cfg['show_timer'] and t)); row.addWidget(stop)
        row.addStretch()
        if not attached:
            row.addWidget(button('Cancelar', d.reject))
        row.addWidget(button('Guardar y empezar',d.accept,True)); box.addLayout(row)

        options_panel = None
        collapsed_height = None

        def resize_options():
            box.invalidate()
            box.activate()
            if attached:
                d.preferred_size_changed.emit()
            else:
                height = d.sizeHint().height() if options_panel is not None else collapsed_height
                d.resize(d.width(), height)

        def close_options():
            nonlocal options_panel
            options_panel.hide()
            box.removeWidget(options_panel)
            options_panel.deleteLater()
            options_panel = None
            more.setText('Opciones')
            more.setFocus()
            resize_options()

        def toggle_options():
            nonlocal options_panel, collapsed_height
            if options_panel is not None:
                close_options()
                return
            section = QWidget(d)
            section.setObjectName('timerOptions')
            fields = QVBoxLayout(section)
            fields.setContentsMargins(0, 4, 0, 0)
            fields.setSpacing(8)
            apply = self.build_options_fields(d, fields)
            if apply is None:
                section.deleteLater()
                return

            def save_options():
                if apply():
                    close_options()

            actions = QHBoxLayout()
            actions.addStretch()
            actions.addWidget(button('Cancelar', close_options))
            actions.addWidget(button('Guardar opciones', save_options, True))
            fields.addLayout(actions)
            collapsed_height = d.height()
            options_panel = section
            box.addWidget(section)
            section.show()
            more.setText('Ocultar opciones')
            resize_options()

        more = button('Opciones', toggle_options)
        more.setObjectName('quiet')
        more.setAutoDefault(False)
        box.addWidget(more, alignment=Qt.AlignmentFlag.AlignLeft)
        d.resize(350, d.sizeHint().height())

        def apply_goal(result):
            if result==2:
                old=self.cfg['show_timer']; self.cfg['show_timer']=False
                if not self.save(): self.cfg['show_timer']=old; return
                self._hide_count(); self.tick(); self.render(); return
            if result!=QDialog.DialogCode.Accepted: return
            day=date.date(); tm=clock.time() if use_time.isChecked() else QTime(0,0)
            old=self.cfg.copy(); self.cfg.update(title=name.text().strip() or 'Mi objetivo', target=dt.datetime(day.year(),day.month(),day.day(),tm.hour(),tm.minute()).isoformat(timespec='minutes'), show_timer=True,guardian=guard.isChecked())
            if not self.save(): self.cfg=old; return
            if old['target']!=self.cfg['target'] or (not old['guardian'] and self.cfg['guardian']): self.last_alert=float('-inf')
            self.last_poll=0
            self.tick(); shown=self._show_count(); self.render()
            if not shown:
                QMessageBox.information(self.window,'Timer activado',
                    'La cuenta está en marcha, pero Windows no reserva espacio para mostrar el contador en una barra horizontal. '
                    'El contador queda oculto para no tapar otras ventanas. Desactiva la ocultación automática de la barra o usa una barra horizontal para verlo.')

        d.finished.connect(apply_goal)
        return d

    def options(self):
        d=GlassDialog(self.window); d.setWindowTitle('Inicio de Windows y enfoque'); d.resize(480,290); box=QVBoxLayout(d); box.setContentsMargins(24,24,24,24)
        box.addWidget(caption('Windows y enfoque','title'))
        apply = self.build_options_fields(d, box)
        if apply is None:
            d.deleteLater()
            return
        box.addStretch(); row=QHBoxLayout(); row.addStretch(); row.addWidget(button('Cancelar',d.reject)); row.addWidget(button('Guardar',d.accept,True)); box.addLayout(row)
        d.accepted.connect(apply)
        if self.dock is not None and self.dock.panel is not None and self.dock.panel.key == 'settings':
            self.dock.panel.open_subpanel(d)
        else:
            d.exec()
            d.deleteLater()

    def build_options_fields(self, parent, box):
        box.addWidget(caption('Palabras de aviso','muted'))
        words=QLineEdit(str(self.cfg['words'])); box.addWidget(words)
        words.setAccessibleName('Palabras de aviso')
        words.setToolTip('Palabras separadas por comas que Cicerón busca en el título de la ventana activa.')
        top=QCheckBox('Mantener el contador sobre otras ventanas'); top.setChecked(bool(self.cfg['topmost'])); box.addWidget(top)
        startup=QCheckBox('Iniciar Cicerón minimizado con Windows')
        old_startup=None; old_startup_type=None; startup_exists=False
        if not development_mode():
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as k:
                    old_startup,old_startup_type=winreg.QueryValueEx(k,RUN_VALUE); startup_exists=True
            except FileNotFoundError: pass
            except OSError as e:
                QMessageBox.warning(parent,'Inicio automático',f'No se pudo consultar el Registro: {e}'); return None
        install_dir=application_root()
        owned_paths={os.path.normcase(str(install_dir / 'Ciceron.exe'))}
        old_target = startup_target(old_startup)
        own_entry=bool(old_target and os.path.normcase(os.path.abspath(old_target)) in owned_paths)
        launcher = install_dir / 'Ciceron.exe'
        installed_executable = (source_installation_root() is not None and launcher.is_file()) or (
            getattr(sys, 'frozen', False) and os.path.normcase(os.path.abspath(sys.executable)) in owned_paths)
        can_manage = installed_executable and (not startup_exists or own_entry)
        startup.setChecked(bool(startup_exists and own_entry)); startup.setEnabled(can_manage)
        if not can_manage:
            message=('La entrada de inicio pertenece a otro programa y no se modificará.' if startup_exists and not own_entry
                     else 'El inicio automático se configura desde la versión instalada.')
            startup.setToolTip(message); box.addWidget(caption(message,'muted'))
        box.addWidget(startup)
        def apply_options():
            desired_startup = startup_command(sys.executable if getattr(sys, 'frozen', False) else launcher)
            changed_startup = can_manage and (
                startup.isChecked() != own_entry or
                (startup.isChecked() and old_startup != desired_startup))
            if changed_startup:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
                        try: current=winreg.QueryValueEx(k,RUN_VALUE)
                        except FileNotFoundError: current=None
                        expected=(old_startup,old_startup_type) if startup_exists else None
                        if current != expected:
                            raise OSError('La entrada de inicio cambió mientras estaba abierta la ventana. Vuelve a abrir los ajustes.')
                        if startup.isChecked(): winreg.SetValueEx(k,RUN_VALUE,0,winreg.REG_SZ,desired_startup)
                        else: winreg.DeleteValue(k,RUN_VALUE)
                except OSError as e: QMessageBox.warning(parent,'Inicio automático',str(e)); return False
            old=self.cfg.copy(); self.cfg.update(words=words.text(),topmost=top.isChecked())
            if not self.save():
                self.cfg=old
                if changed_startup:
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
                            try: current=winreg.QueryValueEx(k,RUN_VALUE)
                            except FileNotFoundError: current=None
                            expected=(desired_startup,winreg.REG_SZ) if startup.isChecked() else None
                            if current != expected:
                                raise OSError('La entrada volvió a cambiar; no se sobrescribió.')
                            if startup_exists: winreg.SetValueEx(k,RUN_VALUE,0,old_startup_type,old_startup)
                            elif current is not None: winreg.DeleteValue(k,RUN_VALUE)
                    except OSError as e: QMessageBox.warning(parent,'Inicio automático',f'No se pudo restaurar la entrada anterior: {e}')
                return False
            visible=self.count.isVisible(); self.count.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,top.isChecked())
            if visible: self.count.show()
            self.render()
            return True

        return apply_options

    def set_background_power(self, saving):
        if self.background_low_power != saving:
            self.background_low_power = saving
            self.tick()

    def focus_alert_finished(self):
        self.alert = None
        self.tick()

    def tick(self):
        self.timer.stop()
        now=dt.datetime.now()
        t=target(self.cfg)
        seconds = (t-now).total_seconds() if t and self.cfg['show_timer'] else 0
        active = seconds > 0 and self.cfg['guardian']
        text=remaining(t) if t and self.cfg['show_timer'] else 'Cicerón'
        if self.count.text() != text:
            self.count.setText(text)
            # The actual native window, not only the painted text, must shrink.
            self.count.ensurePolished()
            width=self.count.fontMetrics().horizontalAdvance(text)+8
            if self.count.width() != width:
                self.count.setFixedWidth(width)
                self._position_count()
        delay = float('inf')
        if seconds > 0 and self.count.isVisible():
            # The text displays whole minutes and changes again at the deadline.
            delay = seconds % 60 + 0.020
        mono = time.monotonic()
        check_focus = False
        if active:
            delay = min(delay, seconds)
            if self.alert is None:
                # The cooldown also tells us when a new foreground check can matter.
                days = seconds / 86400
                cooldown = 1800 if days > 30 else 900 if days > 7 else 300 if days > 1 else 120
                interval = max(15 if self.background_low_power else 5, self.cfg['interval'])
                elapsed = mono - self.last_poll
                until_poll = min(interval, elapsed + seconds) - elapsed
                until_alert = self.last_alert + cooldown - mono
                check_focus = until_poll <= 0 and until_alert <= 0
                delay = min(delay, max(interval if check_focus else until_poll, until_alert))
                if until_alert > 0:
                    # Re-evaluate when the remaining time enters a shorter cooldown band.
                    boundary = next((days - band for band in (30, 7, 1) if days > band), None)
                    if boundary is not None:
                        delay = min(delay, boundary * 86400)
        if math.isfinite(delay):
            self.timer.start(max(20, min(2147483647, math.ceil(delay * 1000))))
        if not active:
            if self.alert: self.alert.close(); self.alert=None
            return
        if not check_focus:
            return
        self.last_poll = mono
        title = foreground().casefold()
        words = (word.strip().casefold() for word in str(self.cfg['words']).split(','))
        if any(word and word in title for word in words):
            from focus_alert import FocusAlert

            self.last_alert = mono
            self.alert = FocusAlert(self.window, lambda: remaining(t, show_seconds=True))
            self.alert.finished.connect(self.focus_alert_finished)
            self.alert.present()
            self.tick()
def open_source_session(root):
    lock = root / 'centro-fuentes.lock'
    # The launcher and installer briefly open this file exclusively to check
    # whether a source session is active. A probe must not interrupt startup.
    for attempt in range(30):
        try:
            return lock.open('ab')
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(.02)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--comprobacion-lente':
        from gpu_lens import check_desktop_lens
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        try:
            result = check_desktop_lens(app)
        except (OSError, RuntimeError) as error:
            result = {'native_capture': False, 'error': str(error)}
        Path(sys.argv[2]).write_text(json.dumps(result), encoding='utf-8')
        return 0 if result['native_capture'] else 1
    if len(sys.argv) == 3 and sys.argv[1] in ('--lanzar-paquete', '--abrir-herramienta'):
        try:
            request_launch(LAUNCH_REQUESTS, sys.argv[2], builtin=sys.argv[1] == '--abrir-herramienta')
        except (OSError, ValueError):
            return 1
    kernel = ctypes.windll.kernel32
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    kernel.CreateSemaphoreW.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_long,
                                        ctypes.c_wchar_p]
    kernel.CreateSemaphoreW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.CloseHandle.argtypes = kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.ReleaseSemaphore.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]
    kernel.ReleaseSemaphore.restype = ctypes.c_int
    suffix = instance_suffix()
    activate = kernel.CreateEventW(None, False, False, r'Local\Ciceron_AbrirCentro_v1' + suffix)
    if not activate:
        raise ctypes.WinError()
    toggle_center = kernel.CreateSemaphoreW(None, 0, 2147483647,
                                            r'Local\Ciceron_AlternarCentro_v2' + suffix)
    if not toggle_center:
        kernel.CloseHandle(activate)
        raise ctypes.WinError()
    mutex = kernel.CreateMutexW(None, False, r'Local\Ciceron_Unica_v2' + suffix)
    mutex_status = kernel.GetLastError()
    source_session = None
    try:
        if not mutex:
            raise ctypes.WinError(mutex_status)
        if mutex_status == 183:
            if '--alternar-centro' in sys.argv:
                if not kernel.ReleaseSemaphore(toggle_center, 1, None):
                    raise ctypes.WinError()
            elif '--abrir' in sys.argv:
                kernel.SetEvent(activate)
            return 0
        installed_source = source_installation_root()
        if installed_source is not None:
            source_session = open_source_session(installed_source)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Ciceron.MiCentro' + suffix)
        app = QApplication(sys.argv)
        app.setWindowIcon(icon())
        app.setQuitOnLastWindowClosed(False)
        controller = App()
        app.aboutToQuit.connect(controller.stop_visual_effects)
        app.aboutToQuit.connect(lambda: controller.birthday_host and controller.birthday_host.close())

        activation = watch_activation_event(app, kernel, activate, controller.open_center,
                                            controller.set_background_power,
                                            additional_events=((toggle_center, controller.toggle_center),))
        app.aboutToQuit.connect(activation.stop)
        power_events = SuspendResumeFilter(controller)
        app.installNativeEventFilter(power_events)
        power_events.register(controller.dock.winId())
        app.aboutToQuit.connect(power_events.stop)
        app.aboutToQuit.connect(lambda: app.removeNativeEventFilter(power_events))
        watch_launch_requests(app, LAUNCH_REQUESTS, controller.launch_requested_apps)
        if installed_source is not None and os.environ.get('CICERON_LIVE_SOURCE'):
            from live_reload import LiveReload

            reload = LiveReload(os.environ['CICERON_LIVE_SOURCE'], app, os.environ.get('CICERON_LIVE_DIGEST'))
            def restart_for_source_change():
                if app.activeModalWidget() is not None:
                    reload.timer.start()
                    return
                maintenance = kernel.CreateMutexW(None, False, r'Local\CiceronInstalacion')
                if maintenance:
                    try:
                        if kernel.WaitForSingleObject(maintenance, 0) not in (0, 0x80):
                            reload.timer.start()
                            return
                        kernel.ReleaseMutex(maintenance)
                    finally:
                        kernel.CloseHandle(maintenance)
                dock_panel_open = controller.dock is not None and controller.dock.panel is not None
                app.exit(76 if controller.window.isVisible() or dock_panel_open else 75)

            reload.restart.connect(restart_for_source_change)
        if '--alternar-centro' in sys.argv:
            controller.toggle_center()
        elif '--abrir' in sys.argv:
            controller.open_center()
        if '--comprobacion' in sys.argv:
            QTimer.singleShot(4000, app.quit)
        return app.exec()
    finally:
        if source_session is not None:
            source_session.close()
        if mutex:
            kernel.CloseHandle(mutex)
        kernel.CloseHandle(toggle_center)
        kernel.CloseHandle(activate)
if __name__=='__main__': sys.exit(main())
