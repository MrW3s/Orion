from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from projects.models import Project


class TaskStatus(models.TextChoices):
    TODO = "todo", "Not started"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETE = "complete", "Complete"


class TaskKind(models.TextChoices):
    TASK = "task", "Task"
    BUG = "bug", "Bug"


class Task(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_tasks",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="created_tasks",
    )
    duration_days = models.PositiveIntegerField(default=1)
    # The start date the user picked. The engine never schedules the task
    # earlier, but may move it later if a dependency isn't finished by then.
    planned_start = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.TODO)
    kind = models.CharField(max_length=10, choices=TaskKind.choices, default=TaskKind.TASK)

    # Blocked is separate from status: a task can be in progress and blocked at once.
    # Blocked while blocked_since is set (standup story).
    blocked_since = models.DateTimeField(null=True, blank=True)
    blocked_reason = models.TextField(blank=True)

    # "this task can't start until these are done"
    depends_on = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="dependents",
    )

    # Written by the scheduling engine, never by users directly.
    scheduled_start = models.DateField(null=True, blank=True)
    scheduled_end = models.DateField(null=True, blank=True)
    slack_days = models.IntegerField(null=True, blank=True)  # days it can slip without delaying the project
    is_critical = models.BooleanField(default=False)  # on the critical path (slack 0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_start", "id"]

    def __str__(self) -> str:
        return self.title

    @property
    def planned_end(self):
        if self.planned_start is None:
            return None
        return self.planned_start + timedelta(days=self.duration_days - 1)

    @property
    def status_label(self) -> str:
        """"Not started" / "In progress" / "Complete" (same name as on ClientTask)."""
        return self.get_status_display()

    @property
    def is_blocked(self) -> bool:
        return self.blocked_since is not None

    @property
    def moved_by_dependencies(self) -> bool:
        return bool(self.planned_start and self.scheduled_start
                    and self.scheduled_start > self.planned_start)


class GanttReport(models.Model):
    """A client or team member saying the project's Gantt chart looks wrong.
    Project managers (the scrum master) read these and mark them resolved."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="gantt_reports")
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="gantt_reports",
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="resolved_gantt_reports",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Gantt report on {self.project} by {self.reporter}"


class TaskEventKind(models.TextChoices):
    CREATED = "created", "Created"
    IN_PROGRESS = "in_progress", "Moved to In progress"
    DONE = "done", "Completed"
    REOPENED = "reopened", "Reopened"
    BLOCKED = "blocked", "Blocked"
    UNBLOCKED = "unblocked", "Unblocked"
    REASSIGNED = "reassigned", "Reassigned"
    RESCHEDULED = "rescheduled", "Due date moved"  # written by the engine, not by a person


class TaskEvent(models.Model):
    """One change to a task: who did what, and when (standup story).

    Written in the same transaction as the change itself, so the log and the
    task always agree. There's no history from before this table existed.
    old_value / new_value hold what changed: a status, an assignee's user id,
    a blocked reason, or an ISO due date for RESCHEDULED.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="task_events")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="task_events",
    )
    kind = models.CharField(max_length=20, choices=TaskEventKind.choices)
    old_value = models.CharField(max_length=500, blank=True)
    new_value = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["project", "created_at"], name="taskevent_project_time"),
            models.Index(fields=["task", "created_at"], name="taskevent_task_time"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.task}"


class StandupOrder(models.Model):
    """Where each member's card sits on a project's standup page. One order per
    project, shared by everyone, so the whole team sees the same speaking order."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="standup_order")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="standup_positions")
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="standup_order_unique_member"),
        ]
