"""Host the project-owned Happy Birthday panel without importing installed packages."""
from collections import defaultdict
from _ctypes import COMError
import importlib
from pathlib import Path
import sys
import types
import winreg

from app_identity import AppIdentity, BIRTHDAY_PACKAGE, WINDOWS_ICON_CACHE
from calendar_data import CalendarEvent, read_events
from start_menu import set_window_identity


APP_ID = BIRTHDAY_PACKAGE


def agenda_module():
    folder = Path(__file__).resolve().parents[1] / 'paquetes' / 'happy-birthday'
    if not (folder / 'qt_agenda.py').is_file():
        return None
    name = '_ciceron_builtin_birthday'
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(folder)]
        sys.modules[name] = package
    return importlib.import_module(name + '.qt_agenda')


class BirthdayHost:
    def __init__(self, center, item):
        self.center = center
        self.item = item
        self.identity = AppIdentity.from_entry(item)
        self.agenda = None
        self.notification_tray = None

    def update_entry(self, item):
        if item == self.item:
            return
        self.item = item
        identity = AppIdentity.from_entry(item)
        if (identity.name, identity.icon) != (self.identity.name, self.identity.icon):
            self.close_notification()
        self.identity = identity

    def prepare(self):
        if self.agenda is not None:
            return self.agenda
        module = agenda_module()
        if module is None:
            return None
        data = self.center.packages.data_folder(self.item['package'])
        path = data / 'cumpleanos.json'
        with self.center.packages.data_lease(APP_ID, exclusive=True):
            self.agenda = module.Agenda(path, module.load(path), self)
        self.agenda.check_reminders()
        return self.agenda

    def show(self, title, body, acknowledged):
        if self.agenda is None:
            return False
        if self.notification_tray is None:
            module = agenda_module()
            cache = self.center.packages.data.parent / WINDOWS_ICON_CACHE
            try:
                icon = self.identity.windows_icon(cache)
            except OSError:
                icon = None
            tray = module.Tray(self.agenda, self.agenda.path.parent, icon or module.HERE / 'icono.ico',
                               self.open_panel, None, hidden=True)
            try:
                if not tray.available:
                    tray.close()
                    return False
                set_window_identity(tray.hwnd, self.identity.windows_id)
            except (OSError, COMError):
                tray.close()
                return False
            self.notification_tray = tray
        heading, body = self.identity.notification_text(title, body)
        return self.notification_tray.show(heading, body, acknowledged)

    def open_panel(self):
        dock = self.center.dock
        if dock is not None and dock.panel is not None and dock.panel.content is self.agenda:
            dock.panel.raise_()
            dock.panel.activateWindow()
        elif dock is None or dock.pending_panel is None or dock.pending_panel[0] != APP_ID:
            self.center.launch(self.item)

    def calendar_days(self, year):
        data = self.center.packages.data.parent
        events = read_events(data / 'calendario', year)
        events.extend(CalendarEvent(APP_ID, birthday.id, birthday.anniversary(year), birthday.label)
                      for birthday in self.agenda.records.entries)
        days = defaultdict(list)
        for event in sorted(events, key=lambda item: (item.day, item.title.casefold(), item.source, item.uid)):
            days[event.day].append(event.title)
        return days

    def close_notification(self):
        if self.notification_tray is not None:
            tray = self.notification_tray
            self.notification_tray = None
            try:
                set_window_identity(tray.hwnd, None)
            except (OSError, COMError):
                pass
            finally:
                tray.close()

    def close(self):
        self.close_notification()
        if self.agenda is not None:
            dock = self.center.dock
            if dock is not None and dock.panel is not None and dock.panel.content is self.agenda:
                dock.panel.close()
            self.agenda.reminders.stop()
            self.agenda.deleteLater()
            self.agenda = None


def remove_legacy_startup(data):
    """Retire the separate logon job only if it points to this app's bootstrap."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run',
                        0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        name = 'Happy Birthday (Cicerón)'
        value, _ = winreg.QueryValueEx(key, name)
        if isinstance(value, str) and value.rstrip('"').endswith(str(data / 'happy-birthday-inicio.pyw')):
            winreg.DeleteValue(key, name)
