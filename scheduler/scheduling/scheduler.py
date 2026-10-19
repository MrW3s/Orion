"""Turns a set of tasks + dependencies into concrete start/end dates.

Uses a forward pass (as in the Critical Path Method): a task starts on the
project start date, its own earliest start date (if it has one), or the day
after its latest predecessor finishes, whichever is latest.

Like graph.py, this module has no Django imports. The tasks app hands it
plain TaskNode values and gets a plain ScheduleResult back, so the only
coupling between the two is that data (data coupling, the loosest kind).

After the forward pass, compute() runs the backward pass in critical_path.py
(PM critical-path story) to give each task its slack, and lists the
critical tasks (slack 0) in ScheduleResult.critical_path.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Hashable, Iterable

from .critical_path import analyse
from .graph import DependencyGraph

TaskId = Hashable


@dataclass(frozen=True)
class TaskNode:
    """What the scheduler needs to know about a task, and nothing more."""

    id: TaskId
    duration_days: int
    depends_on: frozenset[TaskId] = field(default_factory=frozenset)
    earliest_start: date | None = None  # "don't start before", e.g. the date a user picked


@dataclass(frozen=True)
class ScheduledTask:
    id: TaskId
    start: date  # earliest start (forward pass)
    end: date    # earliest finish, inclusive: a 1-day task starts and ends the same day
    slack_days: int = 0        # days it can slip without delaying the project end
    is_critical: bool = False  # slack 0: any delay here delays the whole project


@dataclass(frozen=True)
class ScheduleResult:
    """Everything the engine computed for one project."""

    order: list[TaskId]                 # valid task ordering (topological)
    tasks: dict[TaskId, ScheduledTask]  # dates per task
    critical_path: list[TaskId] = field(default_factory=list)  # critical tasks, in order

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
            start = max(project_start, task.earliest_start or project_start)
            for dep in task.depends_on:
                start = max(start, slots[dep].end + timedelta(days=1))
            end = start + timedelta(days=max(task.duration_days, 1) - 1)
            slots[task_id] = ScheduledTask(task_id, start, end)

        # Backward pass: how far each task can slip before the project end moves.
        project_end = max((s.end for s in slots.values()), default=project_start)
        for task_id, (slack, critical) in analyse(graph, order, tasks_by_id, slots, project_end).items():
            slots[task_id] = replace(slots[task_id], slack_days=slack, is_critical=critical)

        critical_path = [t for t in order if slots[t].is_critical]
        return ScheduleResult(order=order, tasks=slots, critical_path=critical_path)

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
