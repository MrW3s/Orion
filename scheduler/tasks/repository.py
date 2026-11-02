"""Data access for tasks.

All ORM queries for tasks live here, so the service layer never builds
queries itself. If the storage changes (e.g. SQLite -> PostgreSQL, or
caching), only this module changes.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from django.utils import timezone

from common.errors import ReportNotFound, TaskNotFound
from scheduling import ScheduleResult

from .models import GanttReport, Task


class TaskRepository:
    def get(self, task_id: int) -> Task:
        try:
            return Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            raise TaskNotFound(f"Task {task_id} does not exist") from None

    def list_for_project(self, project_id: int) -> list[Task]:
        return list(
            Task.objects.filter(project_id=project_id)
            .select_related("assignee").prefetch_related("depends_on")
        )

    def ids_in_project(self, project_id: int, task_ids: Iterable[int]) -> set[int]:
        return set(
            Task.objects.filter(project_id=project_id, pk__in=list(task_ids))
            .values_list("pk", flat=True)
        )

    def create(self, *, project_id: int, created_by, title: str, description: str,
               duration_days: int, planned_start: date, assignee_id: int | None,
               depends_on_ids: Iterable[int]) -> Task:
        task = Task.objects.create(
            project_id=project_id, created_by=created_by, title=title,
            description=description, duration_days=duration_days,
            planned_start=planned_start, assignee_id=assignee_id,
        )
        task.depends_on.set(list(depends_on_ids))
        return task

    def save_schedule(self, result: ScheduleResult) -> None:
        tasks = list(Task.objects.filter(pk__in=result.tasks.keys()))
        for task in tasks:
            slot = result.tasks[task.pk]
            task.scheduled_start, task.scheduled_end = slot.start, slot.end
            task.slack_days, task.is_critical = slot.slack_days, slot.is_critical
        Task.objects.bulk_update(
            tasks, ["scheduled_start", "scheduled_end", "slack_days", "is_critical"],
        )

    def set_dependencies(self, task: Task, depends_on_ids: Iterable[int]) -> None:
        task.depends_on.set(list(depends_on_ids))

    def save_status(self, task: Task, status: str) -> Task:
        task.status = status
        task.save(update_fields=["status", "updated_at"])
        return task

    # ---- Gantt chart reports -----------------------------------------
    def create_gantt_report(self, *, project_id: int, reporter, message: str) -> GanttReport:
        return GanttReport.objects.create(project_id=project_id, reporter=reporter, message=message)

    def get_gantt_report(self, report_id: int) -> GanttReport:
        try:
            return GanttReport.objects.get(pk=report_id)
        except GanttReport.DoesNotExist:
            raise ReportNotFound(f"Report {report_id} does not exist") from None

    def open_gantt_reports(self, project_id: int) -> list[GanttReport]:
        return list(GanttReport.objects.filter(project_id=project_id, resolved_at__isnull=True)
                    .select_related("reporter"))

    def resolve_gantt_report(self, report: GanttReport, resolved_by) -> GanttReport:
        report.resolved_by, report.resolved_at = resolved_by, timezone.now()
        report.save(update_fields=["resolved_by", "resolved_at"])
        return report
