from django.contrib import admin

from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "status", "scheduled_start", "scheduled_end"]
    list_filter = ["project", "status"]
