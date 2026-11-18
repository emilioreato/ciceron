"""Exercise actual Python processes and selective transfer in two profiles."""
import os
from pathlib import Path
import shutil
import struct
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app_packages import PackageError, PackageStore, atomic_json, create_package, python_command
from data_transfer import DataArchive, export_data


def make_app(root, name, version, *, hold=False):
    payload = root / name
    payload.mkdir(exist_ok=True)
    spec = dict(schema=1, id=f'local.{name}', name=name, version=version,
                entrypoint='mini.py', python='3.12', args=['un argumento'],
                data={'version': 1, 'files': ['registros/nota.txt']},
                settings=[{'id': 'tema', 'label': 'Tema', 'type': 'text', 'default': 'claro'},
                          {'id': 'local', 'label': 'Ruta local', 'type': 'text', 'default': '',
                           'portable': False}])
    atomic_json(payload / 'ciceron.json', spec)
    script = f'''
import json, os, sys, time
from pathlib import Path
from app_local import PREFIX
assert sys.argv[1] == 'un argumento'
folder = Path(os.environ['CICERON_APP_DATA'])
settings = json.loads(Path(os.environ['CICERON_APP_SETTINGS']).read_text(encoding='utf-8'))
path = folder / 'registros/nota.txt'
path.parent.mkdir(exist_ok=True)
old = path.read_text(encoding='utf-8') if path.exists() else ''
path.write_text(old + PREFIX + settings['tema'] + '\\n', encoding='utf-8')
(folder / 'ready').touch()
if {hold!r}:
    while not (folder / 'stop').exists():
        time.sleep(.03)
'''
    (payload / 'mini.py').write_text(script, encoding='utf-8')
    (payload / 'app_local.py').write_text(f'PREFIX = {version!r} + ":"', encoding='utf-8')
    archive = root / f'{name}-{version}.ciceron'
    spec, _ = create_package(payload, archive)
    return archive, spec


with TemporaryDirectory(dir=Path(__file__).resolve().parent, prefix='.datos con espacios ') as temporary:
    root = Path(temporary)
    source = PackageStore(root / 'origen/paquetes', root / 'origen/datos-apps')
    dest = PackageStore(root / 'destino/paquetes', root / 'destino/datos-apps')
    with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(root / 'Ciceron.exe')):
        assert Path(python_command('notas.pyw', os.environ)[0]).name.lower() == 'pythonw.exe'
        with patch('app_packages.shutil.which', return_value=None):
            try:
                python_command('notas.pyw', os.environ)
            except PackageError as error:
                assert '3.12' in str(error)
            else:
                raise AssertionError('Se aceptó un intérprete ausente.')
    legacy = root / 'legacy'
    legacy.mkdir()
    shutil.copyfile(Path(os.environ['SystemRoot']) / 'System32' / 'where.exe', legacy / 'Buscar.exe')
    atomic_json(legacy / 'ciceron.json', dict(schema=1, id='local.legacy', version='1.0.0', name='Legacy',
                                             entrypoint='Buscar.exe', args=['cmd.exe']))
    legacy_package = root / 'legacy.ciceron'
    create_package(legacy, legacy_package)
    assert source.install(legacy_package)[0] == 'instalada'
    assert source.launch(source.entries()[0]).wait(timeout=10) == 0
    first, spec = make_app(root, 'notas', '1.0.0', hold=True)
    second, _ = make_app(root, 'notas', '1.1.0')
    other, other_spec = make_app(root, 'diario', '1.0.0')
    source.install(first)
    source.install(other)
    source.save_settings(other_spec, {'tema': 'datos del otro origen'})
    assert source.launch(next(i for i in source.entries() if i['package']['id'] == other_spec['id'])).wait(timeout=10) == 0
    source.save_settings(spec, {'tema': 'oscuro', 'local': r'C:\Dato que no sale'})
    notes = source.data_folder(spec)
    old_process = source.launch(next(i for i in source.entries() if i['package']['id'] == spec['id']))
    archive_path = root / 'seleccion.ciceron-datos'
    try:
        # A new store has no process bookkeeping. The inherited handle still
        # stops a transfer, including after closing and reopening Cicerón.
        reopened = PackageStore(source.root, source.data)
        try:
            export_data(reopened, archive_path, [spec['id']])
        except PackageError as error:
            assert 'Cierra local.notas' in str(error)
        else:
            raise AssertionError('Se exportaron datos de una miniapp en ejecución.')
        assert not archive_path.exists()
        (notes / 'stop').touch()
        assert old_process.wait(timeout=10) == 0
    finally:
        if old_process.poll() is None:
            old_process.kill()
            old_process.wait()
    assert source.install(second)[0] == 'actualizada'
    assert source.launch(next(i for i in source.entries() if i['package']['id'] == spec['id'])).wait(timeout=10) == 0
    (notes / 'cache').mkdir()
    (notes / 'cache/ajeno.bin').write_bytes(b'cache')
    (notes / 'traza.log').write_text('log', encoding='utf-8')
    note_bytes = (notes / 'registros/nota.txt').read_bytes()
    assert note_bytes.replace(b'\r\n', b'\n') == b'1.0.0:oscuro\n1.1.0:oscuro\n'
    dest.install(second)
    dest.install(other)
    dest.save_settings(other_spec, {'tema': 'sin cambios'})
    assert dest.launch(next(i for i in dest.entries() if i['package']['id'] == other_spec['id'])).wait(timeout=10) == 0
    other_note = dest.data_folder(other_spec) / 'registros/nota.txt'
    other_before = other_note.read_bytes()

    export_data(source, archive_path, [spec['id']])
    with ZipFile(archive_path) as zipped:
        assert set(zipped.namelist()) == {'datos.json', 'apps/local.notas/registros/nota.txt'}
        member = zipped.getinfo('apps/local.notas/registros/nota.txt')
    previous = archive_path.read_bytes()
    bad = bytearray(previous)
    name_length, extra_length = struct.unpack_from('<HH', bad, member.header_offset + 26)
    bad[member.header_offset + 30 + name_length + extra_length + member.compress_size // 2] ^= 0xFF
    damaged = root / 'corrupto.ciceron-datos'
    damaged.write_bytes(bad)
    try:
        with DataArchive.open(damaged):
            raise AssertionError('Se aceptó un ZIP dañado.')
    except (PackageError, OSError):
        assert not dest.data_folder(spec).exists()

    with DataArchive.open(archive_path) as data:
        assert data.preferences is None and list(data.apps) == [spec['id']]
        assert data.apps[spec['id']]['settings'] == {'tema': 'oscuro'}
        empty_store = PackageStore(root / 'vacio/paquetes', root / 'vacio/datos-apps')
        assert 'no está instalada' in data.preview(empty_store)[0][3]
        modified = dest.records()
        modified[spec['id']]['manifest']['data']['version'] = 2
        with patch.object(dest, 'records', return_value=modified):
            assert 'no son compatibles' in data.preview(dest)[0][3]
        assert data.preview(dest) == [(spec['id'], spec['name'], False, None)]
        assert data.restore(dest, spec['id']) == ('restaurada', None)
        folder = dest.data_folder(spec)
        restored = folder / 'registros/nota.txt'
        assert restored.read_bytes() == note_bytes and dest.settings(spec)['tema'] == 'oscuro'
        assert not (folder / 'ready').exists()
        restored.write_bytes(b'cambio local')
        (folder / 'local.txt').write_bytes(b'no declarado')
        dest.save_settings(spec, {'local': r'D:\Mantener'})
        assert data.preview(dest)[0][2] and data.restore(dest, spec['id']) == ('omitida', None)
        assert restored.read_bytes() == b'cambio local'
        original_rename = Path.rename

        def fail_publish(path, target):
            if path.name == 'contenido' and target == folder:
                raise OSError('fallo al publicar')
            return original_rename(path, target)

        with patch.object(Path, 'rename', fail_publish):
            try:
                data.restore(dest, spec['id'], replace_existing=True)
            except OSError:
                assert restored.read_bytes() == b'cambio local'
            else:
                raise AssertionError('El fallo de restauración no llegó a la prueba.')
        state, backup = data.restore(dest, spec['id'], replace_existing=True)
        assert state == 'restaurada' and restored.read_bytes() == note_bytes
        assert (backup / 'registros/nota.txt').read_bytes() == b'cambio local'
        assert (folder / 'local.txt').read_bytes() == b'no declarado'
        assert dest.settings(spec)['tema'] == 'oscuro'
        assert dest.settings(spec)['local'] == r'D:\Mantener'
    assert other_note.read_bytes() == other_before and dest.settings(other_spec)['tema'] == 'sin cambios'
    export_data(source, archive_path, [], {'theme': 'dark'})
    with DataArchive.open(archive_path) as data:
        assert data.preferences == {'theme': 'dark'} and not data.apps
print('Miniapps Python y datos: actualización, aislamiento, selección, CRC, conflictos y reversión verificados.')
