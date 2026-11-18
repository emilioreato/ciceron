"""Panel de integración opcional de navegador."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QPlainTextEdit,QMessageBox,QInputDialog,QLineEdit,QCheckBox,QWidget)
from app_paths import application_root
import browser_bridge as bridge
from center_ui import GlassDialog

X_SIDEBAR='[data-testid=\"sidebarColumn\"]'
PASSPHRASE_HASH='bab27650cfa2f94d325b54d7e5de24d475dfee9a1849e0df7ac8b8aa90b137c5'

def label(text, kind=None):
    w=QLabel(text); w.setWordWrap(True)
    if kind: w.setObjectName(kind)
    return w

def extension_dir():
    root=application_root()
    pointer=root/'extension-path.txt'
    try:
        configured=Path(pointer.read_text(encoding='utf-8').strip())
        return (configured if configured.is_absolute() else root/configured).resolve()
    except OSError:
        installed=root/'00 EXTENSION'
        if installed.is_dir(): return installed
        return Path(__file__).resolve().parents[1]/'navegador'/'extension'

class BrowserDialog(GlassDialog):
    preferred_size_changed = Signal()

    def __init__(self,parent=None,attached=False):
        super().__init__(parent, attached=attached)
        self.setWindowTitle('Navegador · Cicerón')
        self.broken = False
        self.next_enabled = True
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 8, 12, 10)
        box.setSpacing(6)
        header = QHBoxLayout()
        header.addWidget(label('Navegador', 'title'), 1)
        self.status = QLabel()
        self.status.setFixedSize(10, 10)
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(header)

        row = QHBoxLayout()
        row.addWidget(label('Pausa Feed', 'heading'), 1)
        self.toggle = QPushButton()
        self.toggle.clicked.connect(lambda: self.change_enabled(self.next_enabled))
        row.addWidget(self.toggle)
        box.addLayout(row)
        self.sidebar = QCheckBox('Ocultar barra lateral de X')
        self.sidebar.clicked.connect(lambda: self.save_selectors(include_editor=False))
        box.addWidget(self.sidebar)

        advanced = QPushButton('Opciones avanzadas')
        advanced.setObjectName('advancedToggle')
        advanced.setCheckable(True)
        box.addWidget(advanced, alignment=Qt.AlignmentFlag.AlignLeft)
        self.advanced = QWidget()
        options = QVBoxLayout(self.advanced)
        options.setContentsMargins(0, 0, 0, 0)
        self.selectors = QPlainTextEdit()
        self.selectors.setPlaceholderText('Selectores CSS de X, uno por línea')
        self.selectors.setAccessibleName('Selectores CSS de X')
        self.selectors.setFixedHeight(76)
        options.addWidget(self.selectors)
        row = QHBoxLayout()
        save = QPushButton('Guardar selectores')
        save.clicked.connect(lambda: self.save_selectors(include_editor=True))
        row.addWidget(save)
        row.addStretch()
        options.addLayout(row)
        row = QHBoxLayout()
        install = QPushButton('Preparar navegador')
        install.clicked.connect(self.prepare_browser)
        row.addWidget(install)
        folder = QPushButton('Ver extensión')
        folder.setAccessibleName('Abrir carpeta de extensión')
        folder.clicked.connect(self.open_folder)
        row.addWidget(folder)
        options.addLayout(row)
        box.addWidget(self.advanced)
        self.advanced.hide()
        advanced.toggled.connect(self.show_options)
        if not attached:
            close = QPushButton('Cerrar')
            close.clicked.connect(self.accept)
            box.addWidget(close)
        self.resize(340 if attached else 540, self.sizeHint().height())
        try:
            self.policy = bridge.load_policy()
            self.sidebar.setChecked(X_SIDEBAR in self.policy['x_selectors'])
            self.selectors.setPlainText('\n'.join(s for s in self.policy['x_selectors'] if s != X_SIDEBAR))
        except (OSError,ValueError,TypeError) as e:
            self.broken = True
            self.policy = dict(bridge.DEFAULT)
            for widget in (self.toggle, save, self.sidebar, self.selectors):
                widget.setEnabled(False)
            QMessageBox.warning(self,'Configuración del navegador',f'No se pudo leer la configuración. No se sobrescribirá: {e}')
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(5000); self.finished.connect(self.timer.stop); self.refresh()

    def show_options(self, opened):
        self.advanced.setVisible(opened)
        if self.property('dockEmbedded'):
            # Let Qt recalculate the dialog layout before the attached panel
            # measures it. Measuring during the toggle can use the old height
            # and make the heading jump when the panel collapses.
            if self.layout() is not None:
                self.layout().activate()
            QTimer.singleShot(0, self.preferred_size_changed.emit)
        else:
            self.resize(self.width(), self.sizeHint().height())

    def refresh(self):
        connected = bridge.sessions()
        names = ', '.join(dict.fromkeys(item.get('browser', 'Navegador') for item in connected))
        requested = self.policy.get('enabled')
        states = [item.get('enabled') for item in connected]
        active = requested if requested is not None else True in states
        state = 'Activado' if active else 'Desactivado'
        if any(item.get('error') for item in connected):
            connection = 'Error de conexión'
            color = '#dd5c5e'
        elif requested is not None and any(current != requested for current in states):
            connection = f'{names} · sincronizando'
            color = '#dfa83c'
        elif names:
            connection = names
            color = '#33ad71' if active else '#dfa83c'
        else:
            connection = 'Sin conexión'
            color = '#dd5c5e'
        has_state = requested is not None or any(current is not None for current in states)
        status = f'{state} · {connection}' if has_state else connection
        self.status.setToolTip(status)
        self.status.setAccessibleName(status)
        self.status.setStyleSheet(f'background: {color}; border-radius: 5px;')
        self.next_enabled = not active
        action = 'Activar' if self.next_enabled else 'Desactivar'
        self.toggle.setText(action)
        self.toggle.setAccessibleName(f'{action} Pausa Feed')
    def persist(self,next_policy):
        try: bridge.save_policy(next_policy)
        except (OSError,ValueError) as e: QMessageBox.warning(self,'No se pudo guardar',str(e)); return False
        self.policy=bridge.validate(next_policy); self.refresh(); return True
    def change_enabled(self,enabled):
        if self.broken: return
        if not enabled:
            phrase,ok=QInputDialog.getText(self,'Pausar Pausa Feed','Escribe la frase que usabas en Pausa Feed:',QLineEdit.EchoMode.Password)
            if not ok: return
            if hashlib.sha256(phrase.encode('utf-8')).hexdigest()!=PASSPHRASE_HASH:
                QMessageBox.warning(self,'Pausa Feed','La frase no coincide.'); return
        next_policy=dict(self.policy); next_policy['enabled']=enabled; self.persist(next_policy)
    def save_selectors(self, include_editor=True):
        if self.broken:
            return
        next_policy = dict(self.policy)
        other = (self.selectors.toPlainText().splitlines() if include_editor else self.policy['x_selectors'])
        next_policy['x_selectors'] = ([X_SIDEBAR] if self.sidebar.isChecked() else []) + [
            value.strip() for value in other if value.strip() and value.strip() != X_SIDEBAR
        ]
        if self.persist(next_policy):
            if include_editor:
                QMessageBox.information(self, 'Selectores guardados', 'Los navegadores conectados recibirán el cambio.')
        else:
            self.sidebar.setChecked(X_SIDEBAR in self.policy['x_selectors'])
    def open_folder(self):
        folder=extension_dir()
        if not (folder/'manifest.json').is_file(): QMessageBox.warning(self,'Extensión no encontrada','Actualiza Cicerón desde el paquete para copiar la extensión.'); return
        try: os.startfile(str(folder))
        except OSError as e: QMessageBox.warning(self,'No se pudo abrir',str(e))
    def prepare_browser(self):
        from browser_setup import prepare, detected
        choices=detected()
        if not choices:
            QMessageBox.information(self,'Navegadores','No se detectó Chrome, Brave ni Edge. Puedes cargar la extensión manualmente y registrar el puente después.'); return
        selected,ok=QInputDialog.getItem(self,'Preparar navegador','Elige un navegador:',list(choices),0,False)
        if not ok: return
        try:
            result=prepare(selected)
        except (OSError,ValueError) as e:
            QMessageBox.warning(self,'No se pudo preparar',str(e)); return
        path=extension_dir()
        if QMessageBox.question(self,'Un paso en el navegador',f'Puente preparado para {selected}.\n\nSe abrirán la página de extensiones y la carpeta. Activa el modo desarrollador, elige «Cargar descomprimida» y selecciona la carpeta «00 EXTENSION».\n\nDespués desactiva la antigua Pausa Feed para no duplicar sus reglas.\n\n¿Abrir ambas ahora?') == QMessageBox.StandardButton.Yes:
            try:
                os.startfile(str(path))
                scheme={'Chrome':'chrome://extensions','Brave':'brave://extensions','Edge':'edge://extensions'}[selected]
                subprocess.Popen([str(choices[selected]),scheme])
            except OSError as e: QMessageBox.warning(self,'No se pudo abrir',str(e))
