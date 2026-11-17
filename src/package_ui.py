"""Cicerón renders the settings declared by an installed package."""
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                               QMessageBox, QProgressDialog, QScrollArea, QSpinBox, QVBoxLayout, QWidget)
from center_ui import PreferenceBox


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
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"Configurar {app['name']}")
    layout = QVBoxLayout(dialog)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    form = QFormLayout(content)
    controls = []
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
        else:
            widget = QLineEdit(value)
            widget.setMaxLength(512)
            getter = widget.text
        controls.append((field['id'], getter))
        form.addRow(field['label'], widget)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText('Guardar')
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
    dialog.resize(405, min(505, 98 + 45 * len(controls)))
    dialog.exec()
    dialog.deleteLater()
