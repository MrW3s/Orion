from django.urls import path

from . import views

urlpatterns = [
    path("projects/", views.manage_projects, name="manage-projects"),
    path("projects/new/", views.new_project, name="new-project"),
    path("projects/<int:project_id>/owner/", views.set_owner, name="set-project-owner"),
]
