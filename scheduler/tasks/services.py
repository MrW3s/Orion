"""Use cases for tasks: the two user stories in Sprint 1, plus the PM story.

    Story 1  add_task()       Given a team member is on the site,
                              when they add a new task (name, start and end date),
                              then it appears in the schedule as Not started
                              with its dependencies saved. Without a name or
                              dates: an error, and nothing is added.

    Story 2  update_status()  Given a user is viewing their schedule,
                              when they change a task's status,
                              then it is saved and shown immediately to
                              every relevant team member.

    PM story risk_report()    Given a schedule with tasks, the project manager
                              sees the task ordering and the critical path (the
                              tasks that delay the project if they slip).
             set_dependencies()
                              When a dependency would create a cycle, it is
                              flagged and rejected, so ordering and critical
                              path are never calculated on a looping schedule.

TaskService depends on its collaborators through the constructor
(repository, scheduler, access, publisher) rather than creating them itself.
That keeps coupling low: each one can be swapped, e.g. an in-memory
publisher in tests, without editing this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db import transaction

from accounts.services import RoleService
from common.errors import InvalidDependency, InvalidTask, NotAllowed
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
    start_date: date
    end_date: date
    description: str = ""
    assignee_id: int | None = None
    depends_on_ids: list[int] = field(default_factory=list)

    @property
    def duration_days(self) -> int:
        """The duration estimate. Both dates count, so Mon to Wed is 3 days."""
        return (self.end_date - self.start_date).days + 1


@dataclass(frozen=True)
class RiskReport:
    """What the PM sees for one project (PM story)."""

    order: list[Task]          # every task, in a valid dependency order
    critical_path: list[Task]  # the tasks that delay the project end if they slip
    project_end: date | None


class TaskService:
    def __init__(self, repository: TaskRepository, scheduler: Scheduler,
                 access: ProjectAccess, publisher: EventPublisher,
                 roles: RoleService | None = None):
        self._repo = repository
        self._scheduler = scheduler
        self._access = access
        self._publisher = publisher
        self._roles = roles or RoleService()

    # ---- Viewing the schedule (used by both stories) -------------------
    def get_project(self, user, project_id: int):
        self._access.require_member(user, project_id)
        return self._access.get_project(project_id)

    def list_schedule(self, user, project_id: int) -> list[Task]:
        self._access.require_member(user, project_id)
        return self._repo.list_for_project(project_id)

    # ---- Story 1 -----------------------------------------------------
    def add_task(self, user, project_id: int, new: NewTask) -> Task:
        self._access.require_member(user, project_id)
        self._check_name_and_dates(project_id, new)
        if new.assignee_id is not None and not self._access.is_member_id(new.assignee_id, project_id):
            raise InvalidTask("Assignee must be a member of the project")
        self._check_dependencies_in_project(project_id, new.depends_on_ids)

        with transaction.atomic():
            task = self._repo.create(
                project_id=project_id, created_by=user, title=new.title,
                description=new.description, duration_days=new.duration_days,
                planned_start=new.start_date, assignee_id=new.assignee_id,
                depends_on_ids=new.depends_on_ids,
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

    # ---- PM story ----------------------------------------------------
    def can_view_risk(self, user) -> bool:
        return self._roles.can(user, "view_risk")

    def risk_report(self, user, project_id: int) -> RiskReport:
        self._access.require_member(user, project_id)
        if not self.can_view_risk(user):
            raise NotAllowed("Only project managers and administrators can view schedule risk")

        project = self._access.get_project(project_id)
        tasks = self._repo.list_for_project(project_id)
        # Saved data never has a cycle (set_dependencies rejects those), so this can't raise.
        result = self._scheduler.compute(project.start_date, self._nodes(tasks))
        by_id = {t.pk: t for t in tasks}
        return RiskReport(
            order=[by_id[t] for t in result.order],
            critical_path=[by_id[t] for t in result.critical_path],
            project_end=result.project_end,
        )

    def set_dependencies(self, user, task_id: int, depends_on_ids: list[int]) -> Task:
        """Replace what a task depends on. A cycle is rejected and nothing changes."""
        task = self._repo.get(task_id)
        self._access.require_member(user, task.project_id)
        self._check_dependencies_in_project(task.project_id, depends_on_ids)

        with transaction.atomic():
            self._repo.set_dependencies(task, depends_on_ids)
            self._reschedule(task.project_id)  # raises InvalidDependency on a cycle -> rollback
            transaction.on_commit(lambda: self._publisher.publish(
                ProjectEvent.schedule_changed(task.project_id, reason="dependencies_changed",
                                              task_id=task.pk)
            ))

        task.refresh_from_db()
        return task

    # ---- helpers -----------------------------------------------------
    def _check_name_and_dates(self, project_id: int, new: NewTask) -> None:
        if not new.title.strip():
            raise InvalidTask("Give the task a name")
        if new.end_date < new.start_date:
            raise InvalidTask("The end date can't be before the start date")
        project_start = self._access.get_project(project_id).start_date
        if new.start_date < project_start:
            raise InvalidTask(f"The start date can't be before the project starts "
                              f"({project_start:%b %d, %Y})")

    def _check_dependencies_in_project(self, project_id: int, dep_ids: list[int]) -> None:
        found = self._repo.ids_in_project(project_id, dep_ids)
        missing = set(dep_ids) - found
        if missing:
            raise InvalidDependency(f"Tasks {sorted(missing)} are not in this project")

    def _reschedule(self, project_id: int) -> None:
        """Rebuild the project's dependency graph and store the new dates.

        This is the single place a "task committed to the schedule" triggers
        the engine: cycle detection, ordering, dates, slack and critical path
        all come back in one ScheduleResult and are saved via the repository.
        """
        project = self._access.get_project(project_id)
        tasks = self._repo.list_for_project(project_id)
        try:
            result = self._scheduler.compute(project.start_date, self._nodes(tasks))
        except CycleError as exc:
            # Raising inside transaction.atomic() rolls the change back, so the
            # saved schedule (and its critical path) stays the last valid one.
            titles = {t.pk: t.title for t in tasks}
            loop = " → ".join(titles[n] for n in exc.nodes + exc.nodes[:1])
            raise InvalidDependency(
                f"Circular dependency: {loop}. Remove one of these dependencies "
                f"before the schedule can be ordered."
            ) from exc
        self._repo.save_schedule(result)

    @staticmethod
    def _nodes(tasks: list[Task]) -> list[TaskNode]:
        return [
            TaskNode(id=t.pk, duration_days=t.duration_days,
                     depends_on=frozenset(d.pk for d in t.depends_on.all()),
                     earliest_start=t.planned_start)
            for t in tasks
        ]
