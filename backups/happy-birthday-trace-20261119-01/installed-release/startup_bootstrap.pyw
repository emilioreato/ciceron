"""Stable logon entry, copied only when startup runs through an installed Cicerón."""
from pathlib import Path
import json
import subprocess

APP_ID = "emilioreato.happy-birthday"


def main():
    folder = Path(__file__).resolve().parent
    if folder.name != APP_ID or folder.parent.name != "datos-apps" or folder.parents[1].name != "datos":
        return
    if (folder / ".inicio-desactivado").exists():
        return
    app_root = folder.parents[2]
    index = folder.parents[1] / "paquetes" / "instaladas.json"
    host = app_root / "Ciceron.exe"
    try:
        if not host.is_file() or APP_ID not in json.loads(index.read_text(encoding="utf-8")):
            return
        marker = folder / ".abrir-oculto"
        marker.touch()
        try:
            subprocess.Popen([str(host), "--lanzar-paquete", APP_ID], cwd=app_root,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError:
            marker.unlink(missing_ok=True)
            raise
    except (OSError, ValueError):
        return


if __name__ == "__main__":
    main()
