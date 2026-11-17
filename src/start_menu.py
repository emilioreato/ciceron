"""Optional per-user Start menu shortcuts for Cicerón's library."""

import hashlib
from _ctypes import COMError
import os
from pathlib import Path
import re
import uuid

from app_packages import APP_ID, RESERVED, atomic_json, json_object


MARKER = 'Ciceron.Library:'
BUILTIN_TOOLS = frozenset(('clock', 'browser', 'effects'))


def shortcut_id(item):
    package = item.get('package')
    key = package['id'] if package else os.path.normcase(os.path.abspath(item['path']))
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
            if path == existing:
                tmp.replace(path)
            else:
                tmp.rename(path)
                if existing:
                    existing.unlink(missing_ok=True)
        finally:
            tmp.unlink(missing_ok=True)

    def remove(self, item):
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
        if isinstance(tool, str) and tool in BUILTIN_TOOLS:
            yield 'tool', tool
        elif isinstance(app_id, str) and APP_ID.fullmatch(app_id):
            yield 'package', app_id
