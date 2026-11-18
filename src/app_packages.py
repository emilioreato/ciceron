"""Contract, storage and launch of versioned Cicerón apps on Windows."""
from contextlib import contextmanager
import ctypes
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
import unicodedata
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED


class PackageError(ValueError):
    pass


MANIFEST = 'ciceron.json'
PACKAGE_EXT = '.ciceron'
APP_ID = re.compile(r'[a-z][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+', re.ASCII)
VERSION = re.compile(r'(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}', re.ASCII)
DIRNAME = re.compile(r'[0-9a-f]{64}')
RESERVED = re.compile(r'con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³]|conin\$|conout\$', re.I)
SIZE_LIMIT = 1024 ** 3
PYTHON_VERSION = '3.12'
# Windows' process creation API can reject a working directory of MAX_PATH length.
PYTHON_LONG_CWD = """
import os
import runpy
import sys

folder, entry, *args = sys.argv[1:]
os.chdir(folder)
sys.path[0] = folder
sys.argv[:] = [entry, *args]
runpy.run_path(entry, run_name='__main__')
"""

_kernel = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                               ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
_kernel.CreateFileW.restype = ctypes.c_void_p
_kernel.CloseHandle.argtypes = [ctypes.c_void_p]


def python_entrypoint(entry):
    return Path(entry).suffix.lower() in ('.py', '.pyw')


def python_command(entry, environment):
    try:
        if not getattr(sys, 'frozen', False) and sys.version_info[:2] == (3, 12):
            interpreter = Path(sys.executable)
        else:
            launcher = shutil.which('py.exe')
            if launcher is None:
                raise FileNotFoundError('py.exe')
            result = subprocess.run(
                [launcher, '-3.12', '-I', '-c',
                 'import sys; assert sys.version_info[:2] == (3, 12); sys.stdout.buffer.write(sys.executable.encode("utf-8"))'],
                env=environment, capture_output=True, check=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW)
            interpreter = Path(result.stdout.decode('utf-8'))
        if Path(entry).suffix.lower() == '.pyw':
            interpreter = interpreter.with_name('pythonw.exe')
        if not interpreter.is_absolute() or not interpreter.is_file():
            raise FileNotFoundError(interpreter)
    except (OSError, subprocess.SubprocessError) as error:
        raise PackageError('Esta miniapp necesita Python 3.12 para Windows y su lanzador py. '
                           'Comprueba que «py -3.12 --version» funcione y vuelve a abrirla.') from error
    return [str(interpreter), '-E', '-s', '-B', str(entry)]


def portable_data_path(name):
    if not isinstance(name, str) or len(name) > 512:
        raise PackageError('Cada ruta de datos debe ser relativa y tener hasta 512 caracteres.')
    path = package_path(name)
    parts = path.casefold().split('/')
    if ('settings.json' in parts or
            set(parts) & {'cache', 'caches', '.cache', '__pycache__', 'logs', 'tmp', 'temp'} or
            Path(parts[-1]).suffix in {'.exe', '.dll', '.pyd', '.py', '.pyw', '.pyc', '.bat', '.cmd',
                                       '.ps1', '.msi', '.com', '.scr', '.lnk', '.reg', '.log', '.tmp',
                                       '.js', '.vbs', '.jar', '.sqlite-wal', '.sqlite-shm'}):
        raise PackageError(f'Este archivo no puede declararse como dato portable: {name}')
    return path


def data_contract(value):
    object_keys(value, 'version files', 'datos portables')
    version, files = value.get('version'), value.get('files')
    if type(version) is not int or not 1 <= version <= 1000000:
        raise PackageError('La versión de los datos debe ser un entero positivo.')
    if not isinstance(files, list) or len(files) > 256:
        raise PackageError('Declara hasta 256 archivos de datos portables.')
    seen = set()
    for name in files:
        key = portable_data_path(name).casefold()
        if key in seen or any(key.startswith(other + '/') or other.startswith(key + '/') for other in seen):
            raise PackageError('Las rutas de datos declaradas se solapan.')
        seen.add(key)
    return value


def package_path(name):
    parts = name.split('/')
    if any(not part or part in ('.', '..') or len(part) > 128 or part.endswith(('.', ' '))
           or re.search(r'[\\:<>"|?*\x00-\x1f]', part)
           or RESERVED.fullmatch(part.split('.')[0].rstrip()) for part in parts):
        raise PackageError(f'Ruta inválida en el paquete: {name!r}')
    return name


def object_keys(data, keys, label):
    if not isinstance(data, dict) or data.keys() - set(keys.split()):
        raise PackageError(f'Campos inválidos en {label}.')


def short_text(value, limit):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit and '\0' not in value


def fold_search(text):
    return ''.join(char for char in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(char))


def app_tags(values):
    if not isinstance(values, list) or len(values) > 12 or not all(short_text(tag, 32) for tag in values):
        raise PackageError('Usa hasta 12 etiquetas de 32 caracteres como máximo.')
    tags = {}
    for value in values:
        tag = ' '.join(value.split())
        tags.setdefault(fold_search(tag), tag)
    return list(tags.values())


def valid_setting(spec, value):
    kind = spec['type']
    if kind == 'boolean':
        return type(value) is bool
    if kind == 'integer':
        return type(value) is int and spec['min'] <= value <= spec['max']
    if kind == 'choice':
        return isinstance(value, str) and value in spec['choices']
    return isinstance(value, str) and len(value) <= text_setting_limit(spec) and '\0' not in value


def text_setting_limit(spec):
    return 8192 if spec.get('multiline', False) else 512


def manifest(data):
    object_keys(data, 'schema id version name description entrypoint args icon dock settings tags python data', MANIFEST)
    if type(data.get('schema')) is not int or data['schema'] != 1:
        raise PackageError('Se requiere schema 1.')
    if not short_text(data.get('id'), 80) or not APP_ID.fullmatch(data['id']):
        raise PackageError('El id debe tener un formato como local.notas.')
    package_path(data['id'])
    if not short_text(data.get('version'), 20) or not VERSION.fullmatch(data['version']):
        raise PackageError('La versión debe tener tres números, como 1.0.0.')
    if not short_text(data.get('name'), 80):
        raise PackageError('El nombre debe tener entre 1 y 80 caracteres.')
    description = data.get('description', '')
    if description != '' and not short_text(description, 240):
        raise PackageError('Descripción inválida.')
    entry = data.get('entrypoint')
    if not isinstance(entry, str) or not package_path(entry).lower().endswith(('.exe', '.py', '.pyw')):
        raise PackageError('Indica un archivo .exe, .py o .pyw en entrypoint.')
    if python_entrypoint(entry):
        if data.get('python') != PYTHON_VERSION:
            raise PackageError('Un punto de entrada Python requiere «python»: «3.12».')
    elif 'python' in data:
        raise PackageError('El campo python solo se usa con .py y .pyw.')
    if 'data' in data:
        data_contract(data['data'])
    icon = data.get('icon')
    if icon is not None and (not isinstance(icon, str) or not package_path(icon).lower().endswith(('.png', '.ico'))):
        raise PackageError('El icono debe ser un archivo PNG o ICO del paquete.')
    args = data.get('args', [])
    if not isinstance(args, list) or len(args) > 32 or any(not isinstance(a, str) or len(a) > 512 or '\0' in a for a in args):
        raise PackageError('Los argumentos deben ser una lista de hasta 32 textos.')
    dock = data.get('dock', {})
    object_keys(dock, 'visible wheel', 'dock')
    if type(dock.get('visible', True)) is not bool or dock.get('wheel', 'passthrough') not in ('passthrough', 'consume'):
        raise PackageError('Dock admite visible y wheel con passthrough o consume.')
    settings = data.get('settings', [])
    if not isinstance(settings, list) or len(settings) > 24:
        raise PackageError('Se admiten hasta 24 ajustes.')
    keys = set()
    for spec in settings:
        object_keys(spec, 'id label type default min max choices portable multiline', 'ajuste')
        key = spec.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key) or key in keys:
            raise PackageError('Cada ajuste necesita un id único en minúsculas.')
        keys.add(key)
        if type(spec.get('portable', True)) is not bool:
            raise PackageError(f'El indicador portable de {key} debe ser booleano.')
        if not short_text(spec.get('label'), 80) or spec.get('type') not in ('boolean', 'integer', 'choice', 'text'):
            raise PackageError(f'Tipo o etiqueta inválidos en {key}.')
        if 'multiline' in spec and (spec['type'] != 'text' or type(spec['multiline']) is not bool):
            raise PackageError(f'El indicador multiline de {key} solo admite un booleano en campos de texto.')
        if spec['type'] == 'integer' and not (
                type(spec.get('min')) is int and type(spec.get('max')) is int and
                -1000000 <= spec['min'] <= spec['max'] <= 1000000):
            raise PackageError(f'Mínimo o máximo inválido en {key}.')
        if spec['type'] == 'choice' and not (
                isinstance(spec.get('choices'), list) and 1 <= len(spec['choices']) <= 24 and
                all(short_text(choice, 80) for choice in spec['choices']) and
                len(set(spec['choices'])) == len(spec['choices'])):
            raise PackageError(f'Opciones inválidas en {key}.')
        if not valid_setting(spec, spec.get('default')):
            raise PackageError(f'Valor inicial inválido en {key}.')
    return dict(data, name=data['name'].strip(), description=description.strip(), icon=icon, args=args,
                dock={'visible': dock.get('visible', True), 'wheel': dock.get('wheel', 'passthrough')},
                settings=settings, tags=app_tags(data.get('tags', [])))


def zip_entries(archive, manifest_name=MANIFEST):
    paths, files, total = {}, {}, 0
    items = archive.infolist()
    if len(items) > 12000:
        raise PackageError('El paquete supera el límite de 12 000 archivos y carpetas.')
    for item in items:
        name = package_path(item.orig_filename.rstrip('/') if item.is_dir() else item.orig_filename)
        mode = stat.S_IFMT(item.external_attr >> 16)
        if (item.flag_bits & 1 or mode not in (0, stat.S_IFREG, stat.S_IFDIR) or
                bool(mode == stat.S_IFDIR) != item.is_dir() and mode != 0):
            raise PackageError(f'El paquete contiene un enlace, cifrado o un tipo de archivo inválido: {name}')
        folded = name.casefold()
        if folded in paths:
            raise PackageError(f'Ruta duplicada: {name}')
        paths[folded] = (name, item.is_dir())
        if not item.is_dir():
            files[name] = item
            total += item.file_size
    if total > SIZE_LIMIT:
        raise PackageError('El paquete supera 1 GiB descomprimido.')
    prefixes = dict(paths)
    for name, _ in paths.values():
        parts = name.split('/')
        for length in range(1, len(parts)):
            parent = '/'.join(parts[:length])
            if prefixes.setdefault(parent.casefold(), (parent, True)) != (parent, True):
                raise PackageError(f'Conflicto entre rutas del paquete: {parent}')
    if manifest_name not in files or files[manifest_name].file_size > 65536:
        raise PackageError(f'Se necesita {manifest_name} en la raíz, de hasta 64 KiB.')
    return files


def unpack_package(path, destination=None):
    """Validate every ZIP member, optionally streaming it into a private staging directory."""
    try:
        with ZipFile(path) as archive:
            files = zip_entries(archive)
            spec = manifest(json.loads(archive.read(files.pop(MANIFEST)).decode('utf-8')))
            if spec['entrypoint'] not in files:
                raise PackageError('El punto de entrada declarado no está en el paquete.')
            if spec['icon'] and (spec['icon'] not in files or files[spec['icon']].file_size > 2 * 1024 ** 2):
                raise PackageError('El icono declarado debe estar en el paquete y pesar hasta 2 MiB.')
            fingerprint = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode('utf-8'))
            for name, item in sorted(files.items()):
                fingerprint.update(name.encode('utf-8') + b'\0')
                digest = hashlib.sha256()
                output_path = destination / name if destination is not None else os.devnull
                if destination is not None:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, open(output_path, 'wb') as output:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(chunk)
                        if destination is not None:
                            output.write(chunk)
                fingerprint.update(digest.digest())
            if destination is not None:
                atomic_json(destination / MANIFEST, spec)
            return spec, fingerprint.hexdigest()
    except (BadZipFile, UnicodeError, json.JSONDecodeError, NotImplementedError, RuntimeError) as error:
        raise PackageError(f'Paquete ilegible: {error}') from error


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as out:
        temporary = Path(out.name)
        try:
            json.dump(data, out, ensure_ascii=False, indent=2, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
            out.close()
            os.replace(temporary, path)
        finally:
            out.close()
            temporary.unlink(missing_ok=True)


def json_object(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise PackageError(f'El archivo {path.name} debe contener un objeto JSON.')
    return data


class PackageStore:
    def __init__(self, store, data):
        self.root = store
        self.data = data
        self.index = store / 'instaladas.json'
        self.releases = store / 'versiones'
        self.running = {}

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / 'estado.lock').open('a+b') as stream:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise PackageError('Ya hay otra operación con paquetes. Vuelve a intentarlo.') from error
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def records(self):
        records = json_object(self.index)
        for key, record in records.items():
            object_keys(record, 'manifest hash', 'registro')
            if not isinstance(record.get('hash'), str) or not DIRNAME.fullmatch(record['hash']):
                raise PackageError('Hash inválido en el registro de paquetes.')
            record['manifest'] = manifest(record.get('manifest'))
            if record['manifest']['id'] != key:
                raise PackageError('El id del registro de paquetes no coincide.')
        return records

    def entries(self):
        items = []
        for record in self.records().values():
            spec = record['manifest']
            release = self.releases / spec['id'] / record['hash']
            items.append(dict(name=spec['name'], path=str(release / spec['entrypoint']), package=spec,
                              root=release, icon=str(release / spec['icon']) if spec['icon'] else None))
        return sorted(items, key=lambda item: item['name'].casefold())

    def release_matches(self, release, spec, expected_digest):
        """Verify an installed release before treating a repeated import as a no-op."""
        try:
            if release.is_symlink() or release.is_junction():
                return False
            root = release.resolve()
            if not root.is_relative_to(self.root.resolve()) or not root.is_dir():
                return False
            metadata = root / MANIFEST
            if (metadata.is_symlink() or metadata.is_junction() or not metadata.is_file() or
                    metadata.stat().st_size > 65536 or
                    manifest(json.loads(metadata.read_text(encoding='utf-8'))) != spec):
                return False

            files = {}
            total = 0
            for path in root.rglob('*'):
                if path.is_symlink() or path.is_junction():
                    return False
                if path.is_dir():
                    continue
                if not path.is_file():
                    return False
                name = package_path(path.relative_to(root).as_posix())
                if name != MANIFEST:
                    files[name] = path
                    total += path.stat().st_size
                    if len(files) > 12000 or total > SIZE_LIMIT:
                        return False

            fingerprint = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode('utf-8'))
            for name, path in sorted(files.items()):
                fingerprint.update(name.encode('utf-8') + b'\0')
                file_digest = hashlib.sha256()
                with path.open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        file_digest.update(chunk)
                fingerprint.update(file_digest.digest())
            return fingerprint.hexdigest() == expected_digest
        except (OSError, ValueError, PackageError, RuntimeError):
            return False

    def release_in_use(self, release):
        try:
            processes = self.running.get(release.resolve(), ())
        except OSError:
            return False
        return any(process.poll() is None for process in processes)

    def install(self, path):
        with self.lock():
            records = self.records()
            with TemporaryDirectory(dir=self.root, prefix='instalar-') as temporary:
                stage = Path(temporary) / 'contenido'
                stage.mkdir()
                spec, digest = unpack_package(path, stage)
                app_id = spec['id']
                previous = records.get(app_id)
                release = self.releases / app_id / digest
                complete = self.release_matches(release, spec, digest)
                repaired = previous is not None and previous['hash'] == digest and not complete
                if previous is not None:
                    old_version = previous['manifest']['version']
                    if previous['hash'] == digest and complete:
                        return 'sin cambios', spec
                    if old_version == spec['version'] and previous['hash'] != digest:
                        raise PackageError('Ese número de versión ya existe con contenido distinto. Aumenta la versión.')
                    if tuple(map(int, spec['version'].split('.'))) < tuple(map(int, old_version.split('.'))):
                        raise PackageError(f'La versión instalada ({old_version}) es más nueva.')
                release.parent.mkdir(parents=True, exist_ok=True)
                if not release.parent.resolve().is_relative_to(self.root.resolve()):
                    raise PackageError('La ruta de instalación salió del almacén de Cicerón.')
                if not complete:
                    if release.exists() or release.is_symlink() or release.is_junction():
                        if self.release_in_use(release):
                            raise PackageError('Cierra la aplicación antes de reparar su versión instalada.')
                        self.delete_release(release)
                    stage.rename(release)
                records[app_id] = dict(manifest=spec, hash=digest)
                atomic_json(self.index, records)
                self.prune(app_id, digest)
            return ('reparada' if repaired else 'actualizada' if previous else 'instalada'), spec

    def delete_release(self, release):
        if release.is_symlink() or release.is_junction() or not release.resolve().is_relative_to(self.root.resolve()):
            raise PackageError('No se puede retirar una versión que apunta fuera del almacén.')
        shutil.rmtree(release)

    def prune(self, app_id, keep=None):
        folder = self.releases / app_id
        complete = True
        if folder.is_dir() and folder.resolve().is_relative_to(self.root.resolve()):
            for release in folder.iterdir():
                if release.name != keep and DIRNAME.fullmatch(release.name) and release.is_dir():
                    processes = [proc for proc in self.running.pop(release.resolve(), []) if proc.poll() is None]
                    if processes:
                        self.running[release.resolve()] = processes
                        complete = False
                        continue
                    try:
                        self.delete_release(release)
                    except (OSError, PackageError):
                        complete = False
        return complete

    def sweep(self):
        if not self.releases.is_dir():
            return
        with self.lock():
            records = self.records()
            for folder in self.releases.iterdir():
                if APP_ID.fullmatch(folder.name):
                    self.prune(folder.name, records.get(folder.name, {}).get('hash'))

    def remove(self, app_id):
        if not APP_ID.fullmatch(app_id):
            raise PackageError('Id de aplicación inválido.')
        with self.lock():
            records = self.records()
            if app_id in records:
                del records[app_id]
                atomic_json(self.index, records)
            return self.prune(app_id)

    def data_folder(self, spec):
        return self.data / spec['id']

    @contextmanager
    def data_lease(self, app_id, *, exclusive):
        """A child inherits the open handle, so closing Cicerón does not unlock a running app."""
        locks = self.root / 'datos-en-uso'
        locks.mkdir(parents=True, exist_ok=True)
        handle = _kernel.CreateFileW(str(locks / (app_id + '.lock')), 0x80000000,
                                     0 if exclusive else 1, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in (32, 33):
                raise PackageError(f'Cierra {app_id} antes de trasladar sus datos.') from ctypes.WinError(error)
            raise ctypes.WinError(error)
        try:
            yield handle
        finally:
            _kernel.CloseHandle(handle)

    def settings(self, spec):
        stored = json_object(self.data_folder(spec) / 'settings.json')
        for field in spec['settings']:
            key = field['id']
            if not valid_setting(field, stored.get(key)):
                stored[key] = field['default']
        return stored

    def save_settings(self, spec, values):
        with self.data_lease(spec['id'], exclusive=False):
            stored = self.settings(spec)
            fields = {field['id']: field for field in spec['settings']}
            for key, value in values.items():
                if key not in fields or not valid_setting(fields[key], value):
                    raise PackageError(f'Valor inválido para {key}.')
                stored[key] = value
            atomic_json(self.data_folder(spec) / 'settings.json', stored)

    def launch(self, item):
        spec = item['package']
        root = item['root'].resolve()
        executable = Path(item['path']).resolve()
        if not root.is_relative_to(self.root.resolve()) or not executable.is_relative_to(root):
            raise PackageError('El ejecutable apunta fuera del paquete instalado.')
        if not executable.is_file():
            raise PackageError('Falta el ejecutable. Vuelve a importar el paquete.')
        data = self.data_folder(spec).resolve()
        if not data.is_relative_to(self.data.resolve()):
            raise PackageError('La carpeta de datos apunta fuera de Cicerón.')
        environment = dict(os.environ, CICERON_APP_ID=spec['id'], CICERON_APP_DATA=str(data),
                           CICERON_APP_SETTINGS=str(data / 'settings.json'), PYINSTALLER_RESET_ENVIRONMENT='1')
        ui_root = Path(__file__).resolve().parent
        if (ui_root / 'miniapp_ui.py').is_file():
            environment['CICERON_UI_ROOT'] = str(ui_root)
            environment['CICERON_UI_CONFIG'] = str(self.data.parent / 'config.json')
        frozen = getattr(sys, 'frozen', False)
        if frozen:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            cwd = root
            if python_entrypoint(executable):
                command = python_command(executable, environment)
                if len(str(root).encode('utf-16-le')) // 2 >= 260:
                    command = [*command[:-1], '-c', PYTHON_LONG_CWD, str(root), str(executable)]
                    cwd = self.root.resolve().anchor
            else:
                command = [str(executable)]
            with self.data_lease(spec['id'], exclusive=False) as lease:
                self.save_settings(spec, {})
                os.set_handle_inheritable(lease, True)
                startup = subprocess.STARTUPINFO(lpAttributeList={'handle_list': [lease]})
                process = subprocess.Popen([*command, *spec['args']], cwd=cwd, env=environment,
                                           startupinfo=startup, close_fds=True)
            running = [proc for proc in self.running.get(root, ()) if proc.poll() is None]
            self.running[root] = [*running, process]
            return process
        finally:
            if frozen:
                ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)


def create_package(folder, output):
    folder, output = folder.resolve(), output.resolve()
    if not folder.is_dir() or output.suffix.lower() != PACKAGE_EXT or output.is_relative_to(folder):
        raise PackageError('Usa un directorio de entrada y un .ciceron fuera de ese directorio.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix='empaquetar-') as temporary:
        staged = Path(temporary) / output.name
        with ZipFile(staged, 'w', ZIP_DEFLATED, compresslevel=3) as archive:
            for path in sorted(folder.rglob('*')):
                if path.is_symlink() or path.is_junction():
                    raise PackageError(f'No se admiten enlaces: {path}')
                if path.is_file():
                    archive.write(path, package_path(path.relative_to(folder).as_posix()))
        spec, digest = unpack_package(staged)
        os.replace(staged, output)
        return spec, digest
