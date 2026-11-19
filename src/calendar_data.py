"""Read-only all-day calendar feeds shared by Cicerón applications."""
from dataclasses import dataclass
from datetime import date
import json


@dataclass(frozen=True)
class CalendarEvent:
    source: str
    uid: str
    day: date
    title: str


def read_events(folder, year):
    """Read independent versioned feeds. A malformed feed cannot hide the others."""
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        return []
    events = []
    for path in sorted(folder.glob('*.json')):
        try:
            if path.is_symlink() or path.stat().st_size > 1_000_000:
                continue
            feed = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(feed, dict) or type(feed.get('schema')) is not int
                    or feed['schema'] != 1 or not isinstance(feed.get('events'), list)):
                continue
            seen = set()
            for item in feed['events']:
                if not isinstance(item, dict):
                    continue
                uid, title, iso = item.get('id'), item.get('title'), item.get('date')
                if not all(isinstance(value, str) and value.strip() for value in (uid, title, iso)):
                    continue
                try:
                    day = date.fromisoformat(iso)
                except ValueError:
                    continue
                if day.isoformat() == iso and day.year == year and uid not in seen:
                    events.append(CalendarEvent(path.stem, uid, day, title.strip()))
                    seen.add(uid)
        except (OSError, ValueError):
            continue
    return events
