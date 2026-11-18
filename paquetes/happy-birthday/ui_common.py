"""Shared inputs, editing feedback, and the optional searchable birthday list."""
import csv
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from annual import long_date
from birthdays import fold, legacy_entries, merge_legacy, save, upcoming

def days_label(days):
    if not days:
        return "Hoy"
    if days == 1:
        return "Mañana"
    return f"En {days} días"


def initial_text(name):
    return "".join(part[0] for part in name.split()[:2]).upper()[:2]


class CommonUI:
    def label(self, parent, text="", *, tone="ink", size=10, bold=False, bg=None, **kw):
        return tk.Label(parent, text=text, fg=self.palette[tone], bg=bg or self.palette["sheet"],
                        font=(self.family, size, "bold" if bold else "normal"), **kw)

    def button(self, parent, text, action, *, primary=False, sheet=True, small=False, textvariable=None):
        p = self.palette
        return tk.Button(parent, text=text, textvariable=textvariable, command=action, anchor="center",
                         fg="#ffffff" if primary else p["accent"],
                         bg=p["primary"] if primary else p["sheet" if sheet else "bg"],
                         activeforeground="#ffffff" if primary else p["accent"],
                         activebackground=p["primary_hover" if primary else "hover"],
                         highlightbackground=p["sheet" if sheet else "bg"], highlightcolor=p["focus"],
                         highlightthickness=1, bd=0, relief="flat", overrelief="flat", cursor="hand2",
                         padx=9 if small else 13, pady=4 if small else 7,
                         font=(self.family, 9 if small else 10, "bold"), takefocus=True)

    def entry(self, parent, variable):
        p = self.palette
        return tk.Entry(parent, textvariable=variable, fg=p["ink"], insertbackground=p["ink"],
                        bg=p["field"], bd=6, relief="flat", highlightthickness=1,
                        highlightcolor=p["focus"], highlightbackground=p["border"],
                        selectforeground="#ffffff", selectbackground=p["primary"], font=(self.family, 11))

    def resize_list(self, _event=None):
        height = self.rows.winfo_reqheight()
        if height > self.canvas.winfo_height():
            if not self.scroll.winfo_manager():
                self.scroll.pack(side="right", fill="y", before=self.canvas)
        elif self.scroll.winfo_manager():
            self.scroll.pack_forget()
        self.canvas.itemconfigure(self.rows_window, width=self.canvas.winfo_width())
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), height))

    def wheel(self, event):
        if self.scroll.winfo_manager():
            steps = -1 if getattr(event, "num", None) == 4 else 1 if getattr(event, "num", None) == 5 else (
                -(event.delta // 120 if abs(event.delta) >= 120 else (1 if event.delta > 0 else -1)))
            self.canvas.yview_scroll(steps * 3, "units")
        return "break"

    def render_rows(self):
        if not hasattr(self, "rows") or not self.rows.winfo_exists():
            return
        p, today = self.palette, self.current_day
        for child in self.rows.winfo_children():
            child.destroy()
        query = fold(self.query.get().strip())
        ordered = upcoming(self.state.entries, today)
        if self.only_date:
            ordered = [entry for entry in ordered if entry.anniversary(self.only_date.year) == self.only_date]
        visible = [item for item in ordered if all(
            token in fold(f"{item.label} {item.short_date} {item.input_date} "
                          f"{item.day:02d}-{item.month:02d} {item.day}/{item.month} {item.day:02d}/{item.month:02d}")
            for token in query.split())]
        self.count.set(str(len(visible)) if not query else f"{len(visible)} de {len(ordered)}")
        self.first_row_button = None
        if not visible:
            empty = tk.Frame(self.rows, bg=p["sheet"], padx=20, pady=13)
            empty.pack(fill="x")
            self.label(empty, "Sin resultados" if query else "Tu lista está vacía", size=12, bold=True).pack(anchor="w")
            self.label(empty, ("Probá con otro nombre o fecha." if query else
                               "Añadí una fecha en la pantalla inicial o elegí Más → Importar CSV."),
                       tone="muted", size=9).pack(anchor="w", pady=(3, 0))
        for index, item in enumerate(visible):
            next_date = item.next_date(today)
            delay = (next_date - today).days
            age = item.upcoming_age(self.only_date or next_date)
            if age is not None and age < 0:
                age = None
            row = tk.Frame(self.rows, bg=p["sheet"], padx=12, pady=4)
            row.pack(fill="x")
            row.grid_columnconfigure(1, weight=1)
            badge = self.label(row, initial_text(item.name) or "·", tone="accent", bg=p["chip"], bold=True,
                               width=4, pady=5, size=9)
            badge.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 9))
            name = item.label
            if len(name) > 43:
                name = name[:40] + "…"
            self.label(row, name, size=10, bold=True, anchor="w").grid(row=0, column=1, sticky="w")
            note = f"{item.short_date}" + (f" · Cumple {age}" if age is not None else "")
            self.label(row, note, tone="muted", size=9, anchor="w").grid(row=1, column=1, sticky="w")
            self.label(row, days_label(delay) if not self.only_date else "", tone="accent" if delay <= 7 else "muted", size=9,
                       bg=p["chip"] if delay <= 7 else p["sheet"], bold=delay <= 7, padx=6, pady=3,
                       width=10, anchor="e").grid(row=0, column=2, rowspan=2, padx=(4, 7))
            action = self.button(row, "Editar", lambda entry=item: self.edit(entry), small=True)
            action.grid(row=0, column=3, rowspan=2)
            action.bind("<FocusIn>", lambda _, position=row: self.ensure_row(position))
            if index == 0:
                self.first_row_button = action
            delete = self.button(row, "Borrar", lambda entry=item: self.remove(entry), small=True)
            delete.grid(row=0, column=4, rowspan=2)
            delete.bind("<FocusIn>", lambda _, position=row: self.ensure_row(position))
            for widget in (row, *row.winfo_children()):
                widget.bind("<MouseWheel>", self.wheel)
                widget.bind("<Button-4>", self.wheel)
                widget.bind("<Button-5>", self.wheel)
            if index < len(visible) - 1:
                tk.Frame(self.rows, height=1, bg=p["border"]).pack(fill="x", padx=12)
        self.canvas.yview_moveto(0)

    def ensure_row(self, row):
        if not self.scroll.winfo_manager():
            return
        top = self.canvas.canvasy(0)
        viewport = self.canvas.winfo_height()
        start, end = row.winfo_y(), row.winfo_y() + row.winfo_height()
        if start < top or end > top + viewport:
            target = start if start < top else end - viewport
            self.canvas.yview_moveto(target / max(1, self.rows.winfo_height()))

    def _focus_first_row(self):
        if self.first_row_button:
            self.first_row_button.focus_set()
        return "break"

    def set_feedback(self, message, *, error=False):
        self.feedback.set(message)
        self.message.configure(fg="#9d3049" if error else self.palette["muted"])

    def commit(self, state):
        try:
            save(self.path, state)
        except OSError:
            self.set_feedback("No se pudo guardar. Revisá la carpeta de datos y volvé a intentar.", error=True)
            return False
        self.state = state
        return True

    def import_csv(self):
        selected = filedialog.askopenfilename(parent=self.root, title="Elegí el data.csv de Happy Birthday",
                                              filetypes=[("CSV de Happy Birthday", "*.csv"), ("Todos los archivos", "*")])
        if not selected:
            return
        try:
            incoming = legacy_entries(Path(selected))
            merged, skipped = merge_legacy(self.state.entries, incoming)
        except (OSError, ValueError, csv.Error) as error:
            messagebox.showerror("No se pudo importar", str(error), parent=self.root)
            return
        count = len(merged) - len(self.state.entries)
        if not count:
            detail = f" · {skipped} duplicados omitidos" if skipped else ""
            self.set_feedback("No hay cumpleaños nuevos" + detail + ".")
            return
        if not messagebox.askyesno("Importar cumpleaños",
                                   f"{count} nuevos · {skipped} duplicados omitidos\n\n"
                                   "Las fechas del CSV se traen sin año. Tus registros actuales no cambian.",
                                   parent=self.root):
            return
        if self.commit(self.state.with_entries(merged)):
            self.query.set("")
            self.set_feedback(f"Importados {count} · {skipped} duplicados omitidos.")
            self.repaint()
            self.check_reminders()

    def open_list(self, only_date=None, *, force_search=False):
        self.only_date = only_date
        p = self.palette
        if not self.list_window or not self.list_window.winfo_exists():
            win = self.list_window = tk.Toplevel(self.root)
            win.title("Cumpleaños guardados")
            win.configure(bg=p["bg"])
            win.geometry("650x490")
            win.minsize(500, 275)
            win.bind("<Escape>", lambda _: win.destroy())
            body = tk.Frame(win, bg=p["bg"], padx=17, pady=14)
            body.pack(fill="both", expand=True)
            header = tk.Frame(body, bg=p["bg"])
            header.pack(fill="x", pady=(0, 8))
            self.list_title = tk.StringVar(win, "Próximos cumpleaños")
            self.label(header, textvariable=self.list_title, size=14, bold=True, bg=p["bg"]).pack(side="left")
            self.label(header, textvariable=self.count, tone="muted", size=9, bg=p["chip"], padx=7).pack(
                side="left", padx=(8, 0))
            self.button(header, "Todos", self.open_list, sheet=False, small=True).pack(side="right")
            self.search_entry = self.entry(header, self.query)
            self.search_entry.configure(width=14)
            self.search_entry.pack(side="right", padx=5)
            self.label(header, "Buscar", tone="muted", size=9, bg=p["bg"]).pack(side="right")
            self.search_entry.bind("<Down>", lambda _: self._focus_first_row())
            list_box = tk.Frame(body, bg=p["sheet"], highlightbackground=p["border"], highlightthickness=1)
            list_box.pack(fill="both", expand=True)
            self.canvas = tk.Canvas(list_box, borderwidth=0, highlightthickness=0, bg=p["sheet"])
            self.scroll = ttk.Scrollbar(list_box, orient="vertical", command=self.canvas.yview)
            self.canvas.configure(yscrollcommand=self.scroll.set)
            self.canvas.pack(fill="both", expand=True, side="left")
            self.rows = tk.Frame(self.canvas, bg=p["sheet"])
            self.rows_window = self.canvas.create_window(0, 0, window=self.rows, anchor="nw")
            self.rows.bind("<Configure>", self.resize_list)
            self.canvas.bind("<Configure>", self.resize_list)
            for widget in (self.canvas, self.rows):
                for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    widget.bind(event, self.wheel)
        self.list_title.set(long_date(only_date) if only_date else "Próximos cumpleaños")
        self.query.set("")
        self.list_window.deiconify()
        self.list_window.lift()
        if force_search or only_date is None:
            self.search_entry.focus_set()
        self.render_rows()
