"""Cicerón frontend for the same agenda, notification history and data format."""
import csv
from contextlib import nullcontext
from datetime import date
from pathlib import Path
import time

from PySide6.QtCore import QDate, QEasingCurve, QEvent, QLocale, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut, QTextCharFormat
from PySide6.QtWidgets import (QApplication, QCalendarWidget, QFileDialog, QGridLayout, QHBoxLayout,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from miniapp_ui import MiniappDialog, panel, stylesheet
if __package__:
    from . import birthdays as model, startup, windows_tray
else:
    import birthdays as model
    import startup
    import windows_tray

Birthday, clean_name, days_in_year, fold = model.Birthday, model.clean_name, model.days_in_year, model.fold
legacy_entries, load, merge_legacy, parse_date = model.legacy_entries, model.load, model.merge_legacy, model.parse_date
pending_today, record_notifications = model.pending_today, model.record_notifications
same_person, save, upcoming = model.same_person, model.save, model.upcoming
Tray, activate_existing, bring_to_front = windows_tray.Tray, windows_tray.activate_existing, windows_tray.bring_to_front

HERE = Path(__file__).resolve().parent


def action(layout, text, callback, role=''):
    button = QPushButton(text)
    button.setObjectName(role)
    button.clicked.connect(callback)
    layout.addWidget(button)
    return button


class BirthdayList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setStyleSheet("""
            QListWidget { border-radius: 11px; padding: 5px 6px 7px; font-size: 12px; }
            QListWidget::item { min-height: 20px; padding: 2px 5px; border-radius: 6px; }
        """)

    def resizeEvent(self, event):
        width = self.viewport().width()
        columns = 2 if width >= 420 else 1
        self.setGridSize(QSize(max(1, (width - 4) // columns), 27))
        super().resizeEvent(event)


class Agenda(MiniappDialog):
    def __init__(self, path, state, host=None):
        super().__init__(attached=host is not None)
        self.host = host
        self.path, self.records = path, state
        self.editing = None
        self.startup_enabled = None
        self.attempted = None
        self.receipts = {}
        self.current_day = date.today()
        if host is None:
            self.setWindowFlag(Qt.WindowType.Tool)
        self.setWindowTitle('Happy Birthday')
        self.setWindowIcon(QIcon(str(HERE / 'icono.ico')))
        self.resize(510, 355)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 20)
        header = QHBoxLayout()
        header.addWidget(panel('title', 'Happy Birthday'))
        header.addStretch()
        action(header, 'Almanaque', self.open_year)
        more = action(header, 'Más', lambda: None, 'quiet')
        more.setStyleSheet("""
            QPushButton { padding-right: 23px; }
            QPushButton::menu-indicator {
                subcontrol-origin: border; subcontrol-position: right center;
                right: 8px; width: 10px; height: 10px;
            }
        """)
        menu = QMenu(more)
        menu.addAction('Importar CSV…', self.import_csv)
        if host is None:
            self.autostart = menu.addAction('Iniciar con Windows')
            self.autostart.setCheckable(True)
            self.autostart.triggered.connect(self.configure_startup)
        menu.addAction('Probar aviso de Windows', self.test_notice)
        if host is None:
            menu.addSeparator()
            menu.addAction('Salir y pausar avisos', self.quit)
        more.setMenu(menu)
        layout.addLayout(header)

        layout.addWidget(panel('heading', 'Nuevo cumpleaños'))
        form = QHBoxLayout()
        self.day = QLineEdit(placeholderText='Fecha')
        self.day.setAccessibleName('Fecha de cumpleaños')
        self.day.setToolTip('Día, mes y año. El año puede quedar en blanco.')
        self.name = QLineEdit(placeholderText='Nombre')
        self.name.setAccessibleName('Nombre')
        for field in (self.day, self.name):
            field.setStyleSheet('QLineEdit { placeholder-text-color: rgba(120,120,120,205); }')
        form.addWidget(self.day, 3)
        form.addWidget(self.name, 3)
        self.submit_button = action(form, 'Añadir', self.submit, 'primary')
        self.cancel_button = action(form, 'Cancelar', self.clear_form)
        self.cancel_button.hide()
        layout.addLayout(form)
        self.feedback = panel('muted', '')
        self.feedback.setWordWrap(True)
        self.feedback.hide()
        layout.addWidget(self.feedback)

        layout.addWidget(panel('heading', 'Próximos cumpleaños'))
        self.search = QLineEdit(placeholderText='Buscar cumpleaños')
        self.search.setAccessibleName('Buscar cumpleaños')
        layout.addWidget(self.search)
        self.rows = BirthdayList()
        self.rows.setAccessibleName('Cumpleaños próximos')
        self.rows.itemDoubleClicked.connect(lambda _: self.edit_selected())
        layout.addWidget(self.rows, 1)
        self.empty = panel('muted', '')
        layout.addWidget(self.empty)
        row = QHBoxLayout()
        row.addStretch()
        self.edit_button = action(row, 'Editar', self.edit_selected)
        self.delete_button = action(row, 'Borrar', self.delete_selected, 'destructive')
        layout.addLayout(row)
        self.rows.currentItemChanged.connect(lambda *_: self.update_actions())
        self.search.textChanged.connect(self.render)
        self.day.returnPressed.connect(self.submit)
        self.name.returnPressed.connect(self.submit)
        QShortcut(QKeySequence('Ctrl+N'), self, activated=self.clear_form)
        QShortcut(QKeySequence('Ctrl+F'), self, activated=self.search.setFocus)
        QShortcut(QKeySequence('Ctrl+L'), self, activated=self.open_year)
        self.render()

        self.tray = (host if host is not None else
                     Tray(self, path.parent, HERE / 'icono.ico', self.restore, self.quit,
                          self.check_reminders, self.open_today))
        self.reminders = QTimer(self, interval=45_000)
        self.reminders.timeout.connect(self.check_reminders)
        self.reminders.start()

    # The native notification helper schedules follow-up work on its UI loop.
    def after_idle(self, callback):
        QTimer.singleShot(0, self, callback)

    def state(self):
        return 'normal' if self.isVisible() else 'withdrawn'

    def set_feedback(self, text):
        self.feedback.setText(text)
        self.feedback.setVisible(bool(text))

    def commit(self, state):
        try:
            lease = self.host.center.packages.data_lease(self.host.item['package']['id'], exclusive=False) if self.host else nullcontext()
            with lease:
                if self.host and load(self.path) != self.records:
                    self.check_reminders()
                    self.set_feedback('La agenda cambió. Revisá los datos y volvé a guardar.')
                    return False
                save(self.path, state)
        except (OSError, ValueError) as error:
            self.set_feedback(f'No se pudo guardar la agenda. {error}')
            return False
        self.records = state
        return True

    def selected(self):
        row = self.rows.currentItem()
        return row.data(Qt.ItemDataRole.UserRole) if row else None

    def update_actions(self):
        enabled = self.selected() is not None
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def render(self):
        self.rows.clear()
        today = date.today()
        needle = fold(self.search.text())
        for birthday in upcoming(self.records.entries, today):
            if needle and needle not in fold(f'{birthday.label} {birthday.short_date}'):
                continue
            upcoming_day = birthday.next_date(today)
            age = birthday.upcoming_age(upcoming_day)
            age_label = f' · {age} años' if age is not None else ''
            row = QListWidgetItem(f'{birthday.label}   ·   {upcoming_day:%d-%m-%Y}{age_label}')
            row.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.setToolTip(row.text())
            row.setData(Qt.ItemDataRole.UserRole, birthday)
            self.rows.addItem(row)
        self.empty.setText('No hay resultados.' if needle else 'Todavía no hay cumpleaños guardados.')
        self.empty.setVisible(self.rows.count() == 0)
        self.rows.setVisible(self.rows.count() != 0)
        self.update_actions()

    def clear_form(self, *, focus=True):
        self.editing = None
        self.day.clear()
        self.name.clear()
        self.submit_button.setText('Añadir')
        self.cancel_button.hide()
        self.rows.setCurrentItem(None)
        self.rows.clearSelection()
        if focus:
            self.day.setFocus()
        self.set_feedback('')

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        if self.editing is not None or self.selected() is not None:
            self.clear_form(focus=False)
        super().hideEvent(event)

    def eventFilter(self, widget, event):
        if event.type() != QEvent.Type.MouseButtonPress or not isinstance(widget, QWidget):
            return False
        if self.editing is None and self.selected() is None:
            return False
        controls = (self.day, self.name, self.submit_button, self.cancel_button,
                    self.edit_button, self.delete_button)
        if any(widget is control or control.isAncestorOf(widget) for control in controls):
            return False
        if self.rows.isAncestorOf(widget) and self.editing is None:
            position = self.rows.viewport().mapFromGlobal(event.globalPosition().toPoint())
            if self.rows.itemAt(position) is not None:
                return False
        self.clear_form(focus=False)
        return False

    def submit(self):
        try:
            parts = parse_date(self.day.text())
            name = clean_name(self.name.text(), optional=True)
        except ValueError as error:
            self.set_feedback(str(error))
            return
        birthday = Birthday(self.editing, name, *parts) if self.editing else Birthday.new(name, parts)
        others = [entry for entry in self.records.entries if entry.id != birthday.id]
        if any(same_person(birthday, entry) for entry in others):
            self.set_feedback('Ya guardaste ese cumpleaños.')
            return
        if self.commit(self.records.with_entries([*others, birthday])):
            self.clear_form()
            self.set_feedback(f'Guardado · {birthday.short_date}')
            self.render()
            self.check_reminders()

    def edit_selected(self):
        birthday = self.selected()
        if birthday:
            self.editing = birthday.id
            self.day.setText(birthday.input_date)
            self.name.setText(birthday.name)
            self.name.setFocus()
            self.submit_button.setText('Guardar')
            self.cancel_button.show()

    def delete_selected(self):
        birthday = self.selected()
        if not birthday:
            return
        reply = QMessageBox.question(self, 'Borrar cumpleaños', f'¿Borrar {birthday.label}?',
                                     defaultButton=QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self.commit(self.records.with_entries(entry for entry in self.records.entries if entry.id != birthday.id)):
            if self.editing == birthday.id:
                self.clear_form()
            self.render()

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importar cumpleaños', '', 'Archivos CSV (*.csv)')
        if not path:
            return
        try:
            rows = legacy_entries(Path(path))
        except (OSError, ValueError, csv.Error) as error:
            self.set_feedback(str(error))
            return
        before = len(self.records.entries)
        merged, skipped = merge_legacy(self.records.entries, rows)
        added = len(merged) - before
        if not added:
            self.set_feedback(f'No hay cumpleaños nuevos · Duplicados: {skipped}')
            return
        if QMessageBox.question(self, 'Importar cumpleaños', f'¿Importar {added} cumpleaños? Duplicados: {skipped}') != QMessageBox.StandardButton.Yes:
            return
        if self.commit(self.records.with_entries(merged)):
            self.set_feedback(f'Importados: {len(merged)-before} · Duplicados: {skipped}')
            self.render()
            self.check_reminders()

    def open_year(self, selected=None):
        calendar = Year(self, selected if isinstance(selected, date) else date.today())
        try:
            calendar.exec()
        finally:
            calendar.deleteLater()

    def open_today(self):
        self.restore()
        self.open_year(date.today())

    def configure_startup(self, enabled=None):
        try:
            self.startup_enabled = startup.setup(self.path.parent, enabled=enabled)
        except OSError as error:
            self.set_feedback(f'No se pudo configurar el inicio con Windows. {error}')
        self.autostart.setEnabled(self.startup_enabled is not None)
        self.autostart.setChecked(bool(self.startup_enabled))

    def test_notice(self):
        if not self.tray.show('Happy Birthday', 'Los avisos de cumpleaños usan esta notificación.', lambda: None):
            self.set_feedback('Windows no acepta el aviso en este momento.')

    def check_reminders(self):
        if self.host is not None:
            try:
                stored = load(self.path)
            except (OSError, ValueError):
                return
            if stored != self.records:
                self.records = stored
                self.render()
        today = date.today()
        if self.current_day != today:
            self.current_day = today
            self.render()
        for day, entries in list(self.receipts.items()):
            if self.commit(record_notifications(self.records, day, entries)):
                del self.receipts[day]
        due = pending_today(self.records, today)
        if not due or today in self.receipts:
            return
        key = today, frozenset(entry.id for entry in due)
        now = time.monotonic()
        if self.attempted and self.attempted[0] == key and now - self.attempted[1] < 240:
            return
        title = 'Hoy hay un cumpleaños' if len(due) == 1 else f'Hoy hay {len(due)} cumpleaños'
        names = ', '.join(entry.label for entry in due[:5])
        if len(due) > 5:
            names += f' y {len(due) - 5} más'
        if self.tray.show(title, names, lambda: self.confirm_notice(today, due)):
            self.attempted = key, now

    def confirm_notice(self, day, entries):
        if not self.commit(record_notifications(self.records, day, entries)):
            self.receipts[day] = entries

    def closeEvent(self, event):
        if self.host is not None:
            super().closeEvent(event)
            return
        if self.tray.ensure():
            self.hide()
        else:
            self.showMinimized()
        event.ignore()

    def reject(self):
        if self.host is not None:
            super().reject()
        else:
            self.close()

    def restore(self):
        if not self.isVisible() or self.isMinimized():
            self.showNormal()
        window = QApplication.activeModalWidget() or self
        window.raise_()
        window.activateWindow()
        bring_to_front(int(window.winId()))
        self.check_reminders()

    def quit(self):
        self.reminders.stop()
        self.tray.close()
        QApplication.instance().exit(0)


class Year(MiniappDialog):
    def __init__(self, agenda, selected):
        super().__init__(agenda, attached=agenda.host is not None)
        self.agenda = agenda
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setProperty('dockEmbedded', False)
        if agenda.host is not None:
            center = agenda.host.center
            self.glass = False
            self.setStyleSheet(stylesheet(center.window.dark, False, neutral=True))
        self.setWindowTitle('Almanaque')
        work = agenda.screen().availableGeometry()
        self.resize(min(1360, work.width() - 28), min(880, work.height() - 28))
        self.move(work.center() - self.rect().center())
        self.fade = QPropertyAnimation(self, b'windowOpacity', self)
        self.fade.setStartValue(.35)
        self.fade.setEndValue(1.0)
        self.fade.setDuration(160)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(panel('title', 'Almanaque'))
        header.addStretch()
        previous = action(header, '−', lambda: self.change(-1))
        previous.setAccessibleName('Año anterior')
        self.year = panel('heading', '')
        header.addWidget(self.year)
        following = action(header, '+', lambda: self.change(1))
        following.setAccessibleName('Año siguiente')
        action(header, 'Hoy', lambda: self.show_date(date.today()))
        action(header, 'Cerrar', self.accept)
        layout.addLayout(header)
        self.detail = panel('muted', '')
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        grid = QWidget()
        months = QGridLayout(grid)
        spanish = QLocale(QLocale.Language.Spanish)
        self.calendars = []
        columns = 4 if self.width() >= 940 else 3 if self.width() >= 700 else 2
        for index in range(12):
            month = QVBoxLayout()
            month.addWidget(panel('heading', spanish.monthName(index + 1).capitalize()))
            calendar = QCalendarWidget()
            calendar.setLocale(spanish)
            calendar.setNavigationBarVisible(False)
            calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
            calendar.clicked.connect(lambda value: self.show_date(value.toPython()))
            month.addWidget(calendar)
            months.addLayout(month, index // columns, index % columns)
            self.calendars.append(calendar)
        scroll.setWidget(grid)
        layout.addWidget(scroll)
        self.show_date(selected)

    def showEvent(self, event):
        super().showEvent(event)
        if self.agenda.host is None or self.agenda.host.center.cfg.get('dock_motion', True):
            self.fade.start()

    def change(self, delta):
        year = self.selected.year + delta
        if 1 <= year <= 9999:
            self.show_date(date(year, self.selected.month, 1))

    def show_date(self, selected):
        previous = getattr(self, 'selected', None)
        self.selected = selected
        self.year.setText(str(selected.year))
        if previous is None or previous.year != selected.year:
            if self.agenda.host is not None:
                self.days = self.agenda.host.calendar_days(selected.year)
            else:
                self.days = {day: [entry.label for entry in entries]
                             for day, entries in days_in_year(self.agenda.records.entries, selected.year).items()}
            marked = QTextCharFormat()
            marked.setFontWeight(QFont.Weight.Bold)
            marked.setFontUnderline(True)
            today = QDate.currentDate()
            for index, calendar in enumerate(self.calendars, 1):
                calendar.setDateTextFormat(QDate(), QTextCharFormat())
                for day in self.days:
                    if day.month == index:
                        event_style = QTextCharFormat(marked)
                        event_style.setToolTip('\n'.join(self.days[day]))
                        calendar.setDateTextFormat(QDate(day.year, day.month, day.day), event_style)
                if today.year() == selected.year and today.month() == index:
                    today_style = QTextCharFormat(marked)
                    today_style.setFontItalic(True)
                    today_style.setToolTip('\n'.join(self.days.get(today.toPython(), ['Hoy'])))
                    calendar.setDateTextFormat(today, today_style)
        value = QDate(selected.year, selected.month, selected.day)
        for index, calendar in enumerate(self.calendars, 1):
            calendar.setSelectedDate(value)
            calendar.setCurrentPage(selected.year, index)
        names = ', '.join(self.days.get(selected, ()))
        self.detail.setText(f'{selected:%d-%m-%Y} · {names or "Sin eventos"}')


def run(folder, instance):
    hidden = startup.consume_background_start(folder)
    with instance(folder) as acquired:
        if not acquired:
            if not hidden:
                for _ in range(10):
                    if activate_existing(folder):
                        break
                    time.sleep(.1)
            return
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        path = folder / 'cumpleanos.json'
        try:
            state = load(path)
        except (OSError, ValueError):
            if not hidden:
                QMessageBox.warning(None, 'No se pudo abrir la agenda', f'Revisá este archivo:\n{path}')
            return
        agenda = Agenda(path, state)
        QTimer.singleShot(250, agenda, agenda.configure_startup)
        QTimer.singleShot(950, agenda, agenda.check_reminders)
        if not hidden or not agenda.tray.ensure():
            agenda.restore()
            agenda.day.setFocus()
        try:
            app.exec()
        finally:
            agenda.tray.close()
