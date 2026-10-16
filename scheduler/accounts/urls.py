from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", views.ChangePasswordView.as_view(), name="password-change"),
    path("users/", views.manage_users, name="manage-users"),
    path("users/<int:user_id>/role/", views.change_role, name="change-role"),
]
