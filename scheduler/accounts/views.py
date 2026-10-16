"""Server-rendered pages for story 4: a simple stand-in until the React UI exists.

Like tasks/views.py, each view calls the service and renders the result.
The rules themselves live in services.py.

    GET  /                     home: your role and what it lets you access
    GET  /users/               admins only: every user's role + the permission table
    POST /users/               admins only: create a user (username, password, role)
    POST /users/<id>/role/     admins only: change one user's role
    GET/POST /password/        any user: change your own password
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from common.errors import DomainError, NotAnAdmin

from .forms import NewUserForm
from .models import Role
from .services import RoleService


@login_required
def home(request):
    roles = RoleService()
    return render(request, "accounts/home.html", {
        "role": roles.role_of(request.user),
        "features": roles.features_of(request.user),
        "can_create_projects": roles.can(request.user, "create_projects"),
    })


@login_required
def manage_users(request):
    roles = RoleService()
    try:
        roles.require_admin(request.user)
    except NotAnAdmin as exc:
        raise PermissionDenied(str(exc)) from exc

    form = NewUserForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        data = form.cleaned_data
        try:
            row = roles.create_user(request.user, data["username"], data["password1"], data["role"])
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"Created {row.user.username} ({row.role.label}). Share the "
                                      "password with them; they can change it after logging in.")
            return redirect("manage-users")

    return render(request, "accounts/manage_users.html", {
        "rows": roles.list_users(request.user),
        "form": form,
        "roles": Role.choices,
        "matrix": roles.permission_matrix(),
    })


@login_required
@require_POST
def change_role(request, user_id: int):
    try:
        row = RoleService().set_role(request.user, user_id, request.POST.get("role", ""))
    except NotAnAdmin as exc:
        raise PermissionDenied(str(exc)) from exc
    except DomainError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Updated {row.user.username} to {row.role.label}.")
    return redirect("manage-users")


class ChangePasswordView(SuccessMessageMixin, PasswordChangeView):
    success_url = reverse_lazy("home")
    success_message = "Your password was changed."
