"""Panel de integración opcional de navegador."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QMessageBox, QInputDialog, QLineEdit, QCheckBox)
from app_paths import application_root, development_mode
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
    def __init__(self,parent=None,attached=False):
        super().__init__(parent, attached=attached)
        self.setWindowTitle('Bloqueo web · Cicerón')
        self.broken = False
        self.next_enabled = True
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(10)
        box.addWidget(label('Bloqueo web', 'title'))

        row = QHBoxLayout()
        details = QVBoxLayout()
        details.setSpacing(2)
        details.addWidget(label('Pausa Feed', 'heading'))
        self.status = label('', 'muted')
        details.addWidget(self.status)
        row.addLayout(details, 1)
        self.toggle = QPushButton()
        self.toggle.setObjectName('primary')
        self.toggle.clicked.connect(lambda: self.change_enabled(self.next_enabled))
        row.addWidget(self.toggle)
        box.addLayout(row)
        self.sidebar = QCheckBox('Ocultar barra lateral de X')
        self.sidebar.clicked.connect(lambda: self.save_selectors())
        box.addWidget(self.sidebar)

        row = QHBoxLayout()
        details = QVBoxLayout()
        details.setSpacing(2)
        details.addWidget(label('Reglas de X', 'heading'))
        self.rules_count = label('', 'muted')
        details.addWidget(self.rules_count)
        row.addLayout(details, 1)
        self.edit_rules = QPushButton('Editar…')
        self.edit_rules.setAccessibleName('Editar reglas personalizadas de X')
        self.edit_rules.clicked.connect(self.open_rules)
        row.addWidget(self.edit_rules)
        box.addLayout(row)

        box.addSpacing(4)
        box.addWidget(label('Extensión del navegador', 'heading'))
        row = QHBoxLayout()
        row.addStretch()
        folder = QPushButton('Carpeta')
        folder.setObjectName('quiet')
        folder.setAccessibleName('Abrir carpeta de extensión')
        folder.clicked.connect(self.open_folder)
        row.addWidget(folder)
        install = QPushButton('Preparar')
        install.setAccessibleName('Preparar navegador')
        install.setEnabled(not development_mode())
        install.clicked.connect(self.prepare_browser)
        row.addWidget(install)
        box.addLayout(row)
        if not attached:
            close = QPushButton('Cerrar')
            close.clicked.connect(self.accept)
            box.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        try:
            self.policy = bridge.load_policy()
            self.sidebar.setChecked(X_SIDEBAR in self.policy['x_selectors'])
        except (OSError,ValueError,TypeError) as e:
            self.broken = True
            self.policy = dict(bridge.DEFAULT)
            for widget in (self.toggle, self.sidebar, self.edit_rules):
                widget.setEnabled(False)
            QMessageBox.warning(self,'Configuración del navegador',f'No se pudo leer la configuración. No se sobrescribirá: {e}')
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(5000); self.finished.connect(self.timer.stop); self.refresh()
        self.resize(340 if attached else 430, self.sizeHint().height())

    def custom_selectors(self):
        return [value for value in self.policy['x_selectors'] if value != X_SIDEBAR]

    def open_rules(self):
        editor = SelectorDialog(self, self.custom_selectors(), self.save_selectors)
        editor.exec()
        editor.deleteLater()

    def refresh(self):
        connected = bridge.sessions()
        names = ', '.join(dict.fromkeys(item.get('browser', 'Navegador') for item in connected))
        requested = self.policy.get('enabled')
        states = [item.get('enabled') for item in connected]
        active = requested if requested is not None else True in states
        state = 'Activado' if active else 'Desactivado'
        if any(item.get('error') for item in connected):
            connection = 'Error de conexión'
        elif requested is not None and any(current != requested for current in states):
            connection = f'{names} · sincronizando'
        elif names:
            connection = names
        else:
            connection = 'Sin navegador conectado'
        has_state = requested is not None or any(current is not None for current in states)
        status = f'{state} · {connection}' if has_state else connection
        self.status.setText(status)
        count = len(self.custom_selectors())
        self.rules_count.setText(f'{count} reglas' if count != 1 else '1 regla')
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
    def save_selectors(self, values=None):
        if self.broken:
            return False
        next_policy = dict(self.policy)
        other = self.custom_selectors() if values is None else values
        next_policy['x_selectors'] = ([X_SIDEBAR] if self.sidebar.isChecked() else []) + [
            value.strip() for value in other if value.strip() and value.strip() != X_SIDEBAR
        ]
        saved = self.persist(next_policy)
        if not saved:
            self.sidebar.setChecked(X_SIDEBAR in self.policy['x_selectors'])
        return saved
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


class SelectorDialog(GlassDialog):
    def __init__(self, parent, selectors, save):
        super().__init__(parent)
        self.setWindowTitle('Reglas personalizadas de X')
        self.resize(460, 330)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(10)
        box.addWidget(label('Reglas de X', 'title'))
        box.addWidget(label('Cada selector CSS oculta un elemento en X. Haz doble clic para editar una regla.', 'muted'))
        self.rules = QListWidget()
        self.rules.setAccessibleName('Selectores CSS guardados')
        for selector in selectors:
            self.add_rule(selector)
        box.addWidget(self.rules, 1)

        row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText('Nuevo selector CSS')
        self.entry.setAccessibleName('Nuevo selector CSS')
        row.addWidget(self.entry, 1)
        add = QPushButton('Añadir')
        add.setAutoDefault(False)
        add.clicked.connect(self.add_pending)
        self.entry.returnPressed.connect(self.add_pending)
        row.addWidget(add)
        box.addLayout(row)

        row = QHBoxLayout()
        remove = QPushButton('Quitar')
        remove.setObjectName('destructive')
        remove.setAutoDefault(False)
        remove.setEnabled(False)
        remove.clicked.connect(lambda: self.rules.takeItem(self.rules.currentRow()))
        self.rules.itemSelectionChanged.connect(lambda: remove.setEnabled(bool(self.rules.selectedItems())))
        row.addWidget(remove)
        row.addStretch()
        cancel = QPushButton('Cancelar')
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        apply = QPushButton('Guardar')
        apply.setAutoDefault(False)
        apply.setObjectName('primary')
        apply.clicked.connect(lambda: self.save_rules(save))
        row.addWidget(apply)
        box.addLayout(row)
        self.entry.setFocus()

    def add_rule(self, selector):
        item = QListWidgetItem(selector, self.rules)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def add_pending(self):
        text = self.entry.text().strip()
        if text:
            self.rules.setCurrentItem(self.add_rule(text))
            self.entry.clear()

    def save_rules(self, save):
        self.add_pending()
        if save([self.rules.item(index).text() for index in range(self.rules.count())]):
            self.accept()
