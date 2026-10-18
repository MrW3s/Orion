"""Critical path: the backward pass of the Critical Path Method.

The forward pass in scheduler.py gives each task its earliest start. This
walks the tasks in reverse order to find the latest each one can start
without pushing back the project end. Slack is the gap between the two:
how many days a task can slip for free. Slack 0 means the task is on the
critical path, so any delay to it delays the whole project.

Like graph.py and scheduler.py, this module has no Django imports.
"""
from __future__ import annotations

from datetime import date, timedelta

from .graph import DependencyGraph


def analyse(graph: DependencyGraph, order, tasks_by_id, slots, project_end: date):
    """Return {task_id: (slack_days, is_critical)}."""
    latest_start: dict = {}
    result: dict = {}

    for task_id in reversed(order):
        succs = graph.successors(task_id)

        # Latest finish: the project end, or the day before the earliest
        # latest-start among the tasks waiting on this one.
        if not succs:
            latest_finish = project_end
        else:
            latest_finish = min(latest_start[s] for s in succs) - timedelta(days=1)

        # Same max(duration, 1) guard as the forward pass in scheduler.py
        duration = max(tasks_by_id[task_id].duration_days, 1)
        this_latest_start = latest_finish - timedelta(days=duration - 1)
        latest_start[task_id] = this_latest_start

        slack = (this_latest_start - slots[task_id].start).days
        is_critical = (slack == 0)
        result[task_id] = (slack, is_critical)

    return result
