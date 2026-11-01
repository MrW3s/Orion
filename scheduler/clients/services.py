"""Use cases for the client dashboard story.

    As a client, I want my own dashboard that is view only, so that I can
    submit new requests and view progress.

    Given a client opens their project,
    then they can view its progress,
    and they can't see internal project details.

    Given a client is signed in,
    when they try to view a project owned by another party,
    then they're told it's out of scope for their permissions
    and sent to their own project.

"Submit new requests" is a note the client leaves for the people working
on the project; the team sees it on the schedule page.

Gantt story: the dashboard also shows the project's Gantt chart (one bar per
task, in dependency order) built from the same ClientTask values, so it has
names, status and dates but no assignees. If it looks wrong, the client
reports it to the scrum master with report_gantt_problem().

What a client may see is decided only here: ClientProject and ClientTask
list every field that reaches the dashboard. Assignees, descriptions,
dependencies, slack and the team members never leave this module
(information hiding), so a template can't show them by accident.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from accounts.services import RoleService
from common.errors import InvalidNote, NotAllowed
from projects.access import ProjectAccess
from projects.models import ClientNote, Project
from tasks.models import GanttReport, TaskStatus
from tasks.repository import TaskRepository
from tasks.services import TaskService


@dataclass(frozen=True)
class ClientTask:
    title: str
    status: str        # "todo" / "in_progress" / "complete", for the status colour
    status_label: str  # "Not started" / "In progress" / "Complete"
    start: date | None
    end: date | None


@dataclass(frozen=True)
class Note:
    text: str
    created_at: datetime


@dataclass(frozen=True)
class ClientProject:
    """Everything the client's dashboard shows for one project, and nothing more."""

    id: int
    name: str
    start_date: date
    tasks: list[ClientTask]
    notes: list[Note]  # the notes this client has left, newest first
    gantt: list[ClientTask] = field(default_factory=list)  # the same tasks, in dependency order

    @property
    def complete(self) -> int:
        return sum(t.status == TaskStatus.COMPLETE for t in self.tasks)

    @property
    def in_progress(self) -> int:
        return sum(t.status == TaskStatus.IN_PROGRESS for t in self.tasks)

    @property
    def percent(self) -> int:
        return round(100 * self.complete / len(self.tasks)) if self.tasks else 0

    @property
    def expected_end(self) -> date | None:
        return max((t.end for t in self.tasks if t.end), default=None)


class ClientDashboardService:
    def __init__(self, roles: RoleService | None = None, access: ProjectAccess | None = None,
                 tasks: TaskRepository | None = None, task_service: TaskService | None = None):
        self._roles = roles or RoleService()
        self._access = access or ProjectAccess(self._roles)
        self._tasks = tasks or TaskRepository()
        self._task_service = task_service

    def projects(self, user) -> list[Project]:
        """The projects this client owns."""
        self._require_client(user)
        return self._access.owned_projects(user)

    def project(self, user, project_id: int) -> ClientProject:
        self._require_client(user)
        project = self._access.require_owner(user, project_id)  # else ProjectOutOfScope
        return ClientProject(
            id=project.pk, name=project.name, start_date=project.start_date,
            tasks=[self._client_task(t) for t in self._tasks.list_for_project(project.pk)],
            notes=[Note(n.text, n.created_at)
                   for n in ClientNote.objects.filter(project=project, author=user)],
            gantt=[self._client_task(t)
                   for t in self._tasks_service().tasks_in_dependency_order(project.pk)],
        )

    def report_gantt_problem(self, user, project_id: int, message: str) -> GanttReport:
        """The client says their project's Gantt chart looks wrong (Gantt story)."""
        self._require_client(user)
        project = self._access.require_owner(user, project_id)
        if not self._roles.can(user, "report_gantt"):
            raise NotAllowed("Your role can't report Gantt chart problems")
        return self._tasks_service().file_gantt_report(project.pk, user, message)

    def add_note(self, user, project_id: int, text: str) -> None:
        self._require_client(user)
        project = self._access.require_owner(user, project_id)
        if not text.strip():
            raise InvalidNote("Write a note first")
        ClientNote.objects.create(project=project, author=user, text=text.strip())

    @staticmethod
    def _client_task(t) -> ClientTask:
        # The only place a Task becomes something a client sees.
        return ClientTask(t.title, t.status, t.get_status_display(),
                          t.scheduled_start, t.scheduled_end)

    def _tasks_service(self) -> TaskService:
        if self._task_service is None:
            from tasks.container import task_service  # the real collaborators, built on first use
            self._task_service = task_service()
        return self._task_service

    def _require_client(self, user) -> None:
        if not self._roles.can(user, "client_dashboard"):
            raise NotAllowed("Only clients have a client dashboard")
