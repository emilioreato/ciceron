"""Exercise the package lifecycle without touching the installed library."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app_packages import PackageError, PackageStore, atomic_json, create_package, unpack_package


with TemporaryDirectory() as temporary:
    base = Path(temporary)
    payload = base / 'payload'
    payload.mkdir()
    spec = {
        'schema': 1, 'id': 'local.prueba', 'name': 'Prueba', 'version': '1.0.0',
        'entrypoint': 'Prueba.exe', 'args': ['un argumento'], 'icon': 'icono.png',
        'dock': {'visible': True, 'wheel': 'consume'},
        'settings': [
            {'id': 'opcion', 'label': 'Una opción', 'type': 'boolean', 'default': False},
            {'id': 'notas', 'label': 'Notas', 'type': 'text', 'default': '', 'multiline': True},
        ],
    }
    (payload / 'Prueba.exe').write_bytes(b'MZ-version-1')
    (payload / 'icono.png').write_bytes(b'icono de prueba')
    (payload / 'ciceron.json').write_text(json.dumps(spec), encoding='utf-8')
    first = base / 'primera.ciceron'
    spec, digest = create_package(payload, first)
    assert unpack_package(first)[1] == digest
    store = PackageStore(base / 'store', base / 'datos')
    assert store.install(first)[0] == 'instalada'
    assert store.install(first)[0] == 'sin cambios' and len(store.entries()) == 1
    initial = store.entries()[0]
    assert Path(initial['icon']).is_file()
    installed_executable = Path(initial['path'])
    installed_executable.write_bytes(b'MZ-contenido-alterado')
    unexpected_file = Path(initial['root']) / 'archivo-ajeno.dll'
    unexpected_file.write_bytes(b'archivo no incluido en el paquete')
    assert store.install(first)[0] == 'reparada'
    assert installed_executable.read_bytes() == b'MZ-version-1' and not unexpected_file.exists()
    notes = 'Varias líneas\n' * 100
    store.save_settings(spec, {'opcion': True, 'notas': notes})
    assert store.settings(spec)['notas'] == notes
    with patch('app_packages.subprocess.Popen') as spawn:
        store.launch(initial)
        args = spawn.call_args
        assert args.args == ([str(Path(initial['path']).resolve()), 'un argumento'],)
        assert args.kwargs['cwd'] == initial['root'].resolve()
        assert args.kwargs['env']['CICERON_APP_ID'] == spec['id']
        settings_path = Path(args.kwargs['env']['CICERON_APP_SETTINGS'])
        assert json.loads(settings_path.read_text())['opcion'] is True
    store.running.clear()

    (payload / 'Prueba.exe').write_bytes(b'MZ-version-2')
    collision = base / 'colision.ciceron'
    create_package(payload, collision)
    try:
        store.install(collision)
    except PackageError:
        assert store.entries() == [initial]
    else:
        raise AssertionError('Se sobrescribió la misma versión con contenido distinto.')

    spec['version'] = '1.1.0'
    (payload / 'ciceron.json').write_text(json.dumps(spec), encoding='utf-8')
    updated = base / 'actualizada.ciceron'
    create_package(payload, updated)
    def interrupt(path, data):
        if path == store.index:
            raise OSError('simulación de fallo de escritura')
        return atomic_json(path, data)

    with patch('app_packages.atomic_json', side_effect=interrupt):
        try:
            store.install(updated)
        except OSError:
            assert store.entries() == [initial] and Path(initial['path']).is_file()
        else:
            raise AssertionError('Se activó una versión con un fallo de escritura.')
    assert store.install(updated)[0] == 'actualizada'
    assert store.entries()[0]['package']['version'] == '1.1.0'
    assert store.settings(spec)['opcion']
    assert not Path(initial['path']).exists()
    assert store.remove(spec['id']) and store.remove(spec['id'])
    assert not store.entries()
    assert settings_path.is_file()
    assert store.install(updated)[0] == 'instalada' and store.settings(spec)['opcion']
    active = store.entries()[0]
    active_executable = Path(active['path'])
    with patch('app_packages.subprocess.Popen') as spawn:
        spawn.return_value.poll.return_value = None
        store.launch(active)
        assert not store.remove(spec['id']) and Path(active['path']).is_file()
        assert store.install(updated)[0] == 'instalada' and store.entries() == [active]
        active_executable.write_bytes(b'MZ-alterado-en-ejecucion')
        try:
            store.install(updated)
        except PackageError as error:
            assert 'Cierra la aplicación' in str(error) and active_executable.read_bytes() == b'MZ-alterado-en-ejecucion'
        else:
            raise AssertionError('Se intentó reemplazar una versión dañada que seguía ejecutándose.')
        spawn.return_value.poll.return_value = 0
        assert store.install(updated)[0] == 'reparada'
        assert active_executable.read_bytes() == b'MZ-version-2'
        assert store.remove(spec['id']) and not Path(active['path']).exists()

    for bad_name in ('../escape', 'sub/../escape', 'C:/escape', 'aux.txt', 'a.txt:stream'):
        dangerous = base / 'ruta.ciceron'
        with ZipFile(dangerous, 'w') as archive:
            archive.writestr('ciceron.json', json.dumps(spec))
            archive.writestr('Prueba.exe', b'MZ')
            archive.writestr(bad_name, b'prueba')
        try:
            store.install(dangerous)
        except PackageError:
            pass
        else:
            raise AssertionError(f'Se aceptó esta ruta: {bad_name}')

print('Paquetes: idempotencia, integridad, reparación, ejecución, ajustes, actualización y desinstalación verificados.')
