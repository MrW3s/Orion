from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("tasks.urls")),
    path("", include("accounts.urls")),  # story 4 pages: login, home, manage users
    path("", include("projects.urls")),  # new project page (project managers + admins)
    path("", include("tasks.page_urls")),  # story 1 page: project schedule + add task
]
