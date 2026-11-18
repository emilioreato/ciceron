"""Portable paths for Cicerón's code, extension and user data."""
import os
import sys
from pathlib import Path


def application_root():
    """Return the folder containing this installation, independent of drive letter."""
    configured = os.environ.get('CICERON_HOME')
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1] / 'Aplicacion'


def data_root():
    """Keep mutable settings and packages beside the portable installation."""
    configured = os.environ.get('CICERON_DATA')
    if configured:
        return Path(configured).expanduser().resolve()
    return application_root() / 'datos'


def resolve_app_path(value):
    """Resolve a stored app path; relative values are confined to this app root."""
    path = Path(value).expanduser()
    if path.is_absolute():
        resolved = path.resolve()
        if resolved.is_file():
            return resolved
        # Older library entries may contain an absolute path from before the
        # whole Aplicacion folder was moved. Rebase only when the same file is
        # present under the current portable root.
        parts = resolved.parts
        for index in range(len(parts) - 2, -1, -1):
            if parts[index].casefold() == 'aplicacion':
                candidate = (application_root() / Path(*parts[index + 1:])).resolve()
                if candidate.is_file():
                    return candidate
                break
        return resolved
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
