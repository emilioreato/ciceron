"""Happy Birthday miniapp for Cicerón. Launches without a console on Windows."""
import errno
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
import time
import tkinter as tk
from tkinter import font, messagebox

from birthdays import (Birthday, STYLES, clean_name, load, parse_date, pending_today,
                       record_notifications, same_person)
from annual import YearWindow
from ui_common import CommonUI
import startup
from glass import Hero, PALETTES
from windows_tray import Tray, activate_existing

HERE = Path(__file__).resolve().parent
CHECK_MS = 45_000
RETRY_SECONDS = 240


def data_folder():
    if value := os.environ.get("CICERON_APP_DATA"):
        return Path(value).resolve()
    if os.name == "nt":
        return (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                / "Happy Birthday" / "datos").resolve()
    return (Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            / "happy-birthday").resolve()


@contextmanager
def instance(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".instancia.lock").open("a+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            yield False
            return
        yield True


class Agenda(CommonUI):
    def __init__(self, root, file_path, state, today=date.today):
        self.root, self.path, self.state, self.today = root, file_path, state, today
        self.names, self.dates, self.query, self.feedback, self.count = (tk.StringVar(root) for _ in range(5))
        self.current_day = self.today()
        self.editing = self.last_unnamed = self.only_date = None
        self.named = False
        self.list_window = self.year_window = None
        self.alert_attempts = {}
        self.alert_receipts = {}
        self.startup_enabled = None
        self.timer = None
        self.palette = PALETTES[state.style]
        self.family = next((face for face in ("Segoe UI", "Arial", "Liberation Sans", "DejaVu Sans")
                            if face in set(font.families(root))), "TkDefaultFont")
        root.title("Happy Birthday")
        root.geometry("528x270")
        root.minsize(452, 270)
        root.resizable(True, False)
        self.icon = tk.PhotoImage(file=HERE / "icono.png")
        root.iconphoto(True, self.icon)
        if os.name == "nt":
            try:
                root.iconbitmap(default=str(HERE / "icono.ico"))
            except tk.TclError:
                pass
        self.tray = Tray(root, file_path.parent, HERE / "icono.ico", self.restore, self.close,
                         self.check_reminders, self.open_today)
        root.protocol("WM_DELETE_WINDOW", self.background)
        root.bind("<Control-n>", lambda _: self.cancel())
        root.bind("<Control-f>", lambda _: self.open_list(force_search=True))
        root.bind("<Control-l>", lambda _: self.open_calendar())
        root.bind("<Escape>", lambda _: self.cancel() if self.editing or self.named else None)
        self.query.trace_add("write", lambda *_: self.render_rows())
        self.build()
        self.date_entry.focus_set()
        self.timer = root.after(950, self.tick)

    def build(self):
        p = self.palette = PALETTES[self.state.style]
        if hasattr(self, "panel"):
            self.panel.destroy()
        self.root.configure(bg=p["bg"])
        panel = self.panel = tk.Frame(self.root, bg=p["bg"], padx=18, pady=12)
        panel.pack(fill="both", expand=True)
        tools = tk.Frame(panel, bg=p["bg"])
        tools.pack(fill="x", pady=(0, 6))
        self.label(tools, "AGENDA PERSONAL", tone="muted", size=8, bold=True, bg=p["bg"]).pack(side="left")
        self.more_button = self.button(tools, "Más  ▾", self.more_menu, sheet=False, small=True)
        self.more_button.pack(side="right")
        self.calendar_button = self.button(tools, "Almanaque", self.open_calendar, sheet=False, small=True)
        self.calendar_button.pack(side="right", padx=(0, 5))

        self.hero = Hero(panel, self.family, self.state.style, "Nuevo cumpleaños")
        self.hero.pack(fill="x")
        form = tk.Frame(panel, bg=p["bg"])
        form.pack(fill="x", pady=(10, 0))
        form.grid_columnconfigure(0, weight=1)
        self.label(form, "Fecha", bold=True, size=10, bg=p["bg"]).grid(row=0, column=0, sticky="w")
        self.label(form, "Ej. 8-9-2004  ·  El año es opcional", tone="muted", size=9, bg=p["bg"]).grid(
            row=0, column=1, columnspan=2, sticky="e", pady=(0, 2))
        self.date_entry = self.entry(form, self.dates)
        self.date_entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 9))
        self.form_action = tk.StringVar(self.root, "Añadir")
        self.add_button = self.button(form, "", self.submit, textvariable=self.form_action, primary=True, sheet=False)
        self.add_button.grid(row=1, column=2, sticky="ew")
        self.date_entry.bind("<Return>", lambda _: self.submit())
        self.date_entry.bind("<Shift-Return>", self.add_name_shortcut)
        self.name_toggle = self.button(form, "+ Nombre (opcional)", self.add_name_shortcut, sheet=False, small=True)
        self.name_toggle.grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.cancel_button = self.button(form, "Cancelar", self.cancel, sheet=False, small=True)
        self.cancel_button.grid(row=2, column=2, sticky="e")
        self.name_label = self.label(form, "Nombre opcional", bold=True, size=9, bg=p["bg"])
        self.name_label.grid(row=2, column=0, sticky="w", pady=(7, 2))
        self.name_entry = self.entry(form, self.names)
        self.name_entry.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.name_entry.bind("<Return>", lambda _: self.submit())

        footer = tk.Frame(panel, bg=p["bg"])
        footer.pack(fill="x", pady=(4, 0))
        self.message = self.label(footer, tone="muted", size=9, bg=p["bg"], textvariable=self.feedback,
                                  anchor="w", justify="left")
        self.message.pack(side="left", fill="x", expand=True)
        self.name_last_button = self.button(footer, "Poner nombre", self.name_last, sheet=False, small=True)
        footer.bind("<Configure>", lambda event: self.message.configure(
            wraplength=max(130, event.width - (124 if self.last_unnamed else 0))))
        self.update_form(resize=False)

    def update_form(self, *, resize=True):
        self.hero.status = "Editar cumpleaños" if self.editing else "Nuevo cumpleaños"
        self.hero.paint()
        self.form_action.set("Guardar" if self.editing else "Añadir")
        if self.named:
            self.name_toggle.grid_remove()
            for w in (self.name_label, self.name_entry, self.cancel_button):
                w.grid()
        else:
            self.name_toggle.grid()
            for w in (self.name_label, self.name_entry, self.cancel_button):
                w.grid_remove()
        if self.last_unnamed:
            self.name_last_button.pack(side="right")
        else:
            self.name_last_button.pack_forget()
        if resize:
            self.root.geometry(f"{max(452, self.root.winfo_width())}x{311 if self.named else 270}")
        for field in (self.date_entry, self.name_entry):
            field.configure(highlightbackground=self.palette["border"], highlightcolor=self.palette["focus"])

    def add_name_shortcut(self, _event=None):
        self.named = True
        self.update_form()
        self.name_entry.focus_set()
        return "break"

    def submit(self):
        self.update_form()
        try:
            parts = parse_date(self.dates.get(), self.today())
        except ValueError as error:
            self.set_feedback(str(error), error=True)
            self.date_entry.configure(highlightbackground="#b0445f", highlightcolor="#b0445f")
            self.date_entry.focus_set()
            return "break"
        try:
            name = clean_name(self.names.get(), optional=True)
        except ValueError as error:
            self.set_feedback(str(error), error=True)
            self.name_entry.focus_set()
            return "break"
        item = Birthday.new(name, parts) if not self.editing else Birthday(self.editing, name, *parts)
        if any(same_person(item, old) for old in self.state.entries if old.id != item.id):
            self.set_feedback("Ya guardaste ese cumpleaños.", error=True)
            return "break"
        rows = [old for old in self.state.entries if old.id != item.id] + [item]
        editing = bool(self.editing)
        if self.commit(self.state.with_entries(rows)):
            self.last_unnamed = item.id if not item.name else None
            self.cancel(clear_feedback=False)
            self.set_feedback(f"{'Actualizado' if editing else 'Guardado'} · {item.short_date}")
            self.repaint()
            self.check_reminders()
        return "break"

    def cancel(self, *, clear_feedback=True):
        self.editing = None
        self.named = False
        self.names.set("")
        self.dates.set("")
        self.update_form()
        self.date_entry.focus_set()
        if clear_feedback:
            self.set_feedback("")

    def name_last(self):
        item = next((i for i in self.state.entries if i.id == self.last_unnamed), None)
        if item:
            self.edit(item)

    def second_windows(self):
        for win in (self.list_window, self.year_window.window if self.year_window else None):
            if win and win.winfo_exists():
                yield win

    def edit(self, item):
        self.editing = item.id
        self.named = True
        self.last_unnamed = None
        self.names.set(item.name)
        self.dates.set(item.input_date)
        for win in self.second_windows():
            win.withdraw()
        self.update_form()
        self.set_feedback("")
        self.restore()
        self.name_entry.focus_set()
        self.name_entry.selection_range(0, "end")

    def remove(self, item):
        parent = self.list_window if self.list_window and self.list_window.winfo_exists() else self.root
        if not messagebox.askyesno("Borrar cumpleaños", f"¿Borrar {item.label} del {item.short_date}?",
                                   parent=parent, default="no"):
            return
        if self.commit(self.state.with_entries(i for i in self.state.entries if i.id != item.id)):
            if self.last_unnamed == item.id:
                self.last_unnamed = None
                self.update_form()
            if self.editing == item.id:
                self.cancel()
            self.set_feedback("Cumpleaños borrado.")
            self.repaint()

    def open_calendar(self):
        if not self.year_window or not self.year_window.window.winfo_exists():
            self.year_window = YearWindow(self)
        self.year_window.window.deiconify()
        self.year_window.window.lift()
        self.year_window.refresh()

    def open_today(self):
        self.restore()
        self.open_calendar()
        self.year_window.go_today()

    def repaint(self):
        self.render_rows()
        if self.year_window and self.year_window.window.winfo_exists():
            self.year_window.refresh()

    def more_menu(self):
        if hasattr(self, "menu") and self.menu.winfo_exists():
            self.menu.destroy()
        menu = self.menu = tk.Menu(self.more_button, tearoff=False, font=(self.family, 10))
        menu.add_command(label="Cumpleaños guardados  ·  Ctrl+F", command=self.open_list)
        menu.add_command(label="Importar CSV anterior…", command=self.import_csv)
        submenu = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label="Apariencia", menu=submenu)
        self.menu_style = tk.StringVar(menu, self.state.style)
        for style, label in zip(STYLES, ("V1 · Sólido", "V2 · Vidrio suave", "V3 · Vidrio luminoso")):
            submenu.add_radiobutton(label=label, value=style, variable=self.menu_style,
                                    command=lambda current=style: self.root.after_idle(self.change_style, current))
        if os.name == "nt":
            menu.add_separator()
            if startup.installed_host(self.path.parent):
                menu.add_command(label=("Desactivar inicio con Windows" if self.startup_enabled
                                       else "Activar inicio con Windows"), command=self.toggle_startup)
            menu.add_command(label="Probar aviso de Windows", command=self.test_notice)
            menu.add_command(label="Ocultar y mantener avisos", command=self.background)
        menu.add_separator()
        menu.add_command(label="Salir y pausar avisos" if os.name == "nt" else "Salir", command=self.close)
        menu.tk_popup(self.more_button.winfo_rootx(), self.more_button.winfo_rooty() + self.more_button.winfo_height())

    def change_style(self, style):
        if style != self.state.style and self.commit(replace(self.state, style=style)):
            for win in self.second_windows():
                win.destroy()
            self.build()
            self.date_entry.focus_set()

    def setup_startup(self, enable=None):
        try:
            self.startup_enabled = startup.setup(self.path.parent, enabled=enable)
        except OSError as error:
            self.set_feedback(f"No se pudo configurar el inicio con Windows. {error}", error=True)
            return False
        return self.startup_enabled is not None

    def toggle_startup(self):
        if self.setup_startup(not self.startup_enabled):
            self.set_feedback("Inicio con Windows " + ("activado." if self.startup_enabled else "desactivado."))

    def test_notice(self):
        if self.tray.show("Happy Birthday", "Los avisos de cumpleaños usan esta notificación.",
                          lambda: self.set_feedback("Windows mostró el aviso de prueba.")):
            self.set_feedback("Aviso de prueba enviado a Windows.")
        else:
            self.set_feedback("Windows no acepta el aviso ahora. Probá en un momento.", error=True)

    def tick(self):
        self.timer = None
        self.check_reminders()
        self.timer = self.root.after(CHECK_MS, self.tick)

    def check_reminders(self):
        now = self.today()
        if now != self.current_day:
            self.current_day = now
            self.repaint()
        for day, entries in list(self.alert_receipts.items()):
            if self.commit(record_notifications(self.state, day, entries)):
                del self.alert_receipts[day]
        if now in self.alert_receipts:
            return
        due = pending_today(self.state, now)
        if not due:
            return
        key = (now, tuple(sorted(item.id for item in due)))
        clock = time.monotonic()
        if clock - self.alert_attempts.get(key, float("-inf")) < RETRY_SECONDS:
            return
        title = "Hoy hay un cumpleaños" if len(due) == 1 else f"Hoy hay {len(due)} cumpleaños"
        names = ", ".join(item.label if item.name else f"Fecha sin nombre · {item.short_date}" for item in due[:5])
        if len(due) > 5:
            names += f" y {len(due)-5} más"
        if self.tray.show(title, names, lambda: self.confirm_notice(now, due)):
            self.alert_attempts = {k: t for k, t in self.alert_attempts.items() if clock-t < RETRY_SECONDS}
            self.alert_attempts[key] = clock

    def confirm_notice(self, day, entries):
        if not self.commit(record_notifications(self.state, day, entries)):
            self.alert_receipts[day] = entries

    def background(self):
        if os.name != "nt":
            self.close()
        elif self.tray.ensure():
            for win in self.second_windows():
                win.withdraw()
            self.root.withdraw()
        else:
            self.root.iconify()

    def restore(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        (self.name_entry if self.editing else self.date_entry).focus_set()
        self.check_reminders()

    def close(self):
        if self.timer:
            self.root.after_cancel(self.timer)
        self.tray.close()
        self.root.destroy()


def main():
    folder = data_folder()
    path = folder / "cumpleanos.json"
    try:
        hidden = startup.consume_background_start(folder) if os.name == "nt" else False
        with instance(folder) as own:
            if not own:
                if not hidden:
                    for _ in range(10):
                        if activate_existing(folder) or os.name != "nt":
                            break
                        time.sleep(.1)
                return
            root = tk.Tk()
            root.withdraw()
            try:
                state = load(path)
            except (OSError, ValueError):
                if not hidden:
                    messagebox.showerror("No se pudo leer la agenda",
                                         f"No se modificó tu archivo. Revisá o recuperá una copia de:\n{path}",
                                         parent=root)
                root.destroy()
                return
            agenda = Agenda(root, path, state)
            root.after(250, agenda.setup_startup)
            if hidden:
                def keep_tray(attempt=0):
                    if not agenda.tray.ensure():
                        if attempt < 20:
                            root.after(1500, keep_tray, attempt+1)
                        else:
                            root.deiconify()
                            agenda.set_feedback("La bandeja de Windows no está disponible.", error=True)
                root.after(100, keep_tray)
            else:
                root.deiconify()
                root.after_idle(agenda.date_entry.focus_set)
            root.mainloop()
    except OSError as error:
        messagebox.showerror("No se pudo abrir Happy Birthday", str(error))


if __name__ == "__main__":
    main()
