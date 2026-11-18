"""Cicerón renders the settings declared by an installed package."""
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialogButtonBox, QFormLayout, QLineEdit, QPlainTextEdit,
                               QMessageBox, QProgressDialog, QScrollArea, QSpinBox, QVBoxLayout, QWidget)
from app_packages import text_setting_limit
from center_ui import GlassDialog, PreferenceBox, panel


def install_packages(parent, store, paths):
    def install():
        results = []
        for path in paths:
            try:
                status, spec = store.install(path)
                results.append(f"{spec['name']} {spec['version']} · {status}")
            except (OSError, ValueError) as error:
                results.append(f"{path.name} · {error}")
        return results

    progress = QProgressDialog(parent)
    progress.setWindowTitle('Importar aplicaciones')
    progress.setLabelText('Validando e instalando paquetes…')
    progress.setRange(0, 0)
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    timer = QTimer(progress)
    with ThreadPoolExecutor(max_workers=1) as executor:
        job = executor.submit(install)
        timer.timeout.connect(lambda: progress.accept() if job.done() else None)
        timer.start(40)
        if not job.done():
            progress.exec()
        timer.stop()
        result = job.result()
    progress.deleteLater()
    return result


def edit_settings(parent, store, app):
    spec = app['package']
    try:
        current = store.settings(spec)
    except (OSError, ValueError) as error:
        QMessageBox.warning(parent, 'Configuración de la aplicación', str(error))
        return
    dialog = GlassDialog(parent)
    dialog.setWindowTitle(f"Configurar {app['name']}")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(10)
    layout.addWidget(panel('title', app['name']))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    scroll.viewport().setObjectName("pageViewport")
    content.setObjectName("pageContent")
    form = QFormLayout(content)
    form.setContentsMargins(0, 0, 6, 0)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(10)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    controls = []
    expanded = 0
    for field in spec['settings']:
        value = current[field['id']]
        type_name = field['type']
        if type_name == 'boolean':
            widget = QCheckBox()
            widget.setChecked(value)
            getter = widget.isChecked
        elif type_name == 'integer':
            widget = QSpinBox()
            widget.setRange(field['min'], field['max'])
            widget.setValue(value)
            getter = widget.value
        elif type_name == 'choice':
            widget = PreferenceBox()
            widget.addItems(field['choices'])
            widget.setCurrentText(value)
            getter = widget.currentText
        elif field.get('multiline') or '\n' in value:
            widget = QPlainTextEdit(value)
            widget.setMinimumHeight(115)
            getter = widget.toPlainText
            expanded += 1
        else:
            widget = QLineEdit(value)
            widget.setMaxLength(text_setting_limit(field))
            getter = widget.text
        controls.append((field['id'], getter))
        title = panel('', field['label'])
        title.setBuddy(widget)
        widget.setAccessibleName(field['label'])
        if isinstance(widget, QPlainTextEdit):
            form.addRow(title)
            form.addRow(widget)
        else:
            form.addRow(title, widget)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText('Guardar')
    buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName('primary')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
    layout.addWidget(buttons)
    buttons.rejected.connect(dialog.reject)

    def save():
        try:
            store.save_settings(spec, {key: get() for key, get in controls})
        except (OSError, ValueError) as error:
            QMessageBox.warning(dialog, 'No se pudo guardar', str(error))
        else:
            dialog.accept()

    buttons.accepted.connect(save)
    dialog.resize(440, min(540, 106 + 44 * len(controls) + 104 * expanded))
    dialog.exec()
    dialog.deleteLater()
