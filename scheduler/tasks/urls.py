from django.urls import path

from .views import ProjectTasksView, TaskStatusView

urlpatterns = [
    path("projects/<int:project_id>/tasks/", ProjectTasksView.as_view(), name="project-tasks"),
    path("tasks/<int:task_id>/status/", TaskStatusView.as_view(), name="task-status"),
]
