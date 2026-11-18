"""Portable paths for Cicerón's code, extension and user data."""
import os
import sys
from hashlib import sha256
from pathlib import Path


def source_installation_root():
    runtime = Path(__file__).resolve().parents[1]
    if (not getattr(sys, 'frozen', False) and runtime.name == '_internal' and
            (runtime / 'entorno.txt').is_file()):
        return runtime.parent
    return None


def development_mode():
    return (not getattr(sys, 'frozen', False) and source_installation_root() is None and
            os.environ.get('CICERON_DEV', '1') == '1')


def application_root():
    """Return the folder containing this installation, independent of drive letter."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    installed = source_installation_root()
    if installed is not None:
        return installed
    configured = os.environ.get('CICERON_HOME')
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / ('.desarrollo' if development_mode() else 'Aplicacion')


def data_root():
    """Keep mutable settings and packages beside the portable installation."""
    configured = os.environ.get('CICERON_DATA')
    if configured and not getattr(sys, 'frozen', False) and source_installation_root() is None:
        return Path(configured).expanduser().resolve()
    return application_root() / 'datos'


def instance_suffix():
    if development_mode():
        key = os.path.normcase(str(data_root())).encode('utf-8')
        return '_Dev_' + sha256(key).hexdigest()[:24]
    return ''


def resolve_app_path(value):
    """Resolve a stored app path; relative values are confined to this app root."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    root = application_root().resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('La ruta relativa sale de la carpeta de Cicerón.')
    return resolved


def stored_app_path(value):
    """Store paths under the portable root relatively and external links absolutely."""
    path = resolve_app_path(value)
    root = application_root().resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def windows_appdata_root():
    """Return Windows' profile path for OS-managed shortcuts only."""
    return Path(os.environ.get('APPDATA', str(Path.home()))).expanduser()
