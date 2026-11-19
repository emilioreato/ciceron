"""Birthdays, original CSV migration, and portable atomic storage."""
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
import calendar
import csv
import io
import json
import os
import re
from tempfile import NamedTemporaryFile
import unicodedata
from uuid import uuid4

STYLES = ("V1", "V2", "V3")
MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
DATE_NUMBERS = re.compile(r"[0-9]+")
LEGACY_HEADER = ("dd-mm,nombres*", "dd-mm,nombres", "dd-mm,nombres(optional)")
NAME_LIMIT = 100


def fold(text):
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def clean_name(value, *, optional=False):
    if not isinstance(value, str):
        raise ValueError("El nombre no es válido.")
    name = " ".join(value.split())
    if not name and not optional:
        raise ValueError("Escribí un nombre.")
    if len(name) > NAME_LIMIT or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError(f"Usá un nombre de hasta {NAME_LIMIT} caracteres.")
    return name


def parse_date(text, today=None):
    today = today or date.today()
    numbers = DATE_NUMBERS.findall(text)
    if (len(numbers) not in (2, 3) or any(len(part) > 2 for part in numbers[:2])
            or (len(numbers) == 3 and len(numbers[2]) != 4)):
        raise ValueError("Usá día-mes-año, por ejemplo 8-9-2004, o 8-9 si no sabés el año.")
    day, month = map(int, numbers[:2])
    year = int(numbers[2]) if len(numbers) == 3 else None
    try:
        birth = date(2000 if year is None else year, month, day)
    except ValueError:
        raise ValueError("Esa fecha no existe. Revisá el día, el mes y el año.") from None
    if year is not None and birth > today:
        raise ValueError("La fecha de nacimiento no puede estar en el futuro.")
    return day, month, year


@dataclass(frozen=True)
class Birthday:
    id: str
    name: str
    day: int
    month: int
    year: int | None = None

    @classmethod
    def new(cls, name, parts):
        return cls(uuid4().hex, clean_name(name, optional=True), *parts)

    @property
    def label(self):
        return self.name or "Cumpleaños sin nombre"

    @property
    def input_date(self):
        return f"{self.day}-{self.month}" + (f"-{self.year:04d}" if self.year is not None else "")

    @property
    def short_date(self):
        return f"{self.day:02d} {MONTHS[self.month - 1]}"

    def anniversary(self, year):
        day = 28 if (self.month, self.day) == (2, 29) and not calendar.isleap(year) else self.day
        return date(year, self.month, day)

    def next_date(self, today):
        candidate = self.anniversary(today.year)
        return candidate if candidate >= today else self.anniversary(today.year + 1)

    def upcoming_age(self, upcoming):
        return None if self.year is None else upcoming.year - self.year


def upcoming(items, today):
    return sorted(items, key=lambda item: (item.next_date(today), fold(item.name), item.id))


def same_person(left, right):
    return (fold(left.name) == fold(right.name) and (left.day, left.month) == (right.day, right.month)
            and (left.year == right.year or None in (left.year, right.year)))


def legacy_entries(path):
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("El CSV supera los 5 MB.")
    raw = path.read_bytes()
    try:
        contents = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        contents = raw.decode("cp1252")
    found = []
    seen_valid_date = False
    for number, row in enumerate(csv.reader(io.StringIO(contents, newline=""), strict=True), 1):
        if not row or not any(cell.strip() for cell in row):
            continue
        if not seen_valid_date and (row[0].strip().casefold() in LEGACY_HEADER
                or (row[0].strip().casefold() == "dd-mm" and len(row) > 1)):
            continue
        try:
            parts = parse_date(row[0])
            if parts[2] is not None:
                raise ValueError("El archivo original guarda solo día y mes.")
            found.extend(Birthday.new(name, parts) for name in row[1:] if name.strip())
        except ValueError as error:
            raise ValueError(f"Fila {number} del CSV. {error}") from None
        seen_valid_date = True
    if not seen_valid_date:
        raise ValueError("No encontré fechas en el formato de Happy Birthday.")
    return found


def merge_legacy(current, incoming):
    merged = list(current)
    skipped = 0
    for item in incoming:
        if any(same_person(item, known) for known in merged):
            skipped += 1
        else:
            merged.append(item)
    return merged, skipped


@dataclass(frozen=True)
class State:
    entries: tuple[Birthday, ...] = ()
    style: str = "V2"
    notified_day: str = ""
    notified_ids: tuple[str, ...] = ()
    history: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def with_entries(self, entries):
        return replace(self, entries=tuple(entries))


def load(path):
    if not path.exists():
        return State()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or type(payload.get("schema")) is not int
            or payload["schema"] != 1 or payload.get("style") not in STYLES
            or not isinstance(payload.get("entries"), list)):
        raise ValueError("Formato de agenda no reconocido.")
    unnamed = payload.get("unnamed_ids", [])
    if not isinstance(unnamed, list) or not all(isinstance(i, str) for i in unnamed):
        raise ValueError("El registro de nombres opcionales no es válido.")
    unnamed = set(unnamed)
    entries = []
    ids = set()
    for row in payload["entries"]:
        if not isinstance(row, dict) or set(row) != {"id", "name", "day", "month", "year"}:
            raise ValueError("Hay un registro incompleto.")
        item = Birthday(**row)
        if (not isinstance(item.id, str) or not re.fullmatch(r"[a-f0-9]{32}", item.id)
                or item.id in ids or type(item.day) is not int or type(item.month) is not int
                or (item.year is not None and type(item.year) is not int)):
            raise ValueError("Hay un registro inválido o repetido.")
        date(2000 if item.year is None else item.year, item.month, item.day)
        ids.add(item.id)
        name = clean_name(item.name, optional=True)
        entries.append(replace(item, name="" if item.id in unnamed else name))
    if unnamed - ids:
        raise ValueError("Hay un nombre opcional sin cumpleaños.")
    alert_day = payload.get("notified_day", "")
    alert_ids = payload.get("notified_ids", [])
    if not isinstance(alert_day, str) or not isinstance(alert_ids, list) or not all(
            isinstance(i, str) and re.fullmatch(r"[a-f0-9]{32}", i) for i in alert_ids):
        raise ValueError("El registro de avisos no es válido.")
    if alert_day:
        date.fromisoformat(alert_day)
    history = payload.get("notification_history", {})
    if not isinstance(history, dict) or not all(
            isinstance(day, str) and isinstance(ids, list) and all(
                isinstance(i, str) and re.fullmatch(r"[a-f0-9]{32}", i) for i in ids)
            for day, ids in history.items()):
        raise ValueError("El historial de avisos no es válido.")
    for day in history:
        date.fromisoformat(day)
    return State(tuple(entries), payload["style"], alert_day, tuple(alert_ids),
                 tuple((day, tuple(ids)) for day, ids in history.items()))


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Older 1.0 releases require a printable name per row. The optional name
    # metadata makes this an additive v1 data format, including backups.
    content = dict(schema=1, style=state.style,
                   entries=[asdict(replace(item, name=item.label)) for item in state.entries],
                   unnamed_ids=[item.id for item in state.entries if not item.name],
                   notified_day=state.notified_day, notified_ids=state.notified_ids,
                   notification_history=dict(state.history))
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".cumples-",
                                suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(content, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sent_on(state, today):
    day = today.isoformat()
    sent = set(dict(state.history).get(day, ()))
    if state.notified_day == day:
        sent.update(state.notified_ids)
    return sent


def pending_today(state, today):
    sent = sent_on(state, today)
    return tuple(item for item in upcoming(state.entries, today)
                 if item.id not in sent and item.anniversary(today.year) == today)


def record_notifications(state, today, items):
    day = today.isoformat()
    history = dict(state.history)
    if state.notified_day and state.notified_day not in history:
        history[state.notified_day] = state.notified_ids
    ids = tuple(sorted(sent_on(state, today) | {item.id for item in items}))
    history[day] = ids
    # Keep the most recently touched dates, including after a clock correction.
    recent = dict((key, values) for key, values in history.items() if key != day)
    recent[day] = ids
    return replace(state, notified_day=day, notified_ids=ids, history=tuple(recent.items())[-16:])


def days_in_year(entries, year):
    result = {}
    for item in sorted(entries, key=lambda entry: (fold(entry.label), entry.id)):
        result.setdefault(item.anniversary(year), []).append(item)
    return result
