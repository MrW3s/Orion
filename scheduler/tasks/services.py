"""Use cases for tasks: the two user stories in Sprint 1.

    Story 1  add_task()       Given a team member is on the site,
                              when they add a new task,
                              then the graph puts the task into the schedule.

    Story 2  update_status()  Given a user is viewing their schedule,
                              when they change a task's status,
                              then it is saved and shown immediately to
                              every relevant team member.

TaskService depends on its collaborators through the constructor
(repository, scheduler, access, publisher) rather than creating them itself.
That keeps coupling low: each one can be swapped, e.g. an in-memory
publisher in tests, without editing this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from common.errors import InvalidDependency, InvalidTask
from notifications.events import ProjectEvent
from notifications.publisher import EventPublisher
from projects.access import ProjectAccess
from scheduling import CycleError, Scheduler, TaskNode

from .models import Task, TaskStatus
from .repository import TaskRepository


@dataclass(frozen=True)
class NewTask:
    """Input for story 1, already validated for shape by the API layer."""

    title: str
    description: str = ""
    duration_days: int = 1
    assignee_id: int | None = None
    depends_on_ids: list[int] = field(default_factory=list)


class TaskService:
    def __init__(self, repository: TaskRepository, scheduler: Scheduler,
                 access: ProjectAccess, publisher: EventPublisher):
        self._repo = repository
        self._scheduler = scheduler
        self._access = access
        self._publisher = publisher

    # ---- Viewing the schedule (used by both stories) -------------------
    def list_schedule(self, user, project_id: int) -> list[Task]:
        self._access.require_member(user, project_id)
        return self._repo.list_for_project(project_id)

    # ---- Story 1 -----------------------------------------------------
    def add_task(self, user, project_id: int, new: NewTask) -> Task:
        self._access.require_member(user, project_id)
        if new.assignee_id is not None and not self._access.is_member_id(new.assignee_id, project_id):
            raise InvalidTask("Assignee must be a member of the project")
        self._check_dependencies_in_project(project_id, new.depends_on_ids)

        with transaction.atomic():
            task = self._repo.create(
                project_id=project_id, created_by=user, title=new.title,
                description=new.description, duration_days=new.duration_days,
                assignee_id=new.assignee_id, depends_on_ids=new.depends_on_ids,
            )
            self._reschedule(project_id)
            # Only tell other clients once the data is really saved.
            transaction.on_commit(lambda: self._publisher.publish(
                ProjectEvent.schedule_changed(project_id, reason="task_added", task_id=task.pk)
            ))

        task.refresh_from_db()
        return task

    # ---- Story 2 -----------------------------------------------------
    def update_status(self, user, task_id: int, status: str) -> Task:
        if status not in TaskStatus.values:
            raise InvalidTask(f"Unknown status {status!r}")
        task = self._repo.get(task_id)
        self._access.require_member(user, task.project_id)

        if task.status == status:
            return task  # nothing changed, nothing to broadcast

        with transaction.atomic():
            task = self._repo.save_status(task, status)
            transaction.on_commit(lambda: self._publisher.publish(
                ProjectEvent.status_changed(task.project_id, task_id=task.pk,
                                            status=task.status, changed_by=user.pk)
            ))
        return task

    # ---- helpers -----------------------------------------------------
    def _check_dependencies_in_project(self, project_id: int, dep_ids: list[int]) -> None:
        found = self._repo.ids_in_project(project_id, dep_ids)
        missing = set(dep_ids) - found
        if missing:
            raise InvalidDependency(f"Tasks {sorted(missing)} are not in this project")

    def _reschedule(self, project_id: int) -> None:
        """Rebuild the project's dependency graph and store the new dates.

        This is the single place a "task committed to the schedule" triggers
        the engine. The future PM story (cycle detection, ordering, critical
        path for risk) plugs in here: anything new the engine returns in
        ScheduleResult gets saved via the repository, with no new call sites.
        """
        project = self._access.get_project(project_id)
        tasks = self._repo.list_for_project(project_id)
        nodes = [
            TaskNode(id=t.pk, duration_days=t.duration_days,
                     depends_on=frozenset(d.pk for d in t.depends_on.all()))
            for t in tasks
        ]
        try:
            result = self._scheduler.compute(project.start_date, nodes)
        except CycleError as exc:
            # Raising inside transaction.atomic() rolls the new task back.
            raise InvalidDependency(str(exc)) from exc
        self._repo.save_schedule(result)
