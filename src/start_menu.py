"""Optional per-user Start menu shortcuts for Cicerón's library."""

import hashlib
import ctypes as C
from _ctypes import COMError
from functools import cache
import os
from pathlib import Path
import re
import uuid

from app_packages import APP_ID, RESERVED, atomic_json, json_object
from app_paths import application_root, development_mode


MARKER = 'Ciceron.Library:'
BUILTIN_TOOLS = frozenset(('clock', 'browser', 'effects'))
BIRTHDAY_PACKAGE = 'emilioreato.happy-birthday'
BIRTHDAY_APP_ID = 'Ciceron.HappyBirthday'


@cache
def property_store_types():
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class Key(C.Structure):
        _fields_ = [('fmtid', GUID), ('pid', C.c_uint32)]

    class Value(C.Structure):
        _fields_ = [('vt', C.c_ushort), ('reserved', C.c_ushort * 3),
                    ('data', C.c_void_p * 2)]

    class IPropertyStore(IUnknown):
        _iid_ = GUID('{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'GetCount', (['out'], C.POINTER(C.c_uint32), 'count')),
            COMMETHOD([], HRESULT, 'GetAt', (['in'], C.c_uint32, 'index'), (['out'], C.POINTER(Key), 'key')),
            COMMETHOD([], HRESULT, 'GetValue', (['in'], C.POINTER(Key), 'key'),
                      (['out'], C.POINTER(Value), 'value')),
            COMMETHOD([], HRESULT, 'SetValue', (['in'], C.POINTER(Key), 'key'),
                      (['in'], C.POINTER(Value), 'value')),
            COMMETHOD([], HRESULT, 'Commit'),
        ]
    return Key, Value, IPropertyStore


def set_app_identity(store, Key, Value, app_id):
    from comtypes import GUID
    app_key = Key(GUID('{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}'), 5)
    if app_id is None:
        store.SetValue(app_key, Value())
        return
    name = C.create_unicode_buffer(app_id)
    store.SetValue(app_key, Value(31, data=(C.c_void_p * 2)(C.addressof(name), None)))


def set_window_identity(hwnd, app_id):
    Key, Value, IPropertyStore = property_store_types()
    store = C.POINTER(IPropertyStore)()
    C.OleDLL('shell32').SHGetPropertyStoreForWindow(
        C.c_void_p(hwnd), C.byref(IPropertyStore._iid_), C.byref(store))
    set_app_identity(store, Key, Value, app_id)


def set_link_properties(path, app_id, tags):
    from comtypes import GUID
    from comtypes.client import CreateObject
    from comtypes.persist import IPersistFile
    from comtypes.shelllink import ShellLink

    Key, Value, IPropertyStore = property_store_types()
    link = CreateObject(ShellLink, interface=IPersistFile)
    link.Load(str(path), 2)
    store = link.QueryInterface(IPropertyStore)
    props = C.OleDLL('propsys')
    keyword_key = Key(GUID('{F29F85E0-4FF9-1068-AB91-08002B27B3D9}'), 5)
    set_app_identity(store, Key, Value, app_id)
    if tags:
        vector = (C.c_wchar_p * len(tags))(*tags)
        keywords = Value()
        props.InitPropVariantFromStringVector(vector, C.c_ulong(len(vector)), C.byref(keywords))
        try:
            store.SetValue(keyword_key, keywords)
        finally:
            C.OleDLL('ole32').PropVariantClear(C.byref(keywords))
    store.Commit()
    link.Save(str(path), True)


def shortcut_id(item):
    package = item.get('package')
    if package:
        key = package['id']
    else:
        executable = Path(item['path']).resolve()
        try:
            key = 'portable:' + executable.relative_to(application_root().resolve()).as_posix().casefold()
        except ValueError:
            key = os.path.normcase(str(executable))
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


class StartMenuApps:
    def __init__(self, folder, ciceron):
        self.folder = folder
        self.ciceron = ciceron

    @staticmethod
    def shell():
        from comtypes.client import CreateObject
        return CreateObject('WScript.Shell', dynamic=True)

    def find(self, shell, item):
        marker = MARKER + shortcut_id(item) + ' '
        for path in self.folder.glob('*.lnk'):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                if shell.CreateShortcut(str(path)).Description.startswith(marker):
                    return path
            except COMError:
                continue
        return None

    def update(self, item, tags, previous=None):
        if development_mode():
            return
        if previous is not None and not self.folder.is_dir():
            return
        shell = self.shell()
        existing = self.find(shell, previous or item)
        if previous is not None and existing is None:
            return
        package = item.get('package')
        executable = Path(item['path']).resolve()
        if not executable.is_file() or (package and not self.ciceron.is_file()):
            raise ValueError('El ejecutable de la aplicación debe estar disponible.')

        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', item['name'][:100]).strip(' .') or 'Aplicación'
        if RESERVED.fullmatch(name.split('.')[0].rstrip()):
            name = 'Cicerón - ' + name
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / (name + '.lnk')
        if path.exists() and path != existing:
            path = self.folder / f'{name} ({shortcut_id(item)[:6]}).lnk'
        tmp = self.folder / (uuid.uuid4().hex + '.lnk')
        try:
            link = shell.CreateShortcut(str(tmp))
            link.TargetPath = str(self.ciceron if package else executable)
            link.Arguments = f"--lanzar-paquete {package['id']}" if package else ''
            link.WorkingDirectory = str(executable.parent)
            icon = Path(item['icon']) if item.get('icon') else executable
            if icon.is_file() and icon.suffix.lower() in ('.exe', '.ico'):
                link.IconLocation = str(icon) + ',0'
            description = ', '.join(tags) if tags else item['name']
            link.Description = f'{MARKER}{shortcut_id(item)} {description}'[:240]
            link.Save()
            if package:
                app_id = (BIRTHDAY_APP_ID if package['id'] == BIRTHDAY_PACKAGE
                          else 'Ciceron.Package.' + shortcut_id(item))
                set_link_properties(tmp, app_id, tags)
            if path == existing:
                tmp.replace(path)
            else:
                tmp.rename(path)
                if existing:
                    existing.unlink(missing_ok=True)
        finally:
            tmp.unlink(missing_ok=True)

    def remove(self, item):
        if development_mode():
            return
        if self.folder.is_dir():
            path = self.find(self.shell(), item)
            if path:
                path.unlink(missing_ok=True)


def request_launch(folder, app_id, *, builtin=False):
    if builtin and app_id not in BUILTIN_TOOLS:
        raise ValueError('Aplicación interna desconocida.')
    if not builtin and (len(app_id) > 80 or not APP_ID.fullmatch(app_id)):
        raise ValueError('Identificador de paquete inválido.')
    atomic_json(folder / (uuid.uuid4().hex + '.json'), {'tool' if builtin else 'id': app_id})


def pending_launches(folder):
    for path in folder.glob('*.json'):
        if not re.fullmatch(r'[a-f0-9]{32}', path.stem):
            continue
        try:
            request = json_object(path)
        except ValueError:
            request = {}
        except OSError:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        tool = request.get('tool')
        app_id = request.get('id')
        if request == {'control': 'quit'}:
            yield 'control', 'quit'
        elif isinstance(tool, str) and tool in BUILTIN_TOOLS:
            yield 'tool', tool
        elif isinstance(app_id, str) and APP_ID.fullmatch(app_id):
            yield 'package', app_id
