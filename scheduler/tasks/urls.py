from django.urls import path

from .views import (
    ProjectRiskView, ProjectTasksView, TaskAssigneeView, TaskBlockView, TaskDependenciesView,
    TaskStatusView,
)

urlpatterns = [
    path("projects/<int:project_id>/tasks/", ProjectTasksView.as_view(), name="project-tasks"),
    path("projects/<int:project_id>/risk/", ProjectRiskView.as_view(), name="project-risk"),
    path("tasks/<int:task_id>/status/", TaskStatusView.as_view(), name="task-status"),
    path("tasks/<int:task_id>/dependencies/", TaskDependenciesView.as_view(),
         name="task-dependencies"),
    path("tasks/<int:task_id>/block/", TaskBlockView.as_view(), name="task-block"),
    path("tasks/<int:task_id>/assignee/", TaskAssigneeView.as_view(), name="task-assignee"),
]
