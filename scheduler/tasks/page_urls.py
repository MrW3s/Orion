from django.urls import path

from . import pages

urlpatterns = [
    path("projects/<int:project_id>/", pages.schedule, name="project-schedule"),
    path("projects/<int:project_id>/gantt/", pages.gantt, name="project-gantt"),
    path("projects/<int:project_id>/gantt/reports/<int:report_id>/resolve/",
         pages.resolve_gantt_report, name="resolve-gantt-report"),
]
