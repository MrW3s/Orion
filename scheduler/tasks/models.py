from datetime import timedelta

from django.conf import settings
from django.db import models

from projects.models import Project


class TaskStatus(models.TextChoices):
    TODO = "todo", "Not started"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETE = "complete", "Complete"


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

    # "this task can't start until these are done"
    depends_on = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="dependents",
    )

    # Written by the scheduling engine, never by users directly.
    scheduled_start = models.DateField(null=True, blank=True)
    scheduled_end = models.DateField(null=True, blank=True)

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
    def moved_by_dependencies(self) -> bool:
        return bool(self.planned_start and self.scheduled_start
                    and self.scheduled_start > self.planned_start)
