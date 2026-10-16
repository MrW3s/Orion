from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("tasks.urls")),
    path("", include("accounts.urls")),  # story 4 pages: login, home, manage users
]
