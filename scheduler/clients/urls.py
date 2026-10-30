from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.dashboard, name="client-dashboard"),
    path("dashboard/<int:project_id>/", views.project, name="client-project"),
]
