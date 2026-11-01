from django.contrib import admin

from .models import GanttReport, Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "status", "scheduled_start", "scheduled_end"]
    list_filter = ["project", "status"]


@admin.register(GanttReport)
class GanttReportAdmin(admin.ModelAdmin):
    list_display = ["project", "reporter", "created_at", "resolved_at"]
    list_filter = ["project"]
