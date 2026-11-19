"""Cicerón frontend for the same agenda, notification history and data format."""
from calendar import monthrange
import csv
from contextlib import nullcontext
from datetime import date
from html import escape
from pathlib import Path
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QItemSelectionModel, QLocale, QPoint,
                            QPropertyAnimation, QRect, QSize, Qt, QTimer)
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFileDialog, QFrame, QHeaderView,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QToolTip, QVBoxLayout, QWidget)

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
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setStyleSheet("""
            QListWidget { border-radius: 11px; padding: 5px 6px 7px; font-size: 12px; }
            QListWidget::item { min-height: 20px; padding: 2px 5px; border-radius: 6px; }
        """)


class BirthdayRow(QWidget):
    def __init__(self, rows, item, text, on_delete, on_edit):
        super().__init__(rows)
        self.rows, self.item = rows, item
        self.on_edit = on_edit
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 4, 0)
        layout.setSpacing(6)
        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.label, 1)
        self.remove = QPushButton('×')
        self.remove.setObjectName('birthdayRemove')
        self.remove.setAccessibleName(f'Eliminar {text}')
        self.remove.setToolTip('Eliminar este cumpleaños')
        self.remove.setFixedSize(23, 23)
        self.remove.setStyleSheet("""
            QPushButton#birthdayRemove {
                color: #d94848; font-size: 18px; font-weight: 700;
                border: none; border-radius: 6px; padding: 0; background: transparent;
            }
            QPushButton#birthdayRemove:hover { background: rgba(217, 72, 72, 28); }
        """)
        self.remove.clicked.connect(on_delete)
        self.remove.hide()
        layout.addWidget(self.remove)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.rows.setCurrentItem(self.item, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.rows.setCurrentItem(self.item, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.on_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


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

        form_heading = QHBoxLayout()
        form_heading.addWidget(panel('heading', 'Nuevo cumpleaños'))
        form_heading.addStretch()
        self.feedback = panel('muted', '')
        self.feedback.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.feedback.setWordWrap(True)
        self.feedback.setMinimumWidth(0)
        self.feedback.setMaximumWidth(190)
        self.feedback.setToolTip('')
        form_heading.addWidget(self.feedback)
        layout.addLayout(form_heading)
        form = QHBoxLayout()
        self.day = QLineEdit(placeholderText='Ej. 8-9-2004')
        self.day.setAccessibleName('Fecha de cumpleaños')
        self.day.setToolTip('Día-mes-año o día-mes. También acepta barras, puntos o espacios.')
        self.name = QLineEdit(placeholderText='Ej. Gabriel')
        self.name.setAccessibleName('Nombre')
        for field in (self.day, self.name):
            field.setStyleSheet('QLineEdit { placeholder-text-color: rgba(120,120,120,205); }')
        form.addWidget(self.day, 3)
        form.addWidget(self.name, 3)
        self.submit_button = action(form, 'Añadir', self.submit, 'primary')
        layout.addLayout(form)
        self.feedback.hide()
        self.feedback_timer = QTimer(self, singleShot=True)
        self.feedback_timer.timeout.connect(lambda: self.set_feedback(''))

        layout.addWidget(panel('heading', 'Próximos cumpleaños'))
        self.search = QLineEdit()
        self.search.setAccessibleName('Buscar cumpleaños')
        layout.addWidget(self.search)
        self.rows = BirthdayList()
        self.rows.setAccessibleName('Cumpleaños próximos')
        self.rows.itemDoubleClicked.connect(lambda _: self.edit_selected())
        layout.addWidget(self.rows, 1)
        self.empty = panel('muted', '')
        layout.addWidget(self.empty)
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

    def set_feedback(self, text, *, timeout=0):
        self.feedback_timer.stop()
        self.feedback.setText(text)
        self.feedback.setToolTip(text)
        self.feedback.setVisible(bool(text))
        if text and timeout > 0:
            self.feedback_timer.start(timeout)

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
        current = self.rows.currentItem()
        for index in range(self.rows.count()):
            item = self.rows.item(index)
            row = self.rows.itemWidget(item)
            if isinstance(row, BirthdayRow):
                row.remove.setVisible(item is current)

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
            row_text = f'{birthday.label}   ·   {upcoming_day:%d-%m-%Y}{age_label}'
            row = QListWidgetItem()
            row.setToolTip(row_text)
            row.setData(Qt.ItemDataRole.AccessibleTextRole, row_text)
            row.setData(Qt.ItemDataRole.UserRole, birthday)
            row.setSizeHint(QSize(0, 31))
            self.rows.addItem(row)
            row_widget = BirthdayRow(
                self.rows,
                row,
                row_text,
                lambda checked=False, entry=birthday: self.delete_birthday(entry),
                self.edit_selected,
            )
            self.rows.setItemWidget(row, row_widget)
        self.empty.setText('No hay resultados.' if needle else 'Todavía no hay cumpleaños guardados.')
        self.empty.setVisible(self.rows.count() == 0)
        self.rows.setVisible(self.rows.count() != 0)
        self.update_actions()

    def clear_form(self, *, focus=True):
        self.editing = None
        self.day.clear()
        self.name.clear()
        self.submit_button.setText('Añadir')
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
        self.set_feedback('')
        if self.editing is not None or self.selected() is not None:
            self.clear_form(focus=False)
        super().hideEvent(event)

    def eventFilter(self, widget, event):
        if event.type() != QEvent.Type.MouseButtonPress or not isinstance(widget, QWidget):
            return False
        if self.editing is None and self.selected() is None:
            return False
        controls = (self.day, self.name, self.submit_button)
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
            self.set_feedback(f'Guardado · {birthday.short_date}', timeout=2800)
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

    def delete_birthday(self, birthday):
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
        if getattr(self, 'year_dialog', None) is not None:
            self.year_dialog.raise_()
            return
        calendar = Year(self, selected if isinstance(selected, date) else date.today())
        self.year_dialog = calendar

        def finished():
            self.year_dialog = None
            calendar.deleteLater()

        calendar.finished.connect(finished)
        calendar.open()

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


class Year(QDialog):
    def __init__(self, agenda, selected):
        super().__init__(agenda, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName('yearOverlay')
        self.agenda = agenda
        self.setWindowTitle('Almanaque')
        screen = agenda.screen()
        self.work = screen.availableGeometry()
        self.setScreen(screen)
        self.setGeometry(self.work)
        self.snapshot = QImage()
        self.origin = agenda.window().frameGeometry().translated(-self.work.topLeft())

        work = self.work
        width = min(work.width() - 24, max(640, round(min(1360, work.width() - 28) * .76)))
        height = min(work.height() - 24, max(360, round(min(880, work.height() - 28) * .78)))
        dark = agenda.host.center.window.dark if agenda.host else agenda.dark
        self.setStyleSheet(stylesheet(dark, False, neutral=True))
        self.card = QFrame(self)
        self.card.setObjectName('card')
        self.destination = QRect((work.width() - width) // 2, (work.height() - height) // 2, width, height)
        self.card.setGeometry(self.destination)
        self.content = QWidget(self.card)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(20, 15, 20, 16)
        header = QHBoxLayout()
        header.setSpacing(5)
        header.addWidget(panel('title', 'Almanaque'))
        header.addStretch()
        previous = action(header, '−', lambda: self.change(-1))
        previous.setAccessibleName('Año anterior')
        self.year = panel('heading', '')
        header.addWidget(self.year)
        following = action(header, '+', lambda: self.change(1))
        following.setAccessibleName('Año siguiente')
        today = action(header, 'Hoy', lambda: self.show_date(date.today()))
        close = action(header, '×', self.accept)
        close.setAccessibleName('Cerrar almanaque')
        for button, button_width in ((previous, 26), (following, 26), (today, 42), (close, 27)):
            button.setFixedSize(button_width, 26)
            button.setStyleSheet('QPushButton { padding: 0; border-radius: 7px; }')
            button.setAutoDefault(False)
        layout.addLayout(header)

        grid = QWidget()
        months = QGridLayout(grid)
        months.setContentsMargins(0, 0, 0, 0)
        months.setSpacing(14)
        columns = 4 if width >= 850 else 3 if width >= 620 else 2
        spanish = QLocale(QLocale.Language.Spanish)
        self.months = []
        self.accent = QColor('#ff969c' if dark else '#a22b3e')
        self.event_fill = QColor('#56333c' if dark else '#fbe6e9')
        self.setStyleSheet(self.styleSheet() + f"""
            QDialog#yearOverlay {{ background: transparent; }}
            QTableWidget {{ background: transparent; border: none; font-size: 13px;
                            selection-background-color: {'#723c46' if dark else '#a22b3e'};
                            selection-color: white; }}
            QHeaderView::section {{ background: transparent; border: none; padding: 2px; }}
        """)
        for index in range(12):
            tile = QVBoxLayout()
            tile.setSpacing(5)
            tile.addWidget(panel('heading', spanish.monthName(index + 1).capitalize()))
            table = QTableWidget(6, 7)
            table.setHorizontalHeaderLabels(('Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá', 'Do'))
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setMinimumSectionSize(15)
            table.verticalHeader().hide()
            table.verticalHeader().setDefaultSectionSize(18)
            table.verticalHeader().setMinimumSectionSize(18)
            table.setFixedHeight(6 * 18 + 23)
            table.setShowGrid(False)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.itemSelectionChanged.connect(lambda t=table: self.select_item(t))
            table.itemClicked.connect(lambda item, t=table: self.pick_day(t, item))
            tile.addWidget(table)
            self.months.append(table)
            months.addLayout(tile, index // columns, index % columns)
        layout.addWidget(grid, 1)
        self.show_date(selected)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(32, self, self.load_backdrop)
        motion = self.agenda.host is None or self.agenda.host.center.cfg.get('dock_motion', True)
        origin = self.origin.intersected(self.rect())
        if not motion or origin.isEmpty():
            return
        preview = QLabel(self.card)
        preview.setPixmap(self.agenda.grab())
        preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        preview.setGeometry(QRect(QPoint(0, 0), origin.size()))
        self.content.hide()
        self.card.setGeometry(origin)
        preview.show()
        animation = QPropertyAnimation(self.card, b'geometry', self)
        animation.setStartValue(origin)
        animation.setEndValue(self.destination)
        animation.setDuration(230)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self.content.show)
        animation.finished.connect(preview.hide)
        animation.finished.connect(preview.deleteLater)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def load_backdrop(self):
        if self.isVisible():
            self.snapshot = self.blur_work_area(self.screen())
            self.update()

    def blur_work_area(self, screen):
        from focus_alert import capture_screen, gaussian_backdrop

        image = capture_screen(screen)
        ratio = screen.devicePixelRatio()
        rect = self.work.translated(-screen.geometry().topLeft())
        crop = image.copy(round(rect.x() * ratio), round(rect.y() * ratio),
                          round(rect.width() * ratio), round(rect.height() * ratio))
        return gaussian_backdrop(crop, max(1, round(5 * ratio)))

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if not self.snapshot.isNull():
                painter.drawImage(self.rect(), self.snapshot)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 38))

    def mousePressEvent(self, event):
        if not self.card.geometry().contains(event.position().toPoint()):
            QToolTip.hideText()
            self.reject()
            event.accept()
        else:
            super().mousePressEvent(event)

    def change(self, delta):
        year = self.selected.year + delta
        if 1 <= year <= 9999:
            self.show_date(date(year, self.selected.month, 1))

    def pick_day(self, table, item):
        if item.toolTip():
            point = table.visualItemRect(item).bottomLeft()
            QToolTip.showText(table.viewport().mapToGlobal(point), item.toolTip(), table)
        else:
            QToolTip.hideText()

    def select_item(self, table):
        items = table.selectedItems()
        if items:
            day = items[0].data(Qt.ItemDataRole.UserRole)
            if day != self.selected:
                self.show_date(day)

    def show_date(self, selected):
        previous = getattr(self, 'selected', None)
        if previous is not None and previous.month != selected.month:
            self.months[previous.month - 1].selectionModel().clear()
        self.selected = selected
        self.year.setText(str(selected.year))
        if previous is None or previous.year != selected.year:
            self.refresh_dates(selected.year)
        first, _ = monthrange(selected.year, selected.month)
        row, column = divmod(first + selected.day - 1, 7)
        self.months[selected.month - 1].setCurrentCell(row, column)

    def refresh_dates(self, year):
        if self.agenda.host is not None:
            events = self.agenda.host.calendar_days(year)
        else:
            events = {day: [entry.label for entry in entries]
                      for day, entries in days_in_year(self.agenda.records.entries, year).items()}
        today = date.today()
        for month, table in enumerate(self.months, 1):
            first, count = monthrange(year, month)
            table.clearContents()
            for day in range(1, count + 1):
                value = date(year, month, day)
                names = events.get(value, ())
                row, column = divmod(first + day - 1, 7)
                item = QTableWidgetItem(str(day))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setData(Qt.ItemDataRole.AccessibleTextRole, f'{value:%d-%m-%Y}')
                if names or column >= 5 or value == today:
                    item.setForeground(QBrush(self.accent))
                if names or value == today:
                    font = table.font()
                    font.setBold(True)
                    item.setFont(font)
                if names:
                    item.setBackground(QBrush(self.event_fill))
                    details = '<br>'.join(escape(name) for name in names)
                    item.setToolTip(f'<b>{value:%d-%m-%Y}</b><br>{details}')
                table.setItem(row, column, item)


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
