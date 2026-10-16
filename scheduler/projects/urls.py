from django.urls import path

from . import views

urlpatterns = [
    path("projects/new/", views.new_project, name="new-project"),
]
