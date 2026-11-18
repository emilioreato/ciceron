"""Export selection and per-app import review."""
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLabel,
                              QMessageBox, QProgressDialog, QScrollArea, QVBoxLayout, QWidget)

from center_ui import GlassDialog
from data_transfer import DataArchive, EXTENSION, PORTABLE_PREFERENCES, export_data


def run_io(parent, label, operation):
    progress = QProgressDialog(label, '', 0, 0, parent)
    progress.setCancelButton(None)
    progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    progress.setMinimumDuration(0)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(operation)
        timer = QTimer(progress)
        timer.timeout.connect(lambda: progress.accept() if future.done() else None)
        timer.start(30)
        progress.exec()
        return future.result()


def selection(parent, title, rows, preference_available, action):
    dialog = GlassDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(470, 350)
    outer = QVBoxLayout(dialog)
    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    body = QWidget()
    layout = QVBoxLayout(body)
    choices = {}
    for app_id, label, checked, problem in rows:
        box = QCheckBox(label)
        box.setChecked(checked)
        box.setEnabled(problem is None)
        layout.addWidget(box)
        choices[app_id] = box
        if problem:
            detail = QLabel(problem)
            detail.setWordWrap(True)
            layout.addWidget(detail)
    layout.addStretch()
    scroll.setWidget(body)
    outer.addWidget(scroll)
    preferences = QCheckBox('Incluir preferencias generales del centro')
    if action == 'Importar':
        preferences.setText('Restaurar preferencias generales del centro')
    if preference_available:
        outer.addWidget(preferences)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    proceed = buttons.addButton(action, QDialogButtonBox.ButtonRole.AcceptRole)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    outer.addWidget(buttons)

    def update():
        proceed.setEnabled(preferences.isChecked() or any(box.isChecked() for box in choices.values()))

    for box in (*choices.values(), preferences):
        box.toggled.connect(update)
    update()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return [app_id for app_id, box in choices.items() if box.isChecked()], preferences.isChecked()


def export_dialog(parent, store, apps, preferences):
    rows = [(spec['id'], f"{spec['name']} ({spec['id']})", False, None)
            for spec in apps if spec.get('data') or any(field.get('portable', True) for field in spec['settings'])]
    chosen = selection(parent, 'Exportar datos', rows, True, 'Exportar')
    if chosen is None:
        return
    filename, _ = QFileDialog.getSaveFileName(parent, 'Guardar datos', 'Ciceron' + EXTENSION,
                                              f'Datos de Cicerón (*{EXTENSION})')
    if not filename:
        return
    destination = Path(filename)
    if destination.suffix.lower() != EXTENSION:
        destination = destination.with_name(destination.name + EXTENSION)
        if destination.exists() and QMessageBox.question(
                parent, 'Reemplazar archivo', f'¿Quieres reemplazar {destination.name}?'
        ) != QMessageBox.StandardButton.Yes:
            return
    ids, include_preferences = chosen
    values = {key: preferences[key] for key in PORTABLE_PREFERENCES if key in preferences}
    run_io(parent, 'Exportando datos…',
           lambda: export_data(store, destination, ids, values if include_preferences else None))
    QMessageBox.information(parent, 'Datos exportados', str(destination))


def import_dialog(parent, store, apply_preferences):
    filename, _ = QFileDialog.getOpenFileName(parent, 'Abrir datos', '', f'Datos de Cicerón (*{EXTENSION})')
    if not filename:
        return
    with ExitStack() as stack:
        def prepare():
            archive = stack.enter_context(DataArchive.open(Path(filename)))
            return archive, archive.preview(store)

        archive, preview = run_io(parent, 'Validando archivo de datos…', prepare)
        conflicts = {app_id for app_id, _, existing, _ in preview if existing}
        rows = []
        for app_id, name, existing, problem in preview:
            label = f'{name} ({app_id})' if app_id != name else app_id
            files = len(archive.apps[app_id]['files'])
            settings = len(archive.apps[app_id]['settings'])
            label += f' · {files} archivos, {settings} ajustes'
            if existing:
                label += ' · Reemplazar y respaldar los datos existentes'
            rows.append((app_id, label, not existing and problem is None, problem))
        chosen = selection(parent, 'Revisar datos para importar', rows, archive.preferences is not None, 'Importar')
        if chosen is None:
            return
        ids, include_preferences = chosen

        def restore():
            results = []
            for app_id in ids:
                try:
                    state, backup = archive.restore(store, app_id, replace_existing=app_id in conflicts)
                    message = f'{app_id}: {state}'
                    if backup is not None:
                        message += f' (respaldo en {backup})'
                except (OSError, ValueError) as error:
                    message = f'{app_id}: {error}'
                results.append(message)
            return results

        results = run_io(parent, 'Restaurando datos…', restore) if ids else []
        if include_preferences:
            results.append('Preferencias generales restauradas.' if apply_preferences(archive.preferences)
                           else 'No se guardaron las preferencias generales.')
        QMessageBox.information(parent, 'Resultado de la importación', '\n'.join(results))
