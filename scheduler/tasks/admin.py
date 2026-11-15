from django.contrib import admin

from .models import GanttReport, Task, TaskEvent


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "kind", "status", "scheduled_start", "scheduled_end", "blocked_since"]
    list_filter = ["project", "status", "kind"]


@admin.register(GanttReport)
class GanttReportAdmin(admin.ModelAdmin):
    list_display = ["project", "reporter", "created_at", "resolved_at"]
    list_filter = ["project"]


@admin.register(TaskEvent)
class TaskEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "project", "task", "kind", "actor", "old_value", "new_value"]
    list_filter = ["project", "kind"]
