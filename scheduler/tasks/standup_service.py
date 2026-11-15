"""Use case for the standup story: everything a daily standup reviews, in one call.

    Standup story  standup()     Given a Scrum Master running a daily standup,
                                 when they open a project's standup page,
                                 then they see what happened since the last
                                 standup: summary tiles (with the change against
                                 the window before), an activity timeline, a card
                                 per person, schedule health and the blockers.
                   save_order()  The speaking order of the cards, shared by the project.

Only project members may see it (ProjectAccess). Every section reads the same
snapshot (the project's tasks, plus the activity log from the start of the
previous window) and is built on its own: if one fails, it comes back as
{"error": ...} and the others still render.

The critical path comes from the scheduling engine (Scheduler.compute), the
same one that writes the saved schedule. Window and grouping rules are in
standup.py. Queries go through TaskRepository; no ORM here.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from django.utils import timezone

from accounts.services import RoleService
from common.errors import InvalidStandupOrder
from projects.access import ProjectAccess
from scheduling import Scheduler

from .models import Task, TaskEventKind, TaskKind, TaskStatus
from .repository import TaskRepository
from .services import schedule_nodes
from .standup import WINDOWS, Window, build_window, group_markers, value_at, working_days_between

log = logging.getLogger(__name__)

SECTIONS = ("tiles", "tasks", "timeline", "people", "schedule_health", "blockers")
STALE_BLOCKED_DAYS = 2  # blocked longer than this many working days is highlighted
STATUS_EVENTS = {TaskEventKind.IN_PROGRESS, TaskEventKind.DONE, TaskEventKind.REOPENED}
BLOCK_EVENTS = {TaskEventKind.BLOCKED, TaskEventKind.UNBLOCKED}
TIMELINE_EVENTS = [TaskEventKind.CREATED, TaskEventKind.IN_PROGRESS, TaskEventKind.DONE,
                   TaskEventKind.BLOCKED, TaskEventKind.UNBLOCKED, TaskEventKind.REASSIGNED,
                   TaskEventKind.REOPENED]
FORECAST_UNAVAILABLE = ("Monte Carlo forecasting isn't built yet, so there's no on-time "
                        "probability to show.")


@dataclass
class _Snapshot:
    """What every section reads. Built once per request."""

    project: object
    window: Window
    previous: Window
    now: datetime
    tz: tzinfo
    tasks: list[Task]
    by_id: dict[int, Task]
    events: list            # every event since previous.start, oldest first
    members: list           # the people with a card, in speaking order

    @property
    def today(self) -> date:
        return self.now.astimezone(self.tz).date()

    def in_window(self, window: Window, kinds=None):
        return [e for e in self.events if window.contains(e.created_at)
                and (kinds is None or e.kind in kinds)]


class StandupService:
    def __init__(self, repository: TaskRepository, scheduler: Scheduler,
                 access: ProjectAccess, roles: RoleService | None = None):
        self._repo = repository
        self._scheduler = scheduler
        self._access = access
        self._roles = roles or RoleService()

    # ---- Use cases ---------------------------------------------------
    def standup(self, user, project_id: int, window: str | None = None,
                start: date | None = None, end: date | None = None,
                sections: list[str] | None = None, now: datetime | None = None) -> dict:
        self._access.require_member(user, project_id)
        now = now or timezone.now()
        tz = timezone.get_current_timezone()
        win = build_window(window, now, tz, start, end)  # raises InvalidWindow
        snap = self._snapshot(project_id, win, now, tz)

        out = {
            "project": {"id": snap.project.pk, "name": snap.project.name},
            "window": self._window_json(win),
            "previous_window": self._window_json(snap.previous),
            "generated_at": now,
        }
        builders = {"tiles": self._tiles, "tasks": self._task_list, "timeline": self._timeline,
                    "people": self._people, "schedule_health": self._schedule_health,
                    "blockers": self._blockers}
        for name in [s for s in SECTIONS if not sections or s in sections]:
            try:
                out[name] = builders[name](snap)
            except Exception:  # one broken section mustn't blank the page
                log.exception("Standup section %s failed for project %s", name, project_id)
                out[name] = {"error": "This section couldn't be loaded."}
        return out

    def save_order(self, user, project_id: int, user_ids: list[int]) -> list[int]:
        """Save the card order. Members left out keep their place after the ones given."""
        self._access.require_member(user, project_id)
        members = [u.pk for u in self._members(project_id, order=[])]
        if len(set(user_ids)) != len(user_ids):
            raise InvalidStandupOrder("Each person can appear only once")
        unknown = set(user_ids) - set(members)
        if unknown:
            raise InvalidStandupOrder(f"Users {sorted(unknown)} aren't on this project's team")
        order = list(user_ids) + [m for m in members if m not in user_ids]
        self._repo.save_standup_order(project_id, order)
        return order

    def window_choices(self) -> dict[str, str]:
        return dict(WINDOWS)

    # ---- Loading -----------------------------------------------------
    def _snapshot(self, project_id: int, win: Window, now: datetime, tz: tzinfo) -> _Snapshot:
        tasks = self._repo.list_for_project(project_id)
        previous = win.previous()
        return _Snapshot(
            project=self._access.get_project(project_id), window=win, previous=previous,
            now=now, tz=tz, tasks=tasks, by_id={t.pk: t for t in tasks},
            events=self._repo.events_since(project_id, previous.start),
            members=self._members(project_id, self._repo.standup_order(project_id)),
        )

    def _members(self, project_id: int, order: list[int]) -> list:
        """Team members (never clients) in the saved order; anyone new goes last, by name."""
        people = [u for u in self._access.get_project(project_id).members.order_by("username")
                  if self._roles.can(u, "update_status")]
        rank = {uid: i for i, uid in enumerate(order)}
        return sorted(people, key=lambda u: rank.get(u.pk, len(rank)))

    # ---- What a task looked like at a moment (for the "previous" numbers) ----
    def _state_at(self, snap: _Snapshot, moment: datetime):
        """{task id: (status, due, blocked)} as they were just before `moment`, for every
        task that existed then. Rebuilt from the log: the old value of the first change
        after `moment`, else today's value."""
        by_task = defaultdict(list)
        for e in snap.events:
            by_task[e.task_id].append(e)
        state = {}
        for t in snap.tasks:
            if t.created_at >= moment:
                continue
            log_ = by_task.get(t.pk, [])
            status = value_at(moment, t.status,
                              [(e.created_at, e.old_value) for e in log_ if e.kind in STATUS_EVENTS])
            due = value_at(moment, t.scheduled_end,
                           [(e.created_at, date.fromisoformat(e.old_value)) for e in log_
                            if e.kind == TaskEventKind.RESCHEDULED])
            # Blocked before a BLOCKED event only if it carried an old reason (a re-block).
            blocked = value_at(moment, t.is_blocked,
                               [(e.created_at, e.kind == TaskEventKind.UNBLOCKED or bool(e.old_value))
                                for e in log_ if e.kind in BLOCK_EVENTS])
            state[t.pk] = (status, due, blocked)
        return state

    # ---- Sections ----------------------------------------------------
    def _tiles(self, snap: _Snapshot) -> list[dict]:
        member_ids = {m.pk for m in snap.members}

        def measure(win: Window) -> dict[str, set[int]]:
            events = snap.in_window(win)
            state = self._state_at(snap, win.end)
            day = win.end.astimezone(snap.tz).date()
            active = {e.actor_id for e in events if e.actor_id in member_ids}
            return {
                "completed": {e.task_id for e in events if e.kind == TaskEventKind.DONE},
                "in_progress": {e.task_id for e in events if e.kind == TaskEventKind.IN_PROGRESS},
                "blocked": {tid for tid, (_, _, blocked) in state.items() if blocked},
                "active_members": active,
                "overdue": {tid for tid, (status, due, _) in state.items()
                            if status != TaskStatus.COMPLETE and due is not None and due < day},
                "bugs_created": {t.pk for t in snap.tasks
                                 if t.kind == TaskKind.BUG and win.contains(t.created_at)},
            }, events

        (now_sets, events), (before, _) = measure(snap.window), measure(snap.previous)
        labels = {"completed": "Tasks completed", "in_progress": "Moved to In progress",
                  "blocked": "Currently blocked", "active_members": "Active members",
                  "overdue": "Overdue", "bugs_created": "Bugs created"}
        tiles = []
        for key, label in labels.items():
            ids = now_sets[key]
            if key == "active_members":
                # Clicking it shows the tasks those people touched in the window.
                task_ids = {e.task_id for e in events if e.actor_id in ids}
            else:
                task_ids = ids
            tiles.append({"key": key, "label": label, "count": len(ids),
                          "previous": len(before[key]), "delta": len(ids) - len(before[key]),
                          "task_ids": sorted(task_ids)})
        return tiles

    def _task_list(self, snap: _Snapshot) -> list[dict]:
        rows = [self._task_json(t, snap) for t in snap.tasks]
        return sorted(rows, key=lambda r: (r["due"] or date.max, r["id"]))

    def _timeline(self, snap: _Snapshot) -> dict:
        items = [{"at": e.created_at, "kind": e.kind, "task_id": e.task_id,
                  "task": snap.by_id[e.task_id].title if e.task_id in snap.by_id else "(deleted)",
                  "person": e.actor.username if e.actor else "Someone"}
                 for e in snap.in_window(snap.window, TIMELINE_EVENTS)]
        grouped, markers = group_markers(items, snap.tz)
        return {
            "start": snap.window.start, "end": snap.window.end,
            "event_count": len(items), "grouped": grouped,
            "legend": [{"kind": k, "label": TaskEventKind(k).label} for k in TIMELINE_EVENTS],
            "markers": [{"at": m.at, "kind": m.kind, "count": m.count, "events": m.events}
                        for m in markers],
        }

    def _people(self, snap: _Snapshot) -> list[dict]:
        window_events = snap.in_window(snap.window)
        cards = []
        for person in snap.members:
            def theirs(task_id):
                task = snap.by_id.get(task_id)
                return task is not None and task.assignee_id == person.pk
            completed = []
            for e in window_events:
                if e.kind == TaskEventKind.DONE and theirs(e.task_id) \
                        and e.task_id not in [c["id"] for c in completed]:
                    completed.append(self._brief(snap.by_id[e.task_id]))
            mine = [t for t in snap.tasks if t.assignee_id == person.pk]
            cards.append({
                "user_id": person.pk, "name": person.get_username(),
                "active": any(e.actor_id == person.pk or theirs(e.task_id) for e in window_events),
                "completed": completed,
                "in_progress": [self._brief(t) for t in mine if t.status == TaskStatus.IN_PROGRESS],
                "blocked": [{**self._brief(t), "reason": t.blocked_reason}
                            for t in mine if t.is_blocked],
            })
        return cards

    def _schedule_health(self, snap: _Snapshot) -> dict:
        # Reuse the engine: the same compute() the saved schedule comes from.
        result = self._scheduler.compute(snap.project.start_date, schedule_nodes(snap.tasks))
        critical = set(result.critical_path)

        moves: dict[int, list] = {}  # task id -> [first old due, last new due] in the window
        for e in snap.in_window(snap.window, {TaskEventKind.RESCHEDULED}):
            old, new = date.fromisoformat(e.old_value), date.fromisoformat(e.new_value)
            moves.setdefault(e.task_id, [old, new])[1] = new

        def moved(tid):
            old, new = moves[tid]
            return {**self._brief(snap.by_id[tid]), "from": old, "to": new,
                    "days": (new - old).days}

        slipped = [tid for tid in result.critical_path
                   if tid in moves and moves[tid][1] > moves[tid][0]]
        # Tasks downstream of a slipped critical task (they depend on it, directly or
        # not) whose own dates moved in the window.
        dependents = defaultdict(set)
        for t in snap.tasks:
            for dep in t.depends_on.all():
                dependents[dep.pk].add(t.pk)
        downstream: dict[int, set[int]] = defaultdict(set)
        for source in slipped:
            stack, seen = [source], set()
            while stack:
                for nxt in dependents[stack.pop()] - seen:
                    seen.add(nxt)
                    stack.append(nxt)
            for tid in seen:
                if tid in moves and tid not in slipped:
                    downstream[tid].add(source)

        return {
            "project_end": result.project_end,
            "critical_path": [{**self._brief(snap.by_id[tid]), "due": result.tasks[tid].end,
                               "status": snap.by_id[tid].status,
                               "slipped": tid in slipped}
                              for tid in result.critical_path],
            "slipped": [moved(tid) for tid in slipped],
            "downstream_moved": [{**moved(tid), "because_of": [snap.by_id[s].title
                                                               for s in sorted(srcs)]}
                                 for tid, srcs in sorted(downstream.items())],
            "forecast": {"available": False, "reason": FORECAST_UNAVAILABLE},
            "critical_count": len(critical),
        }

    def _blockers(self, snap: _Snapshot) -> list[dict]:
        blocked = sorted((t for t in snap.tasks if t.is_blocked), key=lambda t: (t.blocked_since, t.pk))
        rows = []
        for t in blocked:
            days = working_days_between(t.blocked_since.astimezone(snap.tz).date(), snap.today)
            rows.append({**self._brief(t), "owner": t.assignee.username if t.assignee else None,
                         "reason": t.blocked_reason, "since": t.blocked_since,
                         "days_blocked": days, "stale": days > STALE_BLOCKED_DAYS})
        return rows

    # ---- JSON helpers --------------------------------------------------
    @staticmethod
    def _window_json(win: Window) -> dict:
        return {"key": win.key, "label": win.label, "start": win.start, "end": win.end}

    @staticmethod
    def _brief(task: Task) -> dict:
        return {"id": task.pk, "title": task.title}

    @staticmethod
    def _task_json(t: Task, snap: _Snapshot) -> dict:
        return {
            "id": t.pk, "title": t.title, "kind": t.kind, "status": t.status,
            "status_label": t.status_label,
            "assignee": t.assignee.username if t.assignee else None,
            "due": t.scheduled_end, "is_critical": t.is_critical, "blocked": t.is_blocked,
            "overdue": (t.status != TaskStatus.COMPLETE and t.scheduled_end is not None
                        and t.scheduled_end < snap.today),
        }
