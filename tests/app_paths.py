"""Check that the portable app and data roots move with the app folder."""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import app_paths


with TemporaryDirectory() as temporary:
    root = Path(temporary) / 'Moved Folder' / 'Aplicacion'
    with patch.dict(os.environ, {'CICERON_HOME': str(root), 'CICERON_DATA': ''}, clear=False):
        assert app_paths.application_root() == root.resolve()
        assert app_paths.data_root() == root.resolve() / 'datos'

    with patch.dict(os.environ, {'CICERON_DATA': str(root / 'private-data')}, clear=False):
        assert app_paths.data_root() == (root / 'private-data').resolve()

    local_executable = root / 'tools' / 'my-app.exe'
    external_executable = Path(temporary) / 'external' / 'other-app.exe'
    with patch.dict(os.environ, {'CICERON_HOME': str(root)}, clear=False):
        assert app_paths.stored_app_path(local_executable) == 'tools/my-app.exe'
        assert app_paths.stored_app_path(external_executable) == str(external_executable.resolve())
        try:
            app_paths.resolve_app_path('../external/other-app.exe')
        except ValueError:
            pass
        else:
            raise AssertionError('Las rutas relativas no deben escapar de la carpeta de Cicerón.')
        moved = Path(temporary) / 'Moved Again' / 'Aplicacion'
        moved_executable = moved / 'tools' / 'my-app.exe'
        moved_executable.parent.mkdir(parents=True)
        moved_executable.write_bytes(b'test')
        with patch.dict(os.environ, {'CICERON_HOME': str(moved)}, clear=False):
            assert app_paths.resolve_app_path('tools/my-app.exe') == (moved / 'tools' / 'my-app.exe').resolve()
            assert app_paths.resolve_app_path(local_executable) == moved_executable.resolve()

original_executable = sys.executable
was_frozen = getattr(sys, 'frozen', None)
try:
    sys.frozen = True
    with TemporaryDirectory() as temporary:
        moved_root = Path(temporary) / 'otra-ubicacion' / 'Aplicacion'
        sys.executable = str(moved_root / 'Ciceron.exe')
        with patch.dict(os.environ, {'CICERON_HOME': '', 'CICERON_DATA': ''}, clear=False):
            assert app_paths.application_root() == moved_root.resolve()
finally:
    sys.executable = original_executable
    if was_frozen is None:
        del sys.frozen
    else:
        sys.frozen = was_frozen

print('Rutas portátiles: raíz, datos, apps vinculadas y ubicación movida verificadas.')
