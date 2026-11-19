"""Resolve miniapp identity for the library, Windows links and notifications."""
from _ctypes import COMError
from dataclasses import dataclass
from functools import lru_cache
from hashlib import file_digest, sha256
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app_packages import app_tags


BIRTHDAY_PACKAGE = 'emilioreato.happy-birthday'
WINDOWS_ICON_CACHE = 'iconos-inicio'


def file_icon_reference(path):
    if path.suffix.lower() == '.exe':
        return path, 0
    if path.suffix.lower() == '.lnk':
        try:
            return shortcut_icon(path, path.stat().st_mtime_ns)
        except (OSError, COMError):
            pass
    return None


@lru_cache(maxsize=64)
def shortcut_icon(path, modified_ns):
    from comtypes.client import CreateObject

    link = CreateObject('WScript.Shell', dynamic=True).CreateShortcut(str(path))
    file, comma, index = link.IconLocation.rpartition(',')
    if not comma:
        file, index = link.IconLocation, '0'
    for source, resource in ((file, index), (link.TargetPath, '0')):
        if not source:
            continue
        icon = Path(os.path.expandvars(source.strip().strip('"')))
        if not icon.is_absolute():
            icon = path.parent / icon
        # Icon locations can point to a network share. Keep lookup local.
        if not str(icon).startswith('\\\\') and icon.suffix.lower() in ('.ico', '.exe', '.dll', '.icl'):
            try:
                if icon.is_file():
                    return icon, int(resource)
            except (OSError, ValueError):
                continue
    return None


@lru_cache(maxsize=64)
def resource_icon(path, index, modified_ns):
    """Read the icon directly, without invoking Shell file handlers."""
    import ctypes as C
    from ctypes import wintypes as W
    from PySide6.QtGui import QIcon, QImage, QPixmap

    extract = C.windll.shell32.ExtractIconExW
    extract.argtypes = (W.LPCWSTR, C.c_int, C.POINTER(W.HICON), C.POINTER(W.HICON), W.UINT)
    extract.restype = W.UINT
    destroy = C.windll.user32.DestroyIcon
    destroy.argtypes = (W.HICON,)
    destroy.restype = W.BOOL
    handle = W.HICON()
    if extract(str(path), index, C.byref(handle), None, 1) != 1 or not handle:
        return QIcon()
    try:
        return QIcon(QPixmap.fromImage(QImage.fromHICON(handle.value)))
    finally:
        destroy(handle)


@dataclass(frozen=True)
class AppIdentity:
    name: str
    icon: Path | None
    package_id: str | None
    tags: tuple[str, ...]

    @classmethod
    def from_entry(cls, item, overrides=None):
        spec = item.get('package')
        package_id = spec['id'] if spec else None
        tags = item.get('tags', [])
        if spec:
            tags = (overrides or {}).get(package_id, spec.get('tags', []))
        try:
            labels = tuple(app_tags(tags))
        except ValueError:
            labels = ()
        return cls(spec['name'] if spec and 'name' in spec else item['name'],
                   Path(item['icon']) if item.get('icon') else None, package_id, labels)

    @property
    def windows_id(self):
        if self.package_id == BIRTHDAY_PACKAGE:
            return 'Ciceron.HappyBirthday'  # Preserve the ID already registered in Windows.
        if self.package_id:
            return 'Ciceron.Package.' + sha256(self.package_id.encode('utf-8')).hexdigest()[:16]
        return None

    @property
    def notification_title(self):
        return f'Cicerón · {self.name}'

    def notification_text(self, title, body):
        heading = self.notification_title
        if title and title not in (self.name, heading):
            body = f'{title}\n{body}'
        return heading, body

    def windows_icon(self, cache):
        if self.icon is None or not self.icon.is_file():
            return None
        if self.icon.suffix.lower() in ('.ico', '.exe'):
            return self.icon
        if self.icon.suffix.lower() != '.png':
            return None
        with self.icon.open('rb') as source:
            fingerprint = file_digest(source, 'sha256').hexdigest()
        target = cache / (fingerprint + '.ico')
        if target.is_file():
            return target

        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QImageReader

        reader = QImageReader(str(self.icon))
        size = reader.size()
        if not size.isValid():
            return None
        size.scale(QSize(64, 64), Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
        image = reader.read()
        if image.isNull():
            return None
        cache.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=cache, suffix='.ico', delete=False) as output:
            staged = Path(output.name)
        try:
            if not image.save(str(staged), 'ICO'):
                return None
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)
        return target
