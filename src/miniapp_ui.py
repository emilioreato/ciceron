"""Shared window material for Python miniapps running in their own process."""
import json
import os
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QTimer
from PySide6.QtWidgets import QApplication

from center_ui import GlassDialog, clear_styles, dark_mode, panel, stylesheet


class MiniappDialog(GlassDialog):
    def __init__(self, parent=None, *, attached=False):
        super().__init__(parent, attached=attached)
        if attached:
            return
        self.floating = True
        self.material_changed = self.update_style
        self.preferences = Path(os.environ['CICERON_UI_CONFIG'])
        self.watcher = QFileSystemWatcher([str(self.preferences.parent)], self)
        self.debounce = QTimer(self, interval=100, singleShot=True)
        self.watcher.directoryChanged.connect(lambda _: self.debounce.start())
        self.watcher.fileChanged.connect(lambda _: self.debounce.start())
        self.debounce.timeout.connect(self.apply_preferences)
        self.appearance = None
        self.apply_preferences()

    def apply_preferences(self):
        if self.preferences.is_file() and not self.watcher.files():
            self.watcher.addPath(str(self.preferences))
        try:
            preferences = json.loads(self.preferences.read_text(encoding='utf-8'))
            if not isinstance(preferences, dict):
                return
        except FileNotFoundError:
            preferences = {}
        except (OSError, ValueError):
            return
        version = preferences.get('ui_version', 'v2')
        classic = version == 'v1'
        pure_version = version in ('v3', 'v4')
        configured_glass = bool(preferences.get('glass', True))
        pure = pure_version
        dark = not classic and dark_mode(preferences.get('theme', 'system'))
        glass = not classic and (configured_glass or pure_version)
        transparency = {'clear': .20, 'contrast': -.18}.get(preferences.get('clarity'), 0)
        QApplication.instance().setProperty('ciceronUIVersion', version)
        appearance = (version, classic, pure, dark, glass, transparency)
        if appearance == self.appearance:
            return
        self.appearance = appearance
        self.dark, self.glass, self.transparency = dark, glass, transparency
        self.setProperty('pureGlass', pure)
        self.setProperty('frostControls', pure)
        self.setWindowOpacity(.995 if pure else 1)
        self.enable_material(glass, dark)
        self.update_style()

    def update_style(self):
        _, classic, pure, dark, glass, _ = self.appearance
        light = self.has_light_glass()
        style = stylesheet(dark and not light, glass, classic)
        dark_list = (dark or pure) and not light
        surface = '#ffffff' if classic else (
            'rgba(42,42,42,190)' if dark_list else 'rgba(255,255,255,185)')
        ink = '#202020' if classic else ('#fafafa' if dark_list else '#252525')
        highlight = '#e9e9e9' if classic else ('#525252' if dark_list else '#dddddd')
        style += f"""
            QListWidget {{ background: {surface}; color: {ink}; border: none; border-radius: 11px; padding: 4px; }}
            QListWidget::item {{ min-height: 28px; padding: 2px 7px; border-radius: 7px; }}
            QListWidget::item:selected {{ background: {highlight}; color: {ink}; }}
        """
        if pure:
            style += clear_styles('QWidget#liveWindow' if self.live else '', light=light,
                                  frost_controls=True, live_controls=self.live)
        self.setStyleSheet(style)
