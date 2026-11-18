"""Per-user Windows logon integration, kept separate from portable birthdays."""
from pathlib import Path
from tempfile import NamedTemporaryFile
import os
import subprocess
import sys
import time

APP_ID = "emilioreato.happy-birthday"
STARTUP_NAME = "Happy Birthday (Cicerón)"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
BOOTSTRAP = "happy-birthday-inicio.pyw"
MARKER = ".abrir-oculto"
OPTOUT = ".inicio-desactivado"


def installed_host(folder, environ=os.environ):
    folder = folder.resolve()
    if (environ.get("CICERON_APP_ID") != APP_ID or folder.name != APP_ID
            or len(folder.parents) < 3 or folder.parent.name != "datos-apps"
            or folder.parents[1].name != "datos"):
        return None
    host = folder.parents[2] / "Ciceron.exe"
    return host if host.is_file() else None


def command(folder, python=sys.executable):
    return subprocess.list2cmdline([str(Path(python).with_name("pythonw.exe")),
                                   "-E", "-s", "-B", str(folder / BOOTSTRAP)])


def setup(folder, *, enabled=None):
    if os.name != "nt" or not installed_host(folder):
        return None
    import winreg
    opt_out = folder / OPTOUT
    active = not opt_out.exists() if enabled is None else enabled
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        try:
            current, _ = winreg.QueryValueEx(key, STARTUP_NAME)
        except FileNotFoundError:
            current = None
        if not active:
            if current == command(folder):
                winreg.DeleteValue(key, STARTUP_NAME)
            opt_out.touch()
            return False
        launch = command(folder)
        if len(launch.encode("utf-16-le")) // 2 > 260:
            raise OSError("La ruta es demasiado larga para el inicio de sesión de Windows.")
        script = folder / BOOTSTRAP
        content = Path(__file__).with_name("startup_bootstrap.pyw").read_bytes()
        if not script.exists() or script.read_bytes() != content:
            temporary = None
            try:
                with NamedTemporaryFile(dir=folder, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(content)
                os.replace(temporary, script)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        if current != launch:
            winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, launch)
        opt_out.unlink(missing_ok=True)
    return True


def consume_background_start(folder, now=time.time):
    marker = folder / MARKER
    try:
        age = now() - marker.stat().st_mtime
        marker.unlink()
    except OSError:
        return False
    return -5 <= age <= 150
