"""Move declared app data and settings between Cicerón profiles."""
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from time import sleep
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED
from zlib import error as CompressionError

from app_packages import (APP_ID, PackageError, SIZE_LIMIT, atomic_json, data_contract,
                          json_object, object_keys, portable_data_path, valid_setting, zip_entries)

EXTENSION = '.ciceron-datos'
MANIFEST = 'datos.json'
PORTABLE_PREFERENCES = {
    'title': lambda v: isinstance(v, str) and len(v) <= 512,
    'target': lambda v: isinstance(v, str) and (v == '' or valid_date(v)),
    'words': lambda v: isinstance(v, str) and len(v) <= 4096,
    'interval': lambda v: type(v) is int and 1 <= v <= 86400,
    'theme': lambda v: v in ('system', 'light', 'dark'),
    'clarity': lambda v: v in ('clear', 'balanced', 'contrast'),
    'ui_version': lambda v: v in ('v1', 'v2', 'v3', 'v4'),
}
PORTABLE_PREFERENCES.update(dict.fromkeys(
    ('show_timer', 'guardian', 'topmost', 'glass', 'open_center_on_start', 'dock_motion', 'include_in_captures'),
    lambda v: type(v) is bool))


def valid_date(value):
    try:
        return len(value) <= 32 and datetime.fromisoformat(value).tzinfo is None
    except ValueError:
        return False


def validate_preferences(values):
    object_keys(values, ' '.join(PORTABLE_PREFERENCES), 'preferencias del centro')
    if any(not PORTABLE_PREFERENCES[key](value) for key, value in values.items()):
        raise PackageError('Hay preferencias generales con valores inválidos.')
    return values


def settings_for(spec, values):
    fields = {field['id']: field for field in spec['settings'] if field.get('portable', True)}
    if any(key not in fields or not valid_setting(fields[key], value) for key, value in values.items()):
        raise PackageError('Estos ajustes no son compatibles con la versión instalada.')
    return values


def checked_path(root, name=''):
    """Reject redirects in the data tree, including Windows directory junctions."""
    path = root
    for part in ('', *name.split('/')) if name else ('',):
        if part:
            path /= part
        if path.is_symlink() or path.is_junction():
            raise PackageError(f'No se admiten enlaces en los datos: {path.name}')
    return path


def identity(path):
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not path.is_file():
        raise PackageError(f'Se esperaba un archivo de datos: {path.name}')
    return info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def publish_directory(source, target):
    # Windows can briefly hold a directory handle after scanning a new file.
    for attempt in range(5):
        try:
            source.rename(target)
            return
        except OSError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 4:
                raise
            sleep(.04 * (attempt + 1))


def export_data(store, destination, app_ids, preferences=None):
    if destination.suffix.lower() != EXTENSION:
        raise PackageError(f'Elige un archivo {EXTENSION}.')
    if len(set(app_ids)) != len(app_ids) or (not app_ids and preferences is None):
        raise PackageError('Elige al menos una aplicación o las preferencias generales.')
    entries = []
    with store.lock(), TemporaryDirectory(dir=destination.parent, prefix='.exportar-') as temporary:
        records = store.records()
        staged = Path(temporary) / destination.name
        if staged.resolve().is_relative_to(store.data.resolve()):
            raise PackageError('Guarda el archivo de traslado fuera de la carpeta de datos de apps.')
        total = 0
        with ZipFile(staged, 'w', ZIP_DEFLATED) as archive:
            for app_id in app_ids:
                if app_id not in records:
                    raise PackageError(f'{app_id} ya no está instalada.')
                spec = records[app_id]['manifest']
                contract = spec.get('data')
                with store.data_lease(app_id, exclusive=True):
                    folder = checked_path(checked_path(store.data), app_id)
                    settings_path = checked_path(folder, 'settings.json')
                    paths = {name: checked_path(folder, name) for name in (contract or {}).get('files', [])}
                    before = {path: identity(path) for path in [settings_path, *paths.values()]}
                    for path in paths.values():
                        if any(identity(checked_path(path.parent, path.name + suffix))
                               for suffix in ('-wal', '-journal')):
                            raise PackageError(f'Cierra la base de datos de {app_id} y guarda sus cambios.')
                    all_settings = store.settings(spec)
                    values = {field['id']: all_settings[field['id']] for field in spec['settings']
                              if field.get('portable', True)}
                    files = []
                    for name, path in paths.items():
                        if before[path] is None:
                            continue
                        total += before[path][1]
                        if total > SIZE_LIMIT:
                            raise PackageError('El archivo de traslado supera 1 GiB descomprimido.')
                        archive.write(path, f'apps/{app_id}/{name}')
                        files.append(name)
                    if any(identity(path) != previous for path, previous in before.items()):
                        raise PackageError(f'Los datos de {app_id} cambiaron durante la exportación.')
                    entries.append(dict(id=app_id, version=contract['version'] if contract else None,
                                        files=files, settings=values))
            document = dict(schema=1, apps=entries)
            if preferences is not None:
                document['preferences'] = validate_preferences(preferences)
            encoded = json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(encoded) > 65536 or total + len(encoded) > SIZE_LIMIT:
                raise PackageError('La selección supera el tamaño del formato. Exporta menos aplicaciones.')
            archive.writestr(MANIFEST, encoded)
        with ZipFile(staged) as archive:
            zip_entries(archive, MANIFEST)
        os.replace(staged, destination)


class DataArchive:
    def __init__(self, root, document):
        self.root = root
        self.apps = {entry['id']: entry for entry in document['apps']}
        self.preferences = document.get('preferences')

    @staticmethod
    @contextmanager
    def open(source):
        """Validate and read every member before exposing a preview or writing to the profile."""
        with TemporaryDirectory(prefix='ciceron-datos-') as temporary:
            root = Path(temporary)
            try:
                with ZipFile(source) as archive:
                    members = zip_entries(archive, MANIFEST)
                    document = json.loads(archive.read(members.pop(MANIFEST)).decode('utf-8'))
                    object_keys(document, 'schema apps preferences', MANIFEST)
                    if type(document.get('schema')) is not int or document['schema'] != 1:
                        raise PackageError('Versión desconocida del archivo de traslado.')
                    if 'preferences' in document:
                        validate_preferences(document['preferences'])
                    apps = document.get('apps')
                    if not isinstance(apps, list) or (not apps and 'preferences' not in document):
                        raise PackageError('El archivo no contiene datos para importar.')
                    seen, expected = set(), set()
                    for entry in apps:
                        object_keys(entry, 'id version files settings', 'aplicación')
                        app_id, version = entry.get('id'), entry.get('version')
                        files, settings = entry.get('files'), entry.get('settings')
                        if (not isinstance(app_id, str) or len(app_id) > 80 or
                                not APP_ID.fullmatch(app_id) or app_id in seen):
                            raise PackageError('Identificador duplicado o inválido en el archivo de traslado.')
                        seen.add(app_id)
                        data_contract({'version': 1 if version is None else version, 'files': files})
                        if version is None and files:
                            raise PackageError('Los archivos requieren una versión de datos.')
                        if (not isinstance(settings, dict) or len(settings) > 24 or
                                any(type(value) not in (bool, int, str) or
                                    isinstance(value, str) and len(value) > 512 for value in settings.values())):
                            raise PackageError('Ajustes de aplicación inválidos.')
                        expected.update(f'apps/{app_id}/{name}' for name in files)
                    if expected != members.keys():
                        raise PackageError('El contenido no coincide con el manifiesto de datos.')
                    for name, member in members.items():
                        path = root / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as content, path.open('wb') as output:
                            shutil.copyfileobj(content, output)
            except (BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError, NotImplementedError,
                    CompressionError, EOFError) as error:
                raise PackageError(f'Archivo de traslado dañado: {error}') from error
            yield DataArchive(root, document)

    @staticmethod
    def compatible(entry, records):
        installed = records.get(entry['id'])
        if installed is None:
            raise PackageError('La aplicación no está instalada.')
        spec = installed['manifest']
        contract = spec.get('data', {})
        if (entry['version'] != contract.get('version') or
                not set(entry['files']).issubset(contract.get('files', []))):
            raise PackageError('La versión o los archivos de datos no son compatibles.')
        settings_for(spec, entry['settings'])
        return spec

    def preview(self, store):
        records = store.records()
        result = []
        for app_id, entry in self.apps.items():
            try:
                spec = self.compatible(entry, records)
                with store.data_lease(app_id, exclusive=True):
                    folder = checked_path(checked_path(store.data), app_id)
                    existing = folder.exists() and any(folder.iterdir())
                result.append((app_id, spec['name'], existing, None))
            except (ValueError, OSError) as error:
                result.append((app_id, app_id, False, str(error)))
        return result

    def restore(self, store, app_id, *, replace_existing=False):
        entry = self.apps[app_id]
        with store.lock(), store.data_lease(app_id, exclusive=True):
            spec = self.compatible(entry, store.records())
            folder = checked_path(checked_path(store.data), app_id)
            has_data = folder.exists() and any(folder.iterdir())
            if has_data and not replace_existing:
                return 'omitida', None
            work = store.data.parent
            store.data.mkdir(parents=True, exist_ok=True)
            backups = checked_path(work / 'respaldos-datos')
            with TemporaryDirectory(dir=work, prefix='.restaurar-') as temporary:
                candidate = Path(temporary) / 'contenido'
                candidate.mkdir()
                if has_data:
                    # Keep local-only files in the live profile. Reject redirects before copying.
                    for path in folder.rglob('*'):
                        name = path.relative_to(folder).as_posix()
                        checked_path(folder, name)
                    shutil.copytree(folder, candidate, dirs_exist_ok=True)
                declared = spec.get('data', {}).get('files', [])
                for name in declared:
                    checked_path(candidate, name).unlink(missing_ok=True)
                for name in entry['files']:
                    target = checked_path(candidate, name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.root / 'apps' / app_id / name, target)
                values = json_object(candidate / 'settings.json')
                for field in spec['settings']:
                    if field.get('portable', True):
                        values[field['id']] = entry['settings'].get(field['id'], field['default'])
                if values:
                    atomic_json(candidate / 'settings.json', values)
                backup = None
                if folder.exists():
                    backups.mkdir(exist_ok=True)
                    backup = backups / (app_id + '-' + uuid4().hex)
                    publish_directory(folder, backup)
                try:
                    publish_directory(candidate, folder)
                except OSError:
                    if backup is not None:
                        try:
                            publish_directory(backup, folder)
                        except OSError as error:
                            raise PackageError(f'Los datos originales se conservaron en {backup}.') from error
                    raise
            return 'restaurada', backup
