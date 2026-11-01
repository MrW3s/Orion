"""Lays out the Gantt chart: where each task's bar sits on the timeline.

Presentation only. The services decide which tasks are shown and in what
order (dependency order); this module turns their dates into positions, as
percentages of the timeline's width, so the page needs no JavaScript chart
library. It only reads each item's dates, through `dates`, so it works on a
Task (the team's chart) or a ClientTask (the client's chart, which carries
no assignee or other internal details).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Sequence

DAILY_TICKS_UP_TO = 21  # days; longer charts get one tick per week


def task_dates(task) -> tuple[date | None, date | None]:
    return task.scheduled_start, task.scheduled_end


@dataclass(frozen=True)
class GanttRow:
    task: object
    start: date
    end: date
    left: str   # CSS percentage, e.g. "12.500%"
    width: str  # CSS percentage

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class GanttTick:
    day: date
    left: str


@dataclass(frozen=True)
class GanttChart:
    start: date | None
    end: date | None
    days: int                 # timeline length, both ends included
    rows: list[GanttRow]
    ticks: list[GanttTick]
    today_left: str | None    # where the "today" line goes, if today is on the chart
    unscheduled: list[object]  # tasks with no dates yet (shouldn't happen with saved data)


def _pct(value: float) -> str:
    return f"{value:.3f}%"


def build_chart(tasks: Sequence, today: date,
                dates: Callable[[object], tuple[date | None, date | None]] = task_dates) -> GanttChart:
    spans = [(t, *dates(t)) for t in tasks]
    scheduled = [(t, s, e) for t, s, e in spans if s and e]
    unscheduled = [t for t, s, e in spans if not (s and e)]
    if not scheduled:
        return GanttChart(None, None, 0, [], [], None, unscheduled)

    start = min(s for _, s, _ in scheduled)
    end = max(e for _, _, e in scheduled)
    days = (end - start).days + 1

    def left_of(day: date) -> float:
        return (day - start).days / days * 100

    rows = [GanttRow(t, s, e, _pct(left_of(s)), _pct(((e - s).days + 1) / days * 100))
            for t, s, e in scheduled]

    step = 1 if days <= DAILY_TICKS_UP_TO else 7
    ticks = [GanttTick(start + timedelta(days=d), _pct(left_of(start + timedelta(days=d))))
             for d in range(0, days, step)]

    # The line sits in the middle of today's column.
    today_left = _pct(left_of(today) + 50 / days) if start <= today <= end else None
    return GanttChart(start, end, days, rows, ticks, today_left, unscheduled)
