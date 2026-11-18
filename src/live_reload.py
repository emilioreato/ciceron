"""Restart the daily center on saved source changes, without periodic polling."""
from hashlib import sha256
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal


class LiveReload(QObject):
    restart = Signal()

    def __init__(self, source, parent, initial_digest=None):
        super().__init__(parent)
        self.source = Path(source)
        self.watcher = QFileSystemWatcher(self)
        self.timer = QTimer(self, interval=650, singleShot=True)
        self.retries = 0
        self.watcher.fileChanged.connect(self.schedule_check)
        self.watcher.directoryChanged.connect(self.schedule_check)
        self.timer.timeout.connect(self.check)
        try:
            observed_digest = self.scan()
        except OSError:
            observed_digest = None
        self.digest = initial_digest or observed_digest
        if self.digest != observed_digest or observed_digest is None:
            self.timer.start()

    def schedule_check(self, _path):
        self.retries = 0
        self.timer.start()

    def scan(self, *, validate=False):
        files = sorted(path for path in self.source.glob('*') if path.suffix in ('.py', '.pyw'))
        desired = {str(path) for path in files}
        current = set(self.watcher.files())
        if current - desired:
            self.watcher.removePaths(sorted(current - desired))
        if desired - current:
            self.watcher.addPaths(sorted(desired - current))
        directories = self.watcher.directories()
        missing = [str(path) for path in (self.source.parent, self.source)
                   if str(path) not in directories and path.is_dir()]
        if missing:
            self.watcher.addPaths(missing)
        digest = sha256()
        for path in files:
            content = path.read_bytes()
            if validate:
                compile(content, str(path), 'exec')
            digest.update(path.name.encode('utf-8') + b'\0' + sha256(content).digest())
        return digest.hexdigest()

    def check(self):
        try:
            digest = self.scan(validate=True)
        except OSError:
            # An editor can still hold the file after its last notification.
            if self.retries < 3:
                self.retries += 1
                self.timer.start()
            return
        except (SyntaxError, ValueError):
            return
        self.retries = 0
        if digest != self.digest and (self.source / 'ciceron.pyw').is_file():
            self.restart.emit()
