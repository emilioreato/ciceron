"""An app with its own UI that uses the Cicerón package settings."""
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


def main():
    ui = tk.Tk()
    data = Path(os.environ.get('CICERON_APP_DATA', Path.home() / '.notas-ciceron'))
    settings_path = Path(os.environ.get('CICERON_APP_SETTINGS', data / 'settings.json'))
    settings = json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.is_file() else {}
    note = data / 'nota.txt'
    ui.title(settings.get('titulo', 'Notas de ejemplo'))
    ui.geometry('510x320')
    ui.attributes('-topmost', settings.get('encima', False))
    colors = ('#192636', '#e9f2fa') if settings.get('tema') == 'Noche' else ('#fffaf1', '#262122')
    editor = tk.Text(ui, wrap='word', background=colors[0], foreground=colors[1],
                     insertbackground=colors[1], font=('Segoe UI', settings.get('letra', 14)),
                     borderwidth=0, padx=12, pady=12)
    if note.is_file():
        editor.insert('1.0', note.read_text(encoding='utf-8'))
    editor.pack(fill='both', expand=True, padx=10, pady=(10, 4))
    feedback = tk.StringVar()

    def save():
        try:
            data.mkdir(parents=True, exist_ok=True)
            temporary = note.with_suffix('.tmp')
            temporary.write_text(editor.get('1.0', 'end-1c'), encoding='utf-8')
            temporary.replace(note)
        except OSError as error:
            messagebox.showerror('No se pudo guardar', str(error), parent=ui)
        else:
            feedback.set('Nota guardada')

    bar = ttk.Frame(ui, padding=(10, 0, 10, 10))
    bar.pack(fill='x')
    ttk.Button(bar, text='Guardar', command=save).pack(side='right')
    ttk.Label(bar, textvariable=feedback).pack(side='left')
    editor.focus_set()
    ui.mainloop()


if __name__ == '__main__':
    main()
