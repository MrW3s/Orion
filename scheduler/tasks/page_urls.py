from django.urls import path

from . import pages

urlpatterns = [
    path("projects/<int:project_id>/", pages.schedule, name="project-schedule"),
]
