"""Cicerón: centro personal para Windows, interfaz Qt."""
import ctypes, datetime as dt, json, math, os, sys, time, winreg
from _ctypes import COMError
from app_packages import PACKAGE_EXT, PackageStore, app_tags, fold_search
from browser_ui import BrowserDialog
from center_ui import CenterWindow, GlassDialog, LibraryBanner, PreferenceBox, dark_mode, panel, scrolled_page, stylesheet
from visual_playground import VisualDialog
from pathlib import Path
from PySide6.QtCore import QPoint, Qt, QTimer, QDate, QTime, Signal
from PySide6.QtGui import QIcon, QPainter, QColor, QPalette, QPixmap, QPen, QTextCharFormat
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QDateEdit, QTimeEdit, QCheckBox, QButtonGroup, QComboBox,
    QFrame, QFileDialog, QFileIconProvider, QInputDialog, QMessageBox, QSystemTrayIcon, QMenu,
    QAbstractSpinBox, QCalendarWidget, QSizePolicy, QStackedWidget, QToolButton)
from PySide6.QtCore import QFileInfo, QSize
from package_ui import edit_settings, install_packages
from start_menu import StartMenuApps, pending_launches, request_launch
from windows_glass import restore_above_taskbar

DATA = Path(os.environ.get('APPDATA', str(Path.home()))) / 'GanaLaBatalla'
CONFIG = DATA / 'config.json'; APPS = DATA / 'apps.json'
PACKAGE_TAGS = DATA / 'etiquetas-paquetes.json'
LAUNCH_REQUESTS = DATA / 'arranques-paquetes'
DEFAULT = dict(title='Mi objetivo', target='', show_timer=True, guardian=True,
               words='youtube, x.com, twitter, instagram', interval=3, topmost=True, geometry='', count_x_ratio=None,
               theme='system', glass=True, clarity='balanced', open_center_on_start=False,
               ui_version='v2', dock_motion=True)
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'

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

def remaining(t):
    seconds=(t-dt.datetime.now()).total_seconds()
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
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._stacking_check = QTimer(self)
        self._stacking_check.setInterval(150)
        self._stacking_check.timeout.connect(self._restore_stacking)

    def showEvent(self, event):
        super().showEvent(event)
        if self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            self._stacking_check.start()

    def hideEvent(self, event):
        self._stacking_check.stop()
        super().hideEvent(event)

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

class App:
    def __init__(self):
        data, broken=read(CONFIG,{}); self.cfg=DEFAULT.copy()
        if isinstance(data,dict): self.cfg.update({k:v for k,v in data.items() if k in DEFAULT})
        if self.cfg['theme'] not in ('system', 'light', 'dark'):
            self.cfg['theme'] = DEFAULT['theme']
        if self.cfg['clarity'] not in ('clear', 'balanced', 'contrast'):
            self.cfg['clarity'] = DEFAULT['clarity']
        if self.cfg['ui_version'] not in ('v1', 'v2'):
            self.cfg['ui_version'] = DEFAULT['ui_version']
        try:
            self.cfg['interval'] = max(1, int(self.cfg['interval']))
        except (ValueError, TypeError, OverflowError):
            self.cfg['interval'] = DEFAULT['interval']
        self.apps, self.bad_apps=read(APPS,[])
        if not isinstance(self.apps,list) or any(not isinstance(i,dict) or not isinstance(i.get('name'),str) or not isinstance(i.get('path'),str) for i in self.apps): self.apps=[]; self.bad_apps=True
        self.package_tags, self.bad_package_tags = read(PACKAGE_TAGS, {})
        if not isinstance(self.package_tags, dict):
            self.package_tags, self.bad_package_tags = {}, True
        self.packages = PackageStore(self.install_dir() / 'paquetes', DATA / 'datos-apps')
        self.start_menu = StartMenuApps(DATA.parent / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Ciceron',
                                        self.install_dir() / 'Ciceron.exe')
        self.managed_apps = []
        self.package_error = None
        try:
            self.packages.sweep()
        except (OSError, ValueError):
            pass  # A locked record can be read safely; debris can be retired at the next start.
        self.reload_packages()
        self.last_poll=0; self.last_alert=float('-inf'); self.alert=None
        self.broken_config = broken or not isinstance(data, dict)
        self.dock = None
        self.dock_signature = None
        self.classic = None
        self.build_window()
        self.apply_appearance()
        QApplication.styleHints().colorSchemeChanged.connect(self.apply_appearance)
        self.count=CountdownButton(); self.count.setWindowTitle('Timer')
        self.count.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.count.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,bool(self.cfg['topmost']))
        self.count.setFixedSize(160,24); self.count.setWindowOpacity(0.9)
        self.count.setStyleSheet('QPushButton { background: #1c1c1c; color: white; border: 0; border-radius: 0; padding: 0; font: 10pt "Segoe UI"; }')
        self.count.setToolTip('Clic para configurar · arrastra para mover en la barra')
        self.count.moved.connect(self._remember_count_position)
        self._count_fits=False
        self._count_hidden_by_layout=False
        self._count_screen=None
        QApplication.instance().primaryScreenChanged.connect(self._set_count_screen)
        self._set_count_screen(QApplication.primaryScreen())
        self.count.clicked.connect(self.edit_goal)
        self.tray=QSystemTrayIcon(icon()); menu=QMenu(self.window)
        menu.addAction('Abrir Cicerón',self.show)
        menu.addAction('General', lambda: self.open_page('general'))
        menu.addAction('Ajustes', lambda: self.open_page('settings'))
        menu.addAction('Estado', lambda: self.open_page('status'))
        photo = menu.addAction('Preparar captura con Cicerón', self.prepare_glass_photo)
        menu.aboutToShow.connect(lambda: photo.setEnabled(
            getattr(QApplication.instance(), '_ciceron_overlay', None) is not None or
            (self.dock is not None and self.dock.backdrop is not None)))
        menu.addSeparator()
        menu.addAction('Timer',self.edit_goal); menu.addAction('Mostrar contador',self._show_count); menu.addAction('Ocultar contador',self._hide_count); menu.addAction('Cerrar efectos visuales',self.stop_visual_effects); menu.addSeparator(); menu.addAction('Salir',QApplication.quit)
        self.tray.setContextMenu(menu); self.tray.setToolTip('Cicerón'); self.tray.activated.connect(self.tray_clicked); self.tray.show()
        self.render(); self.timer=QTimer(); self.timer.timeout.connect(self.tick); self.timer.start(1000); self.tick()
        if self.cfg['show_timer'] and target(self.cfg): self._show_count()
        if self.broken_config: QMessageBox.warning(self.window,'Configuración','No se pudo leer la configuración; se conservó el archivo original.')
        if self.cfg['open_center_on_start']:
            self.open_center()
        elif not CONFIG.exists() or not QSystemTrayIcon.isSystemTrayAvailable():
            self.show()
        elif self.cfg['ui_version'] == 'v2':
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
    def _remember_count_position(self, x):
        if self._count_screen is None: return
        screen=self._count_screen.geometry(); available=max(1,screen.width()-self.count.width())
        previous=self.cfg.get('count_x_ratio')
        self.cfg['count_x_ratio']=max(0.0,min(1.0,(x-screen.x())/available))
        if not self.save(): self.cfg['count_x_ratio']=previous
    def tray_clicked(self,reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,QSystemTrayIcon.ActivationReason.DoubleClick): self.show()
    def build_window(self):
        self.window = CenterWindow()
        self.window.material_changed = self.update_window_style
        self.window.setWindowTitle('Cicerón')
        self.window.resize(418, 390)
        self.window.setMinimumSize(340, 315)
        outer = QVBoxLayout(self.window)
        outer.setContentsMargins(8, 5, 7, 7)
        outer.setSpacing(8)
        menu = QHBoxLayout()
        menu.setSpacing(4)
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
            menu.addWidget(item)
        menu.addStretch(1)
        outer.addLayout(menu)
        outer.addWidget(self.pages, 1)
        self.nav.button(self.page_ids['general']).setChecked(True)
        self.window.setProperty('localWheel', True)

    def apply_appearance(self, *_):
        classic = self.cfg['ui_version'] == 'v1'
        self.window.monochrome = classic
        self.window.dark = False if classic else dark_mode(self.cfg['theme'])
        self.window.glass = bool(self.cfg['glass']) and not classic
        self.window.transparency = {'clear': 0.20, 'balanced': 0.0, 'contrast': -0.18}.get(
            self.cfg['clarity'], 0.0)
        self.window.enable_material(self.window.glass, self.window.dark)
        if self.dock is not None:
            self.dock.set_glass(self.window.glass)
            self.dock.motion_enabled = bool(self.cfg['dock_motion'])
            self.dock.transparency = self.window.transparency
            self.dock.layer.update()
            self.dock.update()
        self.update_window_style()

    def update_window_style(self):
        self.banner.glass = not self.window.monochrome
        QApplication.instance().setStyleSheet(stylesheet(self.window.dark, self.window.glass, self.window.monochrome))
        self.window.update()
        self.banner.update()
        if self.pages.currentIndex() == self.page_ids['status']:
            self.refresh_status()

    def build_general(self, content):
        from edge_dock import tool_icon
        self.banner = LibraryBanner()
        layout = QVBoxLayout(self.banner)
        layout.setContentsMargins(16, 10, 16, 11)
        layout.setSpacing(3)
        layout.addWidget(caption('Mis aplicaciones', 'heroTitle'))
        self.library_summary = caption('', 'heroDetail')
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
                               [('Abrir', lambda checked=False, tool=key: self.open_tool(tool))], style=key + 'Card')
            self.builtin_cards.append((detail.parentWidget(), fold_search(' '.join((title, description, *tags)))))
            if key == 'clock':
                self.goal_detail = detail
        content.addWidget(button('Aplicaciones instaladas de Windows',
                                 lambda: self.open_location('ms-settings:appsfeatures')),
                          alignment=Qt.AlignmentFlag.AlignLeft)

    def build_library(self, content):
        self.app_search = QLineEdit()
        self.app_search.setPlaceholderText('Buscar por nombre o etiqueta')
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
        version.setAccessibleName('Versión de la interfaz')
        version.addItem('V1 · Clásica', 'v1')
        version.addItem('V2 · Liquid Glass', 'v2')
        version.setCurrentIndex(version.findData(self.cfg['ui_version']))
        version.currentIndexChanged.connect(
            lambda index: self.change_preference('ui_version', version.itemData(index), version))
        self.card(content, 'Interfaz', '', control=version)
        theme = PreferenceBox()
        theme.setAccessibleName('Tema')
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
        glass.toggled.connect(lambda checked: self.change_preference('glass', checked, glass))
        self.card(content, 'Liquid Glass', '', control=glass)
        clarity = PreferenceBox()
        clarity.setAccessibleName('Transparencia del vidrio')
        for label, value in (('Alta', 'clear'), ('Media', 'balanced'), ('Baja', 'contrast')):
            clarity.addItem(label, value)
        clarity.setCurrentIndex(max(0, clarity.findData(self.cfg['clarity'])))
        clarity.setEnabled(glass.isChecked())
        glass.toggled.connect(lambda _: clarity.setEnabled(glass.isChecked()))
        clarity.currentIndexChanged.connect(
            lambda index: self.change_preference('clarity', clarity.itemData(index), clarity))
        self.card(content, 'Transparencia', '', control=clarity)
        content.addWidget(caption('Inicio', 'heading'))
        startup = ClearCheckBox()
        startup.setFixedSize(22, 22)
        startup.setAccessibleName('Mostrar el centro al abrir Cicerón')
        startup.setChecked(bool(self.cfg['open_center_on_start']))
        startup.toggled.connect(lambda checked: self.change_preference('open_center_on_start', checked, startup))
        self.card(content, 'Abrir el centro al iniciar', '', control=startup)
        self.card(content, 'Windows y enfoque', '', [('Opciones', self.options)])

    def build_status(self, content):
        content.addWidget(button('Volver a comprobar', self.refresh_status),
                          alignment=Qt.AlignmentFlag.AlignLeft)
        self.status_fields = {}
        for name, title, actions in (
            ('program', 'Instalación de Cicerón', [('Abrir carpeta', self.open_install_folder)]),
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
        box = QHBoxLayout(frame)
        box.setContentsMargins(11, 4, 9, 4)
        box.setSpacing(12)
        if image is not None:
            badge = QLabel()
            badge.setPixmap(image.pixmap(QSize(30, 30)))
            box.addWidget(badge)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = caption(name, 'heading')
        text.addWidget(title)
        detail = caption(description, 'muted')
        if style == 'appCard':
            for label in (title, detail):
                policy = label.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
                label.setSizePolicy(policy)
        text.addWidget(detail)
        if not description:
            detail.hide()
        box.addLayout(text, 1)
        for label, callback in actions:
            box.addWidget(button(label, callback))
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
        self.apply_appearance()
        if key == 'ui_version' and self.cfg[key] != previous:
            self.window.hide()
            self.show()

    def select_page(self, key):
        index = self.page_ids[key]
        self.nav.button(index).setChecked(True)
        self.pages.setCurrentIndex(index)
        self.window.setProperty('localWheel', key == 'general')
        if key == 'general':
            self.render_library()
        elif key == 'status':
            self.refresh_status()

    def open_page(self, key):
        self.select_page(key)
        self.render()
        if self.dock is not None and self.dock.isVisible() and self.dock.screen:
            if self.dock.panel is None or self.dock.panel.key != 'settings':
                self.dock.toggle_panel('settings', lambda: self.window, persistent=True)
            else:
                self.dock.panel.raise_()
            return
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def open_center(self):
        self.show()
        if self.cfg['ui_version'] == 'v2':
            self.open_page('general')

    def show(self):
        if self.cfg['ui_version'] == 'v1':
            if self.dock is not None:
                self.dock.hide()
            self.show_classic()
            return
        if self.classic is not None:
            self.classic.hide()
        self.show_edge_dock()
        self.dock.reveal()

    def show_edge_dock(self):
        if self.dock is None:
            from edge_dock import EdgeDock
            self.dock = EdgeDock(icon(), self.toggle_settings_panel)
        self.refresh_dock()
        self.dock.set_glass(self.cfg['glass'])
        self.dock.motion_enabled = bool(self.cfg['dock_motion'])
        self.dock.transparency = self.window.transparency
        self.dock.show()
        self.dock.raise_()

    def toggle_settings_panel(self):
        def settings():
            self.select_page('general')
            self.render()
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
        from edge_dock import tool_icon
        entries = [
            ('Timer', tool_icon('clock'), lambda: self.open_tool('clock')),
            ('Navegador', tool_icon('browser'), lambda: self.open_tool('browser')),
            ('Efectos de escritorio', tool_icon('lens'), lambda: self.open_tool('effects')),
        ]
        for entry in dock_apps:
            wheel = entry['package']['dock']['wheel'] if entry.get('package') else 'passthrough'
            entries.append((entry['name'], self.app_icon(entry),
                            lambda checked=False, item=entry: self.launch(item), wheel))
        self.dock.set_entries(entries)
        self.dock_signature = signature

    def open_tool(self, key):
        if self.dock is not None and self.dock.isVisible():
            factories = {
                'clock': lambda: self.goal_dialog(attached=True),
                'browser': lambda: BrowserDialog(self.window, attached=True),
                'effects': lambda: VisualDialog(self.window, attached=True, dock_provider=lambda: self.dock),
            }
            self.dock.toggle_panel(key, factories[key])
        else:
            {'clock': self.edit_goal, 'browser': self.browser_settings, 'effects': self.visual_playground}[key]()

    def show_classic(self):
        if self.classic is None:
            self.classic = QWidget()
            self.classic.setWindowTitle('Mi centro')
            self.classic.setWindowIcon(icon())
            self.classic.resize(500, 430)
            self.classic.setMinimumSize(420, 300)
            self.classic.setStyleSheet('''
                QWidget { background: #fafafa; color: #202020; font: 13px "Segoe UI"; }
                QLabel#classicTitle { font-size: 23px; font-weight: 650; }
                QLabel#heading { font-size: 15px; font-weight: 650; }
                QLabel#muted { color: #555555; }
                QFrame#card { background: #fff; border: 1px solid #ddd; border-radius: 6px; }
                QPushButton { background: #fff; color: #202020; border: 1px solid #bbb;
                              border-radius: 5px; padding: 6px 11px; }
                QPushButton:hover { background: #ededed; }
                QPushButton#primary { background: #242424; color: white; }
                QPushButton:focus { border: 2px solid #444; }
            ''')
            content = QVBoxLayout(self.classic)
            content.setContentsMargins(22, 19, 22, 16)
            header = QHBoxLayout()
            header.addWidget(caption('Mi centro', 'classicTitle'), 1)
            header.addWidget(button('Añadir aplicación', self.add_app, True))
            content.addLayout(header)
            scroll, self.classic_rows = scrolled_page(self.classic)
            content.addWidget(scroll, 1)
            footer = QHBoxLayout()
            footer.addWidget(button('Ajustes', lambda: self.open_page('settings')))
            footer.addStretch()
            footer.addWidget(button('Cerrar', self.classic.hide))
            content.addLayout(footer)
        self.render_classic()
        self.classic.show()
        self.classic.raise_()
        self.classic.activateWindow()

    def render_classic(self):
        while self.classic_rows.count():
            widget = self.classic_rows.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        when = target(self.cfg)
        label = remaining(when) if when else 'Configura tu objetivo'
        self.card(self.classic_rows, 'Timer y enfoque', label, [('Configurar', self.edit_goal)])
        self.card(self.classic_rows, 'Navegador', 'Pausa Feed', [('Configurar', self.browser_settings)])
        self.card(self.classic_rows, 'Efectos de escritorio', 'Burbuja y partículas', [('Abrir', self.visual_playground)])
        for entry in self.library_apps():
            spec = entry.get('package')
            remove = 'Desinstalar' if spec else 'Quitar'
            actions = [('Abrir', lambda checked=False, item=entry: self.launch(item))]
            if spec and spec['settings']:
                actions.append(('Configurar', lambda checked=False, item=entry: edit_settings(self.classic, self.packages, item)))
            actions.append((remove, lambda checked=False, item=entry: self.remove(item)))
            self.card(self.classic_rows, entry['name'], self.app_description(entry), actions, image=self.app_icon(entry))

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
            total = len(self.library_apps())
            word = 'aplicación guardada' if total == 1 else 'aplicaciones guardadas'
            self.library_summary.setText(f'{total} {word}')
        self.refresh_dock()
        if self.classic is not None and self.classic.isVisible():
            self.render_classic()
        if self.pages.currentIndex() == self.page_ids['general']:
            self.render_library()
        elif self.pages.currentIndex() == self.page_ids['status']:
            self.refresh_status()

    def render_library(self, *_):
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
                'Importa un paquete .ciceron, un ejecutable o un acceso directo.')
            self.library_rows.addWidget(caption(message, 'muted'))
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
            add_shortcut = start.addAction('Añadir acceso', lambda checked=False, i=item: self.add_start_shortcut(i))
            add_shortcut.setEnabled(exists)
            start.addAction('Quitar acceso', lambda checked=False, i=item: self.remove_start_shortcut(i))
            folder = menu.addAction('Abrir carpeta', lambda checked=False, p=path.parent: self.open_location(p))
            folder.setEnabled(path.parent.is_dir())
            menu.addSeparator()
            menu.addAction('Desinstalar paquete' if spec else 'Quitar de Cicerón',
                           lambda checked=False, i=item: self.remove(i))
            more.setMenu(menu)
            description = f"Versión {spec['version']}" if spec else 'Acceso vinculado'
            if not exists:
                description = 'Archivo no encontrado'
            elif tags:
                description = ' · '.join(tags[:2])
            detail = self.card(self.library_rows, item['name'], description,
                               [('Abrir', lambda checked=False, i=item: self.launch(i))] if exists else (),
                               control=more, image=self.app_icon(item), style='appCard')
            tooltip = self.app_description(item)
            if tags:
                tooltip += '\nEtiquetas: ' + ', '.join(tags)
            detail.parentWidget().setToolTip(tooltip)

    def tags_for(self, item):
        package = item.get('package')
        values = self.package_tags.get(package['id'], package.get('tags', [])) if package else item.get('tags', [])
        try:
            return app_tags(values)
        except ValueError:
            return []

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
            if old is not None and old['path'] != item['path']:
                self.add_start_shortcut(item, previous=old)

    def add_start_shortcut(self, item, previous=None):
        try:
            self.start_menu.update(item, self.tags_for(item), previous)
        except (OSError, ValueError, COMError) as error:
            QMessageBox.warning(self.window, 'Inicio de Windows', str(error))

    def remove_start_shortcut(self, item):
        try:
            self.start_menu.remove(item)
        except (OSError, ValueError, COMError) as error:
            QMessageBox.warning(self.window, 'Inicio de Windows', str(error))

    def library_apps(self):
        return self.apps + self.managed_apps

    def app_icon(self, item):
        if item.get('icon'):
            bundled = QIcon(item['icon'])
            if not bundled.isNull():
                return bundled
        path = Path(item['path'])
        return self.file_icons.icon(QFileInfo(str(path))) if path.is_file() else icon()

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
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'GanaLaBatalla'

    def open_install_folder(self):
        folder = self.install_dir()
        self.open_location(folder if folder.is_dir() else Path(sys.executable).parent)

    def refresh_status(self):
        from browser_bridge import sessions
        install = self.install_dir() / 'Ciceron.exe'
        running_installed = getattr(sys, 'frozen', False) and Path(sys.executable) == install
        installed = install.is_file()
        state = 'Instalado y en ejecución' if installed and running_installed else (
            'Instalado · esta ventana se ejecuta desde otra copia' if installed else
            'Instalación de usuario no encontrada')
        fields = self.status_fields
        for detail in fields.values():
            detail.show()
        fields['program'].setText(state)
        fields['program'].setToolTip(str(install))
        shortcut = Path(os.environ.get('APPDATA', str(Path.home()))) / 'Microsoft/Windows/Start Menu/Programs/Mi centro.lnk'
        fields['shortcut'].setText('Acceso encontrado' if shortcut.is_file() else 'Acceso no encontrado')
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as registry:
                raw, _ = winreg.QueryValueEx(registry, 'GanaLaBatalla')
            startup = 'Activado' if isinstance(raw, str) and Path(
                os.path.expandvars(raw.strip().strip('"'))) == install and installed else 'La entrada apunta a otra ruta'
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
        fields['glass'].setToolTip(getattr(self.window.material, 'error', None) or '')
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

    def prepare_glass_photo(self):
        app = QApplication.instance()
        bubble = getattr(app, '_ciceron_overlay', None)
        dock = self.dock if self.dock is not None and self.dock.isVisible() else None
        if (bubble is None or not bubble.isVisible()) and dock is None:
            return
        self.tray.showMessage('Captura con Cicerón',
                              'Tienes tres segundos para abrir el panel o colocar la burbuja.',
                              QSystemTrayIcon.MessageIcon.Information, 2300)

        def freeze():
            if bubble is not None and getattr(app, '_ciceron_overlay', None) is bubble:
                bubble.show_in_screenshots()
            if self.dock is dock and dock is not None:
                dock.show_in_screenshots()

        QTimer.singleShot(3500, freeze)
    def visual_playground(self):
        dialog = VisualDialog(self.window, dock_provider=lambda: self.dock)
        if self.dock is not None and self.dock.isVisible() and self.dock.screen:
            area = self.dock.screen.availableGeometry()
            dialog.move(max(area.x(), area.right() - self.dock.WIDTH - dialog.width() - 12),
                        area.center().y() - dialog.height() // 2)
        dialog.exec()
    def browser_settings(self):
        dialog=BrowserDialog(self.window)
        dialog.exec()
    def launch(self,item):
        try:
            if item.get('package'):
                self.packages.launch(item)
            else:
                if not Path(item['path']).is_file(): raise FileNotFoundError('No se encuentra el archivo; puede que se haya movido.')
                os.startfile(item['path'])
        except (OSError, ValueError) as e: QMessageBox.warning(self.window,'No se pudo abrir',str(e))

    def launch_requested_packages(self):
        for app_id in pending_launches(LAUNCH_REQUESTS):
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
            write(APPS, entries)
        except OSError as error:
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
    def edit_goal(self):
        self.goal_dialog().exec()

    def goal_dialog(self, attached=False):
        d=GlassDialog(self.window); d.setWindowTitle('Timer'); d.resize(350,276)
        box=QVBoxLayout(d); box.setContentsMargins(12,9,12,11); box.setSpacing(8)
        head=QHBoxLayout(); head.addWidget(caption('Timer','title')); head.addStretch()
        more=button('Opciones',self.options); more.setObjectName('quiet'); head.addWidget(more); box.addLayout(head)
        name=QLineEdit(str(self.cfg['title'])); name.setAccessibleName('Nombre del objetivo'); name.setPlaceholderText('Nombre del objetivo'); box.addWidget(name)
        t=target(self.cfg); date=QDateEdit(); date.setAccessibleName('Fecha'); date.setDisplayFormat('dd-MM-yyyy'); date.setDate(QDate(t.year,t.month,t.day) if t else QDate.currentDate())
        date.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        date_field = QFrame()
        date_field.setObjectName('dateField')
        date_field.setStyleSheet('''
            QFrame#dateField { background: white; border-radius: 9px; }
            QFrame#dateField QDateEdit { background: transparent; color: #202020; border: 1px solid transparent; }
            QFrame#dateField QPushButton#calendarButton { background: white; color: #383838; border: 1px solid transparent; padding: 4px 8px; }
            QFrame#dateField QDateEdit:focus, QFrame#dateField QPushButton#calendarButton:focus,
            QFrame#dateField QPushButton#calendarButton:hover { border-color: #929292; }
        ''')
        date_row = QHBoxLayout(date_field)
        date_row.setContentsMargins(2, 0, 3, 0)
        date_row.setSpacing(0)
        date_row.addWidget(date, 1)
        picker = QDialog(d, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        picker.setWindowTitle('Elegir fecha')
        picker.setStyleSheet(stylesheet(False, False, neutral=True) +
                             '''
            QCalendarWidget QWidget { font-size: 12px; }
            QCalendarWidget QWidget#qt_calendar_navigationbar { background: #f1f1f1; }
            QCalendarWidget QToolButton { background: transparent; color: #202020; border: 0; padding: 3px; }
            QCalendarWidget QToolButton:hover { background: #e4e4e4; }
            QCalendarWidget QAbstractItemView {
                background: white; color: #202020; alternate-background-color: #f3f3f3;
                selection-background-color: #333; selection-color: white;
            }
        ''')
        picker_layout = QVBoxLayout(picker)
        picker_layout.setContentsMargins(7, 6, 7, 6)
        picker_layout.setSpacing(4)
        calendar = QCalendarWidget(picker)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        palette = calendar.palette()
        for role, color in (('Base', '#ffffff'), ('AlternateBase', '#f3f3f3'), ('Window', '#ffffff'),
                            ('WindowText', '#202020'), ('Text', '#202020'), ('Button', '#f1f1f1'),
                            ('ButtonText', '#202020'), ('Highlight', '#333333'), ('HighlightedText', '#ffffff')):
            palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
        calendar.setPalette(palette)
        weekend = QTextCharFormat()
        weekend.setForeground(QColor('#545454'))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            calendar.setWeekdayTextFormat(day, weekend)
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

        def choose_date():
            if picker.isVisible():
                picker.reject()
                return
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

        calendar.clicked.connect(selected)
        calendar.activated.connect(selected)
        calendar_button = button('Calendario', choose_date)
        calendar_button.setObjectName('calendarButton')
        calendar_button.setAutoDefault(False)
        date_row.addWidget(calendar_button)
        box.addWidget(date_field)
        time_row=QHBoxLayout(); use_time=ClearCheckBox('Elegir una hora'); use_time.setChecked(bool(t and (t.hour,t.minute)!=(0,0)))
        clock=QTimeEdit(); clock.setDisplayFormat('HH:mm'); clock.setTime(QTime(t.hour,t.minute) if t else QTime(0,0)); clock.setEnabled(use_time.isChecked()); clock.setMaximumWidth(108)
        clock.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        clock.setAccessibleName('Hora')
        use_time.setToolTip('Si dejas la hora desactivada, la fecha vence a las 00:00.')
        chosen_time=[QTime(clock.time())]
        def change_time(enabled):
            if enabled: clock.setTime(chosen_time[0])
            else: chosen_time[0]=QTime(clock.time()); clock.setTime(QTime(0,0))
            clock.setEnabled(enabled)
        use_time.toggled.connect(change_time); time_row.addWidget(use_time); time_row.addStretch(); time_row.addWidget(clock)
        box.addLayout(time_row)
        guard=ClearCheckBox('Avisos de distracción'); guard.setChecked(bool(self.cfg['guardian'])); box.addWidget(guard)
        box.addStretch()
        row=QHBoxLayout(); stop=button('Detener',lambda: d.done(2)); stop.setObjectName('destructive'); stop.setEnabled(bool(self.cfg['show_timer'] and t)); row.addWidget(stop)
        stop.setStyleSheet('''
            QPushButton#destructive { background: #ffeded; color: #8f242c; border: 1px solid #e9aab0; }
            QPushButton#destructive:hover, QPushButton#destructive:focus { border-color: #a94b53; }
            QPushButton#destructive:disabled { background: #eaeaea; color: #555555; border-color: transparent; }
        ''')
        row.addStretch()
        if not attached:
            row.addWidget(button('Cancelar', d.reject))
        row.addWidget(button('Guardar y empezar',d.accept,True)); box.addLayout(row)
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
        box.addWidget(caption('Windows y enfoque','title')); box.addWidget(caption('Palabras de aviso','muted'))
        words=QLineEdit(str(self.cfg['words'])); box.addWidget(words)
        words.setToolTip('Palabras separadas por comas que Cicerón busca en el título de la ventana activa.')
        top=QCheckBox('Mantener el contador sobre otras ventanas'); top.setChecked(bool(self.cfg['topmost'])); box.addWidget(top)
        startup=QCheckBox('Abrir al iniciar sesión en Windows')
        old_startup=None; old_startup_type=None; startup_exists=False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as k:
                old_startup,old_startup_type=winreg.QueryValueEx(k,'GanaLaBatalla'); startup_exists=True
        except FileNotFoundError: pass
        except OSError as e:
            QMessageBox.warning(self.window,'Inicio automático',f'No se pudo consultar el Registro: {e}'); return
        install_dir=Path(os.environ.get('LOCALAPPDATA','')) / 'GanaLaBatalla'
        owned_paths={os.path.normcase(str(install_dir / name)) for name in ('Ciceron.exe','GanaLaBatalla.exe')}
        own_entry=isinstance(old_startup,str) and os.path.normcase(os.path.expandvars(old_startup.strip().strip('"'))) in owned_paths
        installed_executable=os.path.normcase(os.path.abspath(sys.executable)) in owned_paths
        can_manage=bool(getattr(sys,'frozen',False)) and installed_executable and (not startup_exists or own_entry)
        startup.setChecked(bool(startup_exists and own_entry)); startup.setEnabled(can_manage)
        if not can_manage:
            message=('La entrada de inicio pertenece a otro programa y no se modificará.' if startup_exists and not own_entry
                     else 'El inicio automático se configura desde la versión instalada.')
            startup.setToolTip(message); box.addWidget(caption(message,'muted'))
        box.addWidget(startup); box.addStretch(); row=QHBoxLayout(); row.addStretch(); row.addWidget(button('Cancelar',d.reject)); row.addWidget(button('Guardar',d.accept,True)); box.addLayout(row)
        def apply_options(result):
            if result != QDialog.DialogCode.Accepted:
                return
            changed_startup=can_manage and startup.isChecked()!=startup_exists
            if changed_startup:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
                        try: current=winreg.QueryValueEx(k,'GanaLaBatalla')
                        except FileNotFoundError: current=None
                        expected=(old_startup,old_startup_type) if startup_exists else None
                        if current != expected:
                            raise OSError('La entrada de inicio cambió mientras estaba abierta la ventana. Vuelve a abrir los ajustes.')
                        if startup.isChecked(): winreg.SetValueEx(k,'GanaLaBatalla',0,winreg.REG_SZ,'"'+sys.executable+'"')
                        else: winreg.DeleteValue(k,'GanaLaBatalla')
                except OSError as e: QMessageBox.warning(self.window,'Inicio automático',str(e)); return
            old=self.cfg.copy(); self.cfg.update(words=words.text(),topmost=top.isChecked())
            if not self.save():
                self.cfg=old
                if changed_startup:
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
                            try: current=winreg.QueryValueEx(k,'GanaLaBatalla')
                            except FileNotFoundError: current=None
                            expected=('"'+sys.executable+'"',winreg.REG_SZ) if startup.isChecked() else None
                            if current != expected:
                                raise OSError('La entrada volvió a cambiar; no se sobrescribió.')
                            if startup_exists: winreg.SetValueEx(k,'GanaLaBatalla',0,old_startup_type,old_startup)
                            elif current is not None: winreg.DeleteValue(k,'GanaLaBatalla')
                    except OSError as e: QMessageBox.warning(self.window,'Inicio automático',f'No se pudo restaurar la entrada anterior: {e}')
                return
            visible=self.count.isVisible(); self.count.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,top.isChecked())
            if visible: self.count.show()
            self.render()

        d.finished.connect(apply_options)
        if self.dock is not None and self.dock.panel is not None and self.dock.panel.key in ('settings', 'clock'):
            self.dock.panel.open_subpanel(d)
        else:
            d.exec()

    def tick(self):
        now=dt.datetime.now(); t=target(self.cfg)
        text=remaining(t) if t and self.cfg['show_timer'] else 'Cicerón'
        if self.count.text() != text:
            self.count.setText(text)
            # The actual native window, not only the painted text, must shrink.
            self.count.ensurePolished()
            width=self.count.fontMetrics().horizontalAdvance(text)+8
            if self.count.width() != width:
                self.count.setFixedWidth(width)
                self._position_count()
        active=bool(t and t>now and self.cfg['show_timer'] and self.cfg['guardian'])
        if not active:
            if self.alert: self.alert.close(); self.alert=None
            return
        mono=time.monotonic()
        if mono-self.last_poll<self.cfg['interval']: return
        self.last_poll=mono; title=foreground().casefold(); words=[w.strip() for w in str(self.cfg['words']).split(',') if w.strip()]
        found=next((w for w in words if w.casefold() in title),None); days=(t-now).total_seconds()/86400
        cooldown=1800 if days>30 else 900 if days>7 else 300 if days>1 else 120
        if found and self.alert is None and mono-self.last_alert>=cooldown:
            self.last_alert=mono; self.alert=QMessageBox(self.window); self.alert.setWindowTitle('Gana la batalla'); self.alert.setText('Gana la batalla'); self.alert.setInformativeText(f'Has abierto una ventana que coincide con «{found}». ¿Quieres volver a tu objetivo?')
            self.alert.setStandardButtons(QMessageBox.StandardButton.Ok)
            stop=self.alert.addButton('Detener avisos',QMessageBox.ButtonRole.ActionRole)
            stop.clicked.connect(self.stop_alerts)
            self.alert.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
            self.alert.finished.connect(lambda _: setattr(self,'alert',None)); self.alert.show()
    def stop_alerts(self):
        old=self.cfg['guardian']; self.cfg['guardian']=False
        if not self.save(): self.cfg['guardian']=old; return
        if self.alert: self.alert.close(); self.alert=None

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
    if len(sys.argv) == 3 and sys.argv[1] == '--lanzar-paquete':
        try:
            request_launch(LAUNCH_REQUESTS, sys.argv[2])
        except (OSError, ValueError):
            return 1
    kernel = ctypes.windll.kernel32
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    activate = kernel.CreateEventW(None, False, False, r'Local\Ciceron_AbrirCentro_v1')
    if not activate:
        raise ctypes.WinError()
    mutex = kernel.CreateMutexW(None, False, r'Local\GanaLaBatalla_Unica_v1')
    mutex_status = kernel.GetLastError()
    try:
        if not mutex:
            raise ctypes.WinError(mutex_status)
        if mutex_status == 183:
            if '--abrir' in sys.argv:
                kernel.SetEvent(activate)
            return 0
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Ciceron.MiCentro')
        app = QApplication(sys.argv)
        app.setWindowIcon(icon())
        app.setQuitOnLastWindowClosed(False)
        controller = App()
        app.aboutToQuit.connect(controller.stop_visual_effects)

        def process_activation():
            if kernel.WaitForSingleObject(activate, 0) == 0:
                controller.open_center()

        controller.timer.timeout.connect(process_activation)
        controller.timer.timeout.connect(controller.launch_requested_packages)
        QTimer.singleShot(0, controller.launch_requested_packages)
        if '--abrir' in sys.argv:
            controller.open_center()
        if '--comprobacion' in sys.argv:
            QTimer.singleShot(4000, app.quit)
        return app.exec()
    finally:
        if mutex:
            kernel.CloseHandle(mutex)
        kernel.CloseHandle(activate)
if __name__=='__main__': sys.exit(main())
