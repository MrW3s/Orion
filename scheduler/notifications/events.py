"""Messages pushed to everyone watching a project.

Each event is a small, plain value. The services decide WHEN to send one;
this module only decides WHAT it looks like on the wire. The browser
(React) relies only on this format, never on Django models.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProjectEvent:
    project_id: int
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def group_name(self) -> str:
        """Channels group that every member viewing this project joins."""
        return f"project_{self.project_id}"

    def to_message(self) -> dict[str, Any]:
        return asdict(self)

    # --- factory methods: one per kind of event --------------------------
    @classmethod
    def schedule_changed(cls, project_id: int, *, reason: str, task_id: int) -> "ProjectEvent":
        # Clients re-fetch the schedule: one new task can move many dates.
        return cls(project_id, "schedule.changed", {"reason": reason, "task_id": task_id})

    @classmethod
    def status_changed(cls, project_id: int, *, task_id: int, status: str,
                       changed_by: int) -> "ProjectEvent":
        return cls(project_id, "task.status_changed",
                   {"task_id": task_id, "status": status, "changed_by": changed_by})
