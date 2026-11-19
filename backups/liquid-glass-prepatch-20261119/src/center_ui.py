"""The native Cicerón window and its shared appearance."""
from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget


class PreferenceBox(QComboBox):
    def __init__(self):
        super().__init__()
        self.setObjectName('preference')

    def wheelEvent(self, event):
        event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().buttonText().color(), 1.6, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        center = QPointF(self.width() - 14, self.height() / 2)
        path = QPainterPath(center + QPointF(-3.5, -1.5))
        path.lineTo(center + QPointF(0, 2))
        path.lineTo(center + QPointF(3.5, -1.5))
        painter.drawPath(path)


def dark_mode(theme):
    return theme == 'dark' or (
        theme == 'system' and QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )


UI_VERSIONS = {'v1': 'V1 · Sólido', 'v2': 'V2 · Vidrio difuminado', 'v3': 'V3 · Vidrio transparente'}
V3_CONTROL_RADIUS = 11
APP_CARD_IDENTITY_RADIUS = 12


class AppCardIdentity(QFrame):
    """Icon and copy form one visual surface within a library card."""
    def __init__(self, icon, title, detail):
        super().__init__()
        self.setObjectName('appCardIdentity')
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 6, 10, 6)
        row.setSpacing(10)
        self.badge = QLabel()
        self.badge.setObjectName('appCardIcon')
        self.set_icon(icon)
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        for label in (title, detail):
            policy = label.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            label.setSizePolicy(policy)
            text.addWidget(label)
        detail.setWordWrap(True)
        row.addLayout(text, 1)

    def set_icon(self, icon):
        self.badge.setPixmap(icon.pixmap(30, 30))


def clear_styles(scope='', light=False, frost_controls=False, live_controls=False):
    # Keep the shared stylesheet's spacing, target sizes and semantic roles.
    scope = (scope + ' ') if scope else ''
    def rule(selectors, properties):
        return ', '.join(scope + selector for selector in selectors.split(', ')) + ' { ' + properties + ' }'
    controls = 'QPushButton, QToolButton, QComboBox, QLineEdit, QAbstractSpinBox, QPlainTextEdit'
    label_color = '#252a32' if light else '#f0f2f6'
    styles = (
        rule('QWidget', 'color: #f8f9fc; font-family: "Segoe UI Variable Text", "Segoe UI";'),
        rule('QLabel, QLabel#muted, QLabel#heroTitle, QLabel#heroDetail', f'color: {label_color}; background: transparent;'),
        rule('QCheckBox', f'color: {label_color}; background: transparent;'),
        rule('QFrame#sidebar, QFrame#card, QFrame#timeCard, QFrame#centerTabs, QFrame#clockCard, QFrame#browserCard, QFrame#effectsCard, QFrame#appCard',
             'background: transparent; border-color: transparent;'),
        rule('QFrame#appCardIdentity', f'border-radius: {APP_CARD_IDENTITY_RADIUS}px; '
             f'background: {"transparent" if live_controls else "rgba(30,30,30,145)"};'),
        rule(controls + ', QPushButton#primary, QPushButton#quiet, QPushButton#more, QPushButton#heroAction, QFrame#centerTabs QPushButton#nav, QFrame#appCard QPushButton',
             f'background: rgba(30,30,30,128); border: 1px solid transparent; border-radius: {V3_CONTROL_RADIUS}px; color: #fafafa;'),
        rule('QPushButton:hover, QPushButton:focus, QPushButton#quiet:hover, QPushButton#primary:hover, QFrame#centerTabs QPushButton#nav:focus',
             'background: rgba(56,56,56,165); border-color: transparent;'),
        rule('QPushButton:checked, QPushButton:pressed, QFrame#centerTabs QPushButton#nav:checked',
             'background: rgba(60,60,60,185); color: white; border-color: transparent;'),
        rule('QPushButton:disabled', 'color: #b3b8c2; background: rgba(38,42,48,100);'),
        rule('QPushButton#destructive', 'background: rgba(30,30,30,128); color: #fafafa; border-color: transparent;'),
        rule('QCalendarWidget, QCalendarWidget QWidget#qt_calendar_navigationbar, QCalendarWidget QAbstractItemView', 'background: rgba(30,30,30,135); color: white; alternate-background-color: transparent;'),
        rule('QMenu, QComboBox QAbstractItemView', 'background: #363636; color: #fafafa;'),
    )
    if live_controls:
        control_ink = '#202731' if frost_controls else '#f7f7f7'
        placeholder = '#4a5564' if frost_controls else '#dadada'
        disabled = '#596374' if frost_controls else '#cdcdcd'
        styles += (
            rule(controls + ', QPushButton:hover, QPushButton:pressed, QPushButton:checked, QPushButton#quiet, QPushButton#quiet:hover, QPushButton#primary, QPushButton#primary:hover, QPushButton#more, QPushButton#heroAction, QPushButton#destructive, QFrame#centerTabs QPushButton#nav, QFrame#centerTabs QPushButton#nav:checked, QFrame#appCard QPushButton',
                 f'background: transparent; color: {control_ink}; placeholder-text-color: {placeholder}; border: 1px solid transparent;'),
            rule('QPushButton:disabled, QPushButton#destructive:disabled, QAbstractSpinBox:disabled',
                 f'background: transparent; color: {disabled};'),
            rule('QPushButton:focus, QPushButton#quiet:focus, QPushButton#primary:focus, QLineEdit:focus, QAbstractSpinBox:focus',
                 'border-color: #64758c;'),
        )
    return '\n'.join(styles)


def stylesheet(dark=False, glass=True, monochrome=False, neutral=False):
    if neutral and dark:
        ink, muted, base, field, stroke, accent = '#f7f7f7', '#ededed', '#252525', '#353535', '#a7a7a7', '#ffffff'
        surface, highlight, pressed, danger = '#303030', '#454545', '#555555', '#ffb4bd'
        primary, primary_hover, primary_ink = '#eeeeee', '#ffffff', '#191919'
    elif monochrome or neutral:
        ink, muted, base, field, stroke, accent = '#242424', '#555555', '#fafafa', '#ffffff', '#bcbcbc', '#343434'
        surface, highlight, pressed, danger = '#ffffff', '#eeeeee', '#e0e0e0', '#8b3030'
        primary, primary_hover, primary_ink = '#343434', '#252525', '#ffffff'
    elif dark:
        ink, muted, base, field, stroke, accent = '#fafafa', '#e1e1e1', '#242424', '#363636', '#888888', '#e0e0e0'
        surface = 'rgba(50, 50, 50, 188)' if glass else '#303030'
        highlight, pressed, danger = '#474747', '#595959', '#ffb4bd'
        primary, primary_hover, primary_ink = '#dddddd', '#eeeeee', '#212121'
    else:
        ink, muted, base, field, stroke, accent = '#131e33', '#35415a', '#f0f4fc', '#ffffff', '#8296ba', '#183f82'
        surface = 'rgba(255, 255, 255, 171)' if glass else '#ffffff'
        highlight, pressed, danger = '#eaf1ff', '#dce9ff', '#a12840'
        primary, primary_hover, primary_ink = '#265ebc', '#1c50ab', '#ffffff'
    rim = 'rgba(220, 220, 220, 80)' if dark else 'rgba(255, 255, 255, 250)'
    button_fill = (
        f'qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {field},stop:1 {surface})'
        if glass else field
    )
    styles = f"""
    QWidget {{ color: {ink}; font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 14px; }}
    QDialog, QMenu, QCalendarWidget {{ background: {base}; }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-size: 34px; font-weight: 650; }}
    QDialog QLabel#title {{ font-size: 26px; }}
    QLabel#heading {{ font-size: 16px; font-weight: 650; }}
    QLabel#muted {{ color: {muted}; }}
    QLabel#heroTitle {{ color: white; font-size: 31px; font-weight: 650; }}
    QLabel#heroDetail {{ color: #e3eaff; font-size: 14px; }}
    QLabel#brand {{ font-size: 21px; font-weight: 650; }}
    QFrame#sidebar, QFrame#card, QFrame#timeCard, QFrame#clockCard, QFrame#browserCard,
    QFrame#effectsCard, QFrame#appCard {{
        background: {surface}; border: 1px solid {rim}; border-radius: 20px;
    }}
    QFrame#timeCard {{ border-color: {stroke}; }}
    QPushButton {{
        background: {button_fill}; border: 1px solid {stroke}; border-radius: 14px;
        padding: 7px 14px; min-height: 18px; font-weight: 550;
    }}
    QPushButton:hover {{ background: {highlight}; border-color: {accent}; }}
    QPushButton:pressed, QPushButton:checked {{ background: {pressed}; }}
    QPushButton:focus, QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {accent};
    }}
    QPushButton:disabled, QComboBox:disabled {{ color: {muted}; background: transparent; }}
    QPushButton#primary {{ background: {primary}; color: {primary_ink}; border: 1px solid {primary}; }}
    QPushButton#primary:hover {{ background: {primary_hover}; }}
    QPushButton#quiet, QPushButton#more {{ background: transparent; border-color: transparent; }}
    QPushButton#quiet:hover, QPushButton#more:hover {{ background: {highlight}; }}
    QPushButton#quiet:focus, QPushButton#more:focus {{ border-color: {accent}; }}
    QFrame#centerTabs {{ background: {surface}; border: 1px solid {rim}; border-radius: 13px; }}
    QFrame#centerTabs QPushButton#nav {{ padding: 4px 8px; border-radius: 9px; background: transparent; border: 1px solid transparent; }}
    QFrame#centerTabs QPushButton#nav:hover {{ background: {highlight}; }}
    QFrame#centerTabs QPushButton#nav:checked {{ color: {accent}; background: {pressed}; font-weight: 650; }}
    QFrame#centerTabs QPushButton#nav:focus {{ border-color: {accent}; }}
    QPushButton#more {{ padding: 4px 10px; font-size: 18px; }}
    QPushButton#more::menu-indicator {{ width: 0; }}
    QPushButton#destructive {{ color: {danger}; }}
    QPushButton#destructive:disabled {{ color: {muted}; }}
    QPushButton#heroAction {{ color: white; background: rgba(233,240,255,40); border-color: rgba(233,240,255,125); }}
    QPushButton#heroAction:hover, QPushButton#heroAction:focus {{ background: rgba(233,240,255,75); }}
    QLineEdit, QComboBox, QDateEdit, QTimeEdit, QPlainTextEdit, QListWidget {{
        background: {field}; border: 1px solid {stroke}; border-radius: 11px; padding: 7px 10px; min-height: 19px;
    }}
    QTimeEdit:disabled {{ color: {muted}; background: {base}; }}
    QComboBox QAbstractItemView, QListWidget {{ color: {ink}; background: {field}; selection-background-color: {pressed}; selection-color: {ink}; }}
    QPushButton#effectSwitch {{ text-align: left; padding-left: 11px; padding-right: 27px; }}
    QComboBox#preference {{ padding: 5px 27px 5px 9px; }}
    QComboBox#preference::drop-down {{ width: 25px; border: 0; background: transparent; }}
    QComboBox#preference::down-arrow {{ image: none; width: 0; height: 0; }}
    QCheckBox {{ spacing: 8px; padding: 3px 0; }}
    QScrollArea {{ border: 0; background: transparent; }}
    QWidget#pageViewport, QWidget#pageContent, QStackedWidget {{ background: transparent; }}
    QScrollBar:vertical {{ width: 9px; background: transparent; margin: 2px; }}
    QScrollBar::handle:vertical {{ min-height: 28px; border-radius: 3px; background: {stroke}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollArea#centerPage QScrollBar:vertical {{ width: 5px; margin: 3px 0; }}
    QScrollArea#centerPage QScrollBar::handle:vertical {{ min-height: 24px; border-radius: 2px; }}
    QScrollArea#centerPage QScrollBar::handle:vertical:hover {{ background: {accent}; }}
    QScrollArea#centerPage QScrollBar::handle:vertical:disabled,
    QScrollArea#centerPage QScrollBar::add-page:vertical,
    QScrollArea#centerPage QScrollBar::sub-page:vertical {{ background: transparent; }}
    QMenu {{ border: 1px solid {stroke}; border-radius: 12px; padding: 5px; }}
    QMenu::item {{ padding: 7px 20px; border-radius: 7px; }}
    QMenu::item:selected {{ color: {ink}; background: {pressed}; }}
    QMenu::item:disabled {{ color: {muted}; }}
    """
    if not monochrome:
        styles += """
        QFrame#clockCard, QFrame#browserCard, QFrame#effectsCard, QFrame#appCard { border-radius: 14px; }
        QFrame#clockCard { background: qlineargradient(x1:0,y1:1,x2:1,y2:0,stop:0 #244567, stop:1 #3a6082); }
        QFrame#browserCard { background: qlineargradient(x1:0,y1:1,x2:1,y2:0,stop:0 #285451, stop:1 #3b6864); }
        QFrame#effectsCard { background: qlineargradient(x1:0,y1:1,x2:1,y2:0,stop:0 #4e3b66, stop:1 #694e7c); }
        QFrame#appCard { background: qlineargradient(x1:0,y1:1,x2:1,y2:0,stop:0 #293956, stop:1 #455678); }
        QFrame#clockCard QLabel, QFrame#browserCard QLabel, QFrame#effectsCard QLabel, QFrame#appCard QLabel { color: #f7f7fa; }
        QWidget QFrame#appCard QPushButton { color: #f7f7fa; background: rgba(233,240,255,40); border-color: rgba(233,240,255,125); }
        QFrame#appCard QPushButton#more { color: #f7f7fa; background: transparent; }
        QFrame#appCard QPushButton:hover, QFrame#appCard QPushButton#more:hover,
        QFrame#appCard QPushButton:focus, QFrame#appCard QPushButton#more:focus { background: rgba(233,240,255,75); }
        """
    else:
        styles += """
        QLabel#heroTitle { color: #242424; }
        QLabel#heroDetail { color: #555555; }
        """
    if glass:
        control_outline = 'rgba(211, 224, 255, 110)' if dark else 'rgba(40, 61, 102, 100)'
        styles += f"""
        QWidget#liveWindow QFrame#sidebar, QWidget#liveWindow QFrame#card,
        QWidget#liveWindow QFrame#timeCard,
        QWidget#liveWindow QPushButton, QWidget#liveWindow QLineEdit, QWidget#liveWindow QComboBox,
        QWidget#liveWindow QAbstractSpinBox, QWidget#liveWindow QPlainTextEdit {{
            background: transparent; border-color: transparent; color: {ink};
        }}
        QWidget#liveWindow QPushButton, QWidget#liveWindow QLineEdit, QWidget#liveWindow QComboBox,
        QWidget#liveWindow QAbstractSpinBox, QWidget#liveWindow QPlainTextEdit {{
            border-color: {control_outline};
        }}
        QWidget#liveWindow QPushButton#primary, QWidget#liveWindow QPushButton#nav:checked {{
            color: {accent}; font-weight: 650;
        }}
        QWidget#liveWindow QPushButton#destructive:enabled {{ color: {danger}; }}
        QWidget#liveWindow QPushButton:disabled, QWidget#liveWindow QComboBox:disabled,
        QWidget#liveWindow QAbstractSpinBox:disabled {{ color: {muted}; }}
        QWidget#liveWindow QPushButton:focus, QWidget#liveWindow QLineEdit:focus, QWidget#liveWindow QComboBox:focus {{
            border-color: {accent};
        }}
        QWidget#liveWindow QLabel#heroTitle, QWidget#liveWindow QLabel#heroDetail {{
            color: {ink};
        }}
        """
    styles += '''
        '''
    styles += '''
            QPushButton#destructive { background: #ffeded; color: #8f242c; border: 1px solid #e9aab0; }
            QPushButton#destructive:hover, QPushButton#destructive:focus { border-color: #a94b53; }
            QPushButton#destructive:disabled { background: #eaeaea; color: #555555; border-color: transparent; }
        '''
    styles += f'''
                QCalendarWidget QWidget {{ font-size: 12px; }}
                QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {surface}; }}
                QCalendarWidget QToolButton {{ background: transparent; color: {ink}; border: 0; padding: 3px; }}
                QCalendarWidget QToolButton:hover {{ background: {highlight}; }}
                QCalendarWidget QAbstractItemView {{
                    background: {field}; color: {ink}; alternate-background-color: {surface};
                    selection-background-color: {primary}; selection-color: {primary_ink};
                }}
            '''
    return styles


class LiveMaterial:
    def init_material(self):
        self.dark = False
        self.glass = True
        self.transparency = 0.0
        self.live = False
        self.material = None
        self.material_changed = None

    def enable_material(self, enabled, dark):
        if self.property('dockEmbedded'):
            return
        if enabled and self.material is None:
            try:
                from window_glass import GlassBackdrop
                self.material = GlassBackdrop(self, self.set_live)
                self.material.floating_panel = getattr(self, 'floating', False)
            except (ImportError, OSError):
                return
        if self.material is not None:
            self.material.pure = bool(self.property('pureGlass'))
            self.material.dark = dark
            self.material.transparency = self.transparency
            if enabled and self.isVisible():
                self.material.start()
            elif not enabled:
                self.material.stop()

    def set_live(self, live):
        self.live = live
        self.setObjectName('liveWindow' if live else '')
        if self.material_changed:
            self.material_changed()
        else:
            style = stylesheet(self.dark, self.glass)
            if self.property('pureGlass'):
                style += clear_styles('QWidget#liveWindow' if live else '',
                                      frost_controls=self.property('frostControls'), live_controls=live)
            self.setStyleSheet(style)

    def showEvent(self, event):
        super().showEvent(event)
        if self.glass:
            self.enable_material(True, self.dark)

    def hideEvent(self, event):
        if self.material is not None:
            self.material.stop()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and not self.isMinimized() and self.glass:
            self.enable_material(True, self.dark)


class GlassDialog(LiveMaterial, QDialog):
    def __init__(self, parent=None, *, attached=False):
        super().__init__(parent)
        self.init_material()
        self.setProperty('dockEmbedded', attached)
        owner = parent.window() if parent else None
        self.glass = bool(getattr(owner, 'glass', False))
        pure = bool(QApplication.instance().property('pureGlass'))
        self.setProperty('pureGlass', pure)
        self.glass = self.glass or pure
        if pure and not attached:
            self.setWindowOpacity(0.995)
        self.dark = pure or getattr(owner, 'dark', False)
        self.transparency = getattr(owner, 'transparency', 0.0)


class CenterWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.monochrome = False
        self.dark = False
        self.glass = True
        self.transparency = 0.0

    def paintEvent(self, event):
        if self.property('dockEmbedded'):
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#fafafa' if self.monochrome else (
            '#222222' if self.dark else '#edf2fb')))
        if not self.glass:
            return
        width, height = self.width(), self.height()
        spots = (
            (.10, .12, .66, '#3a3a3a' if self.dark else '#b9cef5'),
            (.94, .10, .70, '#333333' if self.dark else '#dcd1f4'),
            (.83, 1.0, .65, '#303030' if self.dark else '#c1e4e8'),
        )
        for x, y, radius, color in spots:
            glow = QRadialGradient(QPointF(width * x, height * y), width * radius)
            glow.setColorAt(0, QColor(color))
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(self.rect(), glow)


class LibraryBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(116)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.glass = True
        self.live = False
        self.setObjectName('libraryBanner')

    def paintEvent(self, event):
        if self.live:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        outline = QPainterPath()
        outline.addRoundedRect(bounds, 25, 25)
        painter.setClipPath(outline)
        width, height = self.width(), self.height()
        backdrop = QLinearGradient(0, height, width, 0)
        backdrop.setColorAt(0, QColor('#163458'))
        backdrop.setColorAt(.58, QColor('#23365e'))
        backdrop.setColorAt(1, QColor('#545794'))
        painter.fillRect(bounds, backdrop if self.glass else QColor('#ededed'))
        if self.glass:
            self.draw_glass(painter, width, height)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(221, 233, 255, 130) if self.glass else QColor('#c8c8c8'), 1))
        painter.drawPath(outline)

    @staticmethod
    def draw_glass(painter, width, height):
        glow = QRadialGradient(QPointF(width * .87, height * .61), height * 1.2)
        glow.setColorAt(0, QColor(96, 190, 241, 150))
        glow.setColorAt(1, QColor(96, 190, 241, 0))
        painter.fillRect(QRectF(0, 0, width, height), glow)
        for index in range(3):
            wave = QPainterPath()
            x = width * .54 + 29 * index
            wave.moveTo(x - 17, height + 24)
            wave.cubicTo(x + 131, height * .70, x - 59, height * .35, x + 105, -16)
            wave.cubicTo(x + 176, -55, width + 115, height * .47, width + 5, height + 22)
            wave.closeSubpath()
            tint = QLinearGradient(x - 20, height, width + 8, 0)
            tint.setColorAt(0, QColor(114, 191, 252, 8))
            tint.setColorAt(.28, QColor(138, 223, 255, 135))
            tint.setColorAt(.57, QColor(182, 168, 255, 44))
            tint.setColorAt(.82, QColor(229, 242, 255, 150))
            tint.setColorAt(1, QColor(153, 199, 255, 38))
            painter.fillPath(wave, tint)
            painter.setPen(QPen(QColor(220, 245, 255, 140 - index * 25), 1.2))
            painter.drawPath(wave)


def panel(name, text, parent=None):
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class CenterPage(QScrollArea):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('centerPage')
        bar = self.verticalScrollBar()
        bar.setSingleStep(22)
        self.wheel_animation = QPropertyAnimation(bar, b'value', self)
        self.wheel_animation.setDuration(160)
        self.wheel_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        bar.actionTriggered.connect(self.wheel_animation.stop)

    def hideEvent(self, event):
        self.wheel_animation.stop()
        super().hideEvent(event)

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        animation = self.wheel_animation
        pixels = event.pixelDelta().y()
        angle = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier or bar.maximum() == 0:
            event.ignore()
            return
        if pixels or event.phase() != Qt.ScrollPhase.NoScrollPhase:
            animation.stop()
            if pixels:
                bar.setValue(bar.value() - pixels)
                event.accept()
            else:
                super().wheelEvent(event)
            return
        if not angle:
            event.ignore()
            return
        current = bar.value()
        target = animation.endValue() if animation.state() == QPropertyAnimation.State.Running else current
        steps = QApplication.styleHints().wheelScrollLines()
        destination = round(target - angle / 120 * bar.singleStep() * steps)
        animation.stop()
        animation.setStartValue(current)
        animation.setEndValue(max(bar.minimum(), min(bar.maximum(), destination)))
        animation.start()
        event.accept()


def scrolled_page(parent):
    scroll = CenterPage(parent)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    scroll.viewport().setObjectName('pageViewport')
    scroll.viewport().setAutoFillBackground(False)
    contents = QWidget()
    contents.setObjectName('pageContent')
    layout = QVBoxLayout(contents)
    layout.setContentsMargins(0, 0, 7, 4)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(contents)
    contents.setAutoFillBackground(False)
    return scroll, layout
