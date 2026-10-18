"""Scheduling engine: a pure-Python module with no Django imports.

Responsibilities (one concern: "given tasks + dependencies, work out the
schedule"):
  * build the dependency graph            graph.py
  * cycle detection + task ordering       graph.py
  * dates for each task (forward pass)    scheduler.py
  * critical path / slack (backward pass) critical_path.py

Other modules should import only what is listed here (the module's public
interface), never reach into graph.py or scheduler.py internals directly.
"""
from .graph import CycleError
from .scheduler import ScheduledTask, ScheduleResult, Scheduler, TaskNode

__all__ = ["CycleError", "ScheduledTask", "ScheduleResult", "Scheduler", "TaskNode"]
