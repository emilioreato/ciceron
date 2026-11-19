"""Three inexpensive materials for the agenda's hero and controls.

V2 and V3 composite light, tint and reflections over an internal scene.
No screen capture, dependency, animation loop, or whole-window alpha.
"""
from functools import lru_cache
from math import exp, hypot, sin
import base64
import struct
import tkinter as tk
import zlib

PALETTES = {
    "V1": dict(bg="#f3f5f9", sheet="#ffffff", border="#d4dce9", field="#f7f8fb",
               hover="#e8edf6", ink="#132442", muted="#4c5d77", accent="#264b8c",
               primary="#254a8c", primary_hover="#1c3c77", focus="#426ac8", chip="#e9effb"),
    "V2": dict(bg="#eef3f9", sheet="#fafdff", border="#d3e0ed", field="#f3f7fd",
               hover="#e5eef9", ink="#152743", muted="#4a5e79", accent="#2b5095",
               primary="#2b5095", primary_hover="#223f78", focus="#5478c1", chip="#e7effc"),
    "V3": dict(bg="#e5f0f5", sheet="#f4fbfd", border="#c1dce4", field="#ebf6f9",
               hover="#dceff4", ink="#142c3e", muted="#405f73", accent="#1d536a",
               primary="#225975", primary_hover="#16475e", focus="#3686a3", chip="#dceef5"),
}


def chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))


@lru_cache(maxsize=6)
def material(style, width, height):
    """Build one tiny RGB texture for each size/style. No disk I/O."""
    rows = bytearray()
    for py in range(height):
        y = py / max(1, height - 1)
        for px in range(width):
            if not px:
                rows.append(0)  # unfiltered PNG scanline
            x = px / max(1, width - 1)
            if style == "V1":
                r, g, b = 23, 43, 76
            else:
                light = exp(-(((x - .78) * 3.0) ** 2 + ((y + .23) * 1.55) ** 2))
                pool = exp(-(((x - 1.04) * 2.7) ** 2 + ((y - .86) * 1.9) ** 2))
                arc = exp(-((y - .28 - .33 * sin((x - .44) * 4)) * (8 if style == "V3" else 4)) ** 2) * x ** 3
                if style == "V2":
                    r, g, b = 16 + 46 * light, 36 + 52 * light + 56 * pool, 67 + 83 * light + 60 * pool
                else:
                    r = 13 + 63 * light + 19 * arc
                    g = 46 + 63 * light + 93 * pool + 26 * arc
                    b = 66 + 101 * light + 83 * pool + 29 * arc
            radius = 10
            cx = max(radius - px, px - (width - 1 - radius), 0)
            cy = max(radius - py, py - (height - 1 - radius), 0)
            alpha = round(255 * max(0, min(1, radius + .5 - hypot(cx, cy))))
            rows.extend((*[min(255, int(c)) for c in (r, g, b)], alpha))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows, 2)) + chunk(b"IEND", b""))
    return base64.b64encode(png)


class Hero(tk.Canvas):
    def __init__(self, parent, font, style, status):
        super().__init__(parent, height=89, highlightthickness=0, bg=PALETTES[style]["bg"], borderwidth=0, takefocus=0)
        self.ui_font, self.style, self.status = font, style, status
        self.image = None
        self.texture_size = 0
        self.bind("<Configure>", self.paint)

    def paint(self, _event=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        scaled = (w + 1) // 2
        if scaled != self.texture_size:
            texture = tk.PhotoImage(data=material(self.style, scaled, (h + 1) // 2), format="png")
            self.image = texture.zoom(2)
            self.texture_size = scaled
        self.create_image(0, 0, image=self.image, anchor="nw")
        if self.style != "V1":
            glint = "#7892bf" if self.style == "V2" else "#77b7c8"
            self.create_line(w * .48, 2, w - 26, 2, w - 11, 3, w - 3, 14, w - 2, 29,
                             w - 2, h - 29, fill=glint, smooth=True)
        x, y = w - 65, 44
        self.draw_cake(x, y)
        self.scale("cake", x, y, .59, .59)
        self.create_text(20, 24, text="H A P P Y   B I R T H D A Y", anchor="w",
                         font=(self.ui_font, 9, "bold"), fill="#b5d7ed")
        self.create_text(19, 54, text=self.status, anchor="w",
                         font=(self.ui_font, 22, "bold"), fill="#ffffff")

    def draw_cake(self, x, y):
        last = max(self.find_all(), default=0)
        v3 = self.style == "V3"
        # Stacked scale rings evoke glass depth without moving the content.
        self.create_oval(x - 63, y - 61, x + 60, y + 59, outline="#528b9e" if v3 else "#536c9c")
        self.create_oval(x - 52, y - 51, x + 51, y + 51, fill="#286477" if v3 else "#344d7d",
                         outline="#85c0ce" if v3 else "#8197c1")
        self.create_arc(x - 50, y - 49, x + 49, y + 49, start=48, extent=110,
                        style="arc", width=2, outline="#a4d3d9" if v3 else "#a8b9db")
        self.create_oval(x - 31, y + 23, x + 31, y + 34, fill="#214052", outline="")
        self.create_polygon(x - 31, y + 16, x - 30, y - 1, x - 24, y - 8, x + 24, y - 8,
                            x + 31, y - 1, x + 31, y + 17, x + 25, y + 24, x - 25, y + 24,
                            fill="#e5b6cd", outline="", smooth=True)
        self.create_polygon(x - 30, y + 2, x - 25, y - 7, x + 24, y - 7, x + 30, y + 1,
                            x + 27, y + 9, x + 17, y + 8, x + 10, y + 13, x + 2, y + 7,
                            x - 8, y + 13, x - 16, y + 7, x - 24, y + 11,
                            fill="#fff0f2", outline="", smooth=True)
        for shift, height in ((-13, 14), (0, 19), (13, 14)):
            self.create_line(x + shift, y - 6, x + shift, y - 6 - height, width=3, fill="#d5edff")
            self.create_polygon(x + shift, y - 13 - height, x + shift - 4, y - 10 - height,
                                x + shift, y - 7 - height, x + shift + 4, y - 10 - height,
                                fill="#ffe7ae", outline="", smooth=True)
        for dx, dy, color in ((-69, -29, "#ffddbe"), (57, -39, "#a9eadf"), (67, 28, "#f0c4d6")):
            s, t = x + dx, y + dy
            self.create_polygon(s - 4, t, s, t - 5, s + 4, t, s, t + 5, fill=color, outline="")
        for shape in self.find_all():
            if shape > last:
                self.addtag_withtag("cake", shape)
