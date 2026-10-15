"""Turns a set of tasks + dependencies into concrete start/end dates.

Uses a forward pass (as in the Critical Path Method): a task starts on the
project start date, or the day after its latest predecessor finishes,
whichever is later.

Like graph.py, this module has no Django imports. The tasks app hands it
plain TaskNode values and gets a plain ScheduleResult back, so the only
coupling between the two is that data (data coupling, the loosest kind).

FUTURE (PM critical-path story): the forward pass here already gives each
task's earliest start/finish. Critical path = add a backward pass in a new
module, critical_path.py (latest start/finish -> slack; slack == 0 means
critical). Its output goes into the extra ScheduleResult fields marked
below. Because callers only depend on ScheduleResult, adding those fields
doesn't change TaskService or the API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Hashable, Iterable

from .graph import DependencyGraph

TaskId = Hashable


@dataclass(frozen=True)
class TaskNode:
    """What the scheduler needs to know about a task, and nothing more."""

    id: TaskId
    duration_days: int
    depends_on: frozenset[TaskId] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ScheduledTask:
    id: TaskId
    start: date  # earliest start (forward pass)
    end: date    # earliest finish, inclusive: a 1-day task starts and ends the same day
    # FUTURE: slack_days: int = 0 ; is_critical: bool = False


@dataclass(frozen=True)
class ScheduleResult:
    """Everything the engine computed for one project."""

    order: list[TaskId]                 # valid task ordering (topological)
    tasks: dict[TaskId, ScheduledTask]  # dates per task
    # FUTURE: critical_path: list[TaskId] = field(default_factory=list)

    @property
    def project_end(self) -> date | None:
        return max((t.end for t in self.tasks.values()), default=None)


class Scheduler:
    def compute(self, project_start: date, tasks: Iterable[TaskNode]) -> ScheduleResult:
        tasks_by_id = {t.id: t for t in tasks}
        graph = self._build_graph(tasks_by_id)
        order = graph.topological_order()  # raises CycleError (cycle detection)

        slots: dict[TaskId, ScheduledTask] = {}
        for task_id in order:
            task = tasks_by_id[task_id]
            start = project_start
            for dep in task.depends_on:
                start = max(start, slots[dep].end + timedelta(days=1))
            end = start + timedelta(days=max(task.duration_days, 1) - 1)
            slots[task_id] = ScheduledTask(task_id, start, end)

        # FUTURE: critical = critical_path.analyse(graph, order, tasks_by_id, slots)
        return ScheduleResult(order=order, tasks=slots)

    @staticmethod
    def _build_graph(tasks_by_id: dict[TaskId, TaskNode]) -> DependencyGraph:
        graph = DependencyGraph()
        for task in tasks_by_id.values():
            graph.add_node(task.id)
            for dep in task.depends_on:
                if dep not in tasks_by_id:
                    raise KeyError(f"Task {task.id!r} depends on unknown task {dep!r}")
                graph.add_dependency(task.id, dep)
        return graph
