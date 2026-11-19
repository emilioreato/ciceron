"""Perpetual, Monday-first year view using the same occurrence dates as reminders."""
import calendar
from datetime import date, timedelta
import tkinter as tk

from birthdays import days_in_year

MONTHS = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
          "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")
WEEK = ("L", "M", "X", "J", "V", "S", "D")
WEEK_FULL = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def long_date(day):
    return f"{WEEK_FULL[day.weekday()].capitalize()} {day.day} de {MONTHS[day.month-1].lower()}"


def rounded(canvas, x, y, x2, y2, radius=11, **options):
    r = radius
    return canvas.create_polygon(x+r, y, x2-r, y, x2, y, x2, y+r,
                                 x2, y2-r, x2, y2, x2-r, y2, x+r, y2,
                                 x, y2, x, y2-r, x, y+r, x, y,
                                 smooth=True, splinesteps=16, **options)


class YearWindow:
    def __init__(self, agenda):
        self.app = agenda
        self.today = agenda.today()
        self.year = self.today.year
        self.selected = self.today
        self.following_today = True
        self.days = {}
        self.window = tk.Toplevel(agenda.root)
        win = self.window
        win.title("Almanaque · Happy Birthday")
        p = agenda.palette
        win.configure(bg=p["bg"])
        screen = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{min(1000, screen[0]-32)}x{min(750, screen[1]-85)}")
        win.minsize(min(760, screen[0]-32), min(550, screen[1]-85))
        win.bind("<Escape>", lambda _: win.destroy())
        body = tk.Frame(win, bg=p["bg"], padx=21, pady=15)
        body.pack(fill="both", expand=True)
        top = tk.Frame(body, bg=p["bg"])
        top.pack(fill="x", pady=(0, 12))
        left = tk.Frame(top, bg=p["bg"])
        left.pack(side="left")
        agenda.label(left, "ALMANAQUE", tone="muted", size=9, bold=True, bg=p["bg"]).pack(anchor="w")
        self.title = tk.StringVar(win)
        agenda.label(left, textvariable=self.title, size=27, bold=True, bg=p["bg"]).pack(anchor="w")
        controls = tk.Frame(top, bg=p["bg"])
        controls.pack(side="right")
        for caption, action in (("‹  Anterior", lambda: self.change_year(-1)), ("Hoy", self.go_today),
                                ("Siguiente  ›", lambda: self.change_year(1))):
            agenda.button(controls, caption, action, sheet=False, small=True).pack(side="left", padx=(4, 0))
        self.canvas = tk.Canvas(body, bg=p["bg"], bd=0, highlightthickness=1,
                                highlightbackground=p["bg"], highlightcolor=p["focus"], takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.paint)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Motion>", self.pointer)
        for key, shift in (("Left", -1), ("Right", 1), ("Up", -7), ("Down", 7)):
            self.canvas.bind(f"<{key}>", lambda _, days=shift: self.move_selection(days))
        self.canvas.bind("<Home>", lambda _: self.go_today())
        self.legend = tk.StringVar(win)
        agenda.label(body, textvariable=self.legend, tone="muted", size=9, bg=p["bg"], anchor="w").pack(
            fill="x", pady=(7, 4))

        detail = tk.Frame(body, bg=p["sheet"], highlightbackground=p["border"], highlightthickness=1, padx=12, pady=6)
        detail.pack(fill="x")
        self.detail = tk.StringVar(win)
        self.detail_label = agenda.label(detail, textvariable=self.detail, bg=p["sheet"], anchor="w",
                                          justify="left", bold=True, size=10)
        self.detail_label.pack(side="left", fill="x", expand=True)
        self.detail_button = agenda.button(detail, "Ver en lista", self.open_details, small=True)
        self.detail_button.pack(side="right", padx=(5, 0))
        detail.bind("<Configure>", lambda e: self.detail_label.configure(wraplength=max(120, e.width-133)))
        self.hitboxes = []
        self.refresh()
        self.canvas.focus_set()

    def change_year(self, delta):
        self.following_today = False
        self.year = max(1, min(9999, self.year + delta))
        self.selected = date(self.year, self.selected.month,
                             min(self.selected.day, calendar.monthrange(self.year, self.selected.month)[1]))
        self.refresh()

    def go_today(self):
        self.following_today = True
        self.today = self.app.today()
        self.selected = self.today
        self.year = self.today.year
        self.refresh()
        self.canvas.focus_set()
        return "break"

    def move_selection(self, shift):
        self.following_today = False
        try:
            self.selected += timedelta(days=shift)
        except OverflowError:
            return "break"
        self.year = self.selected.year
        self.refresh()
        return "break"

    def refresh(self):
        self.today = self.app.today()
        if self.following_today:
            self.selected, self.year = self.today, self.today.year
        self.days = days_in_year(self.app.state.entries, self.year)
        self.month_counts = [0] * 13
        for day, entries in self.days.items():
            self.month_counts[day.month] += len(entries)
        self.title.set(str(self.year))
        count = sum(len(v) for v in self.days.values())
        self.legend.set(f"Hoy · {long_date(self.today)} de {self.today.year}     |     "
                        f"● Cumpleaños ({count})     ·     Marcá un día para ver quién cumple")
        self.show_detail()
        self.paint()

    def show_detail(self):
        due = self.days.get(self.selected, ())
        names = ", ".join(item.label for item in due[:3])
        if len(names) > 100:
            names = names[:97] + "…"
        if len(due) > 3:
            names += f" y {len(due)-3} más"
        self.detail.set(f"{long_date(self.selected)}  ·  {names or 'Sin cumpleaños'}")
        self.detail_button.configure(state="normal" if due else "disabled")

    def open_details(self):
        self.app.open_list(only_date=self.selected)

    def day_at(self, event):
        return next((day for x, y, x2, y2, day in self.hitboxes if x <= event.x < x2 and y <= event.y < y2), None)

    def pointer(self, event):
        self.canvas.configure(cursor="hand2" if self.day_at(event) else "")

    def click(self, event):
        if day := self.day_at(event):
            self.following_today = day == self.today
            self.selected = day
            self.show_detail()
            self.paint()
            self.canvas.focus_set()

    def paint(self, _event=None):
        c, p = self.canvas, self.app.palette
        w, h = c.winfo_width(), c.winfo_height()
        if w < 320 or h < 285:
            return
        c.delete("all")
        self.hitboxes = []
        gap = 8
        mw, mh = (w - 3*gap - 4)/4, (h - 2*gap - 4)/3
        ink = self.app.family
        for m, label in enumerate(MONTHS, 1):
            row, col = divmod(m-1, 4)
            x, y = 2 + col * (mw+gap), 2 + row * (mh+gap)
            current = (self.year, m) == (self.today.year, self.today.month)
            rounded(c, x, y, x+mw, y+mh, 12, fill=p["sheet"], outline=p["focus"] if current else p["border"])
            c.create_text(x+11, y+14, anchor="w", text=label, fill=p["ink"], font=(ink, 10, "bold"))
            if n := self.month_counts[m]:
                mark = f"{n}"
                right = x + mw - 9
                rounded(c, right-24, y+7, right, y+21, 4, fill=p["chip"], outline="")
                c.create_text(right-12, y+14, text=mark, fill=p["accent"], font=(ink, 8, "bold"))
            slotw, sloth = (mw-16)/7, (mh-31)/7
            for day_index, symbol in enumerate(WEEK):
                c.create_text(x+8+(day_index+.5)*slotw, y+28+sloth/2, text=symbol, fill=p["muted"],
                              font=(ink, 7, "bold"))
            first, count = calendar.monthrange(self.year, m)
            for num in range(1, count+1):
                week, day_index = divmod(first+num-1, 7)
                value = date(self.year, m, num)
                dx, dy = x+8+(day_index+.5)*slotw, y+28+(week+1.5)*sloth
                due = self.days.get(value)
                today, selected = value == self.today, value == self.selected
                self.hitboxes.append((dx-slotw/2, dy-sloth/2, dx+slotw/2, dy+sloth/2, value))
                width, height = min(10, slotw * .45), max(4, min(9, sloth * .48))
                if due or today or selected:
                    fill = p["primary"] if today else p["chip"] if due else p["sheet"]
                    rounded(c, dx-width, dy-height, dx+width, dy+height, min(5, height-1),
                            fill=fill, outline=p["focus"] if selected or today else "")
                c.create_text(dx, dy, text=str(num), fill="#ffffff" if today else p["accent"] if due else p["ink"],
                              font=(ink, 8 if h > 425 else 7, "bold" if due or today else "normal"))
                if due and height >= 6:
                    mark = "#ffffff" if today else p["accent"]
                    c.create_oval(dx+width-4, dy-height+1, dx+width-1, dy-height+4, fill=mark, outline="")
