"""Date and time rules for the standup page (standup story). Pure Python:
no models, no queries, so every rule here is unit-tested without a database.

    build_window()          the time window every section uses
    previous_working_day()  "since last standup": Monday looks back to Friday
    working_days_between()  how long a task has been blocked, in working days
    value_at()              what a task's field was at a moment, from its change log
    group_markers()         the timeline: one marker per event, or per hour when busy

Working days are Monday to Friday; there's no holiday calendar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Iterable, Sequence

from common.errors import InvalidWindow

WINDOWS = {
    "since_last": "Since last standup",
    "today": "Today",
    "24h": "Last 24 hours",
    "custom": "Custom range",
}
DEFAULT_WINDOW = "since_last"
MAX_CUSTOM_DAYS = 92
GROUP_THRESHOLD = 30  # more events than this: same-hour events share one marker


@dataclass(frozen=True)
class Window:
    """[start, end): every section counts what happened from start up to, not including, end."""

    key: str
    start: datetime
    end: datetime
    label: str

    def previous(self) -> "Window":
        """The window of the same length just before this one (for the tiles' deltas)."""
        span = self.end - self.start
        return Window(self.key, self.start - span, self.start, "Previous window")

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


def is_working_day(day: date) -> bool:
    return day.weekday() < 5  # Monday 0 ... Friday 4


def previous_working_day(day: date) -> date:
    day -= timedelta(days=1)
    while not is_working_day(day):
        day -= timedelta(days=1)
    return day


def working_days_between(start: date, end: date) -> int:
    """Working days after `start`, up to and including `end`: blocked on Monday,
    it's Wednesday, so 2. Zero if end isn't after start."""
    count, day = 0, start
    while day < end:
        day += timedelta(days=1)
        count += is_working_day(day)
    return count


def _midnight(day: date, tz: tzinfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def build_window(key: str | None, now: datetime, tz: tzinfo,
                 start: date | None = None, end: date | None = None) -> Window:
    """The window for a key in WINDOWS. `now` is aware; `tz` decides where days begin.
    A custom range covers whole days from `start` to `end`, both included."""
    key = key or DEFAULT_WINDOW
    today = now.astimezone(tz).date()
    if key == "since_last":
        since = previous_working_day(today)
        return Window(key, _midnight(since, tz), now, f"Since {since:%a, %b} {since.day}")
    if key == "today":
        return Window(key, _midnight(today, tz), now, "Today")
    if key == "24h":
        return Window(key, now - timedelta(hours=24), now, WINDOWS["24h"])
    if key == "custom":
        if start is None or end is None:
            raise InvalidWindow("Pick both a start and an end date")
        if end < start:
            raise InvalidWindow("The end date can't be before the start date")
        if start > today:
            raise InvalidWindow("The range can't start in the future")
        if (end - start).days + 1 > MAX_CUSTOM_DAYS:
            raise InvalidWindow(f"Pick a range of at most {MAX_CUSTOM_DAYS} days")
        finish = min(_midnight(end + timedelta(days=1), tz), now)
        return Window(key, _midnight(start, tz), finish,
                      f"{start:%b} {start.day} – {end:%b} {end.day}")
    raise InvalidWindow(f"Unknown window {key!r}")


def value_at(moment: datetime, current: Any, changes: Sequence[tuple[datetime, Any]]) -> Any:
    """What a value was just before `moment`, given its current value and the
    (time, old value) of each change, oldest first: the old value of the first
    change at or after `moment`, or the current value if nothing changed since."""
    for at, old in changes:
        if at >= moment:
            return old
    return current


@dataclass
class Marker:
    at: datetime
    kind: str          # an event kind, or "mixed" when a grouped hour has several
    events: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.events)


def group_markers(events: Iterable[dict], tz: tzinfo,
                  threshold: int = GROUP_THRESHOLD) -> tuple[bool, list[Marker]]:
    """Events (dicts with an aware "at" and a "kind"), oldest first, become timeline
    markers. Up to `threshold` events: one marker each. More: one marker per hour
    (local time) holding every event in it. Returns (grouped?, markers)."""
    events = list(events)
    if len(events) <= threshold:
        return False, [Marker(e["at"], e["kind"], [e]) for e in events]
    hours: dict[datetime, Marker] = {}
    for e in events:
        hour = e["at"].astimezone(tz).replace(minute=0, second=0, microsecond=0)
        marker = hours.setdefault(hour, Marker(hour, e["kind"]))
        marker.events.append(e)
        if marker.kind != e["kind"]:
            marker.kind = "mixed"
    return True, list(hours.values())
