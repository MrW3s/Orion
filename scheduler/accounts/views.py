"""Server-rendered pages for story 4: a simple stand-in until the React UI exists.

Like tasks/views.py, each view calls the service and renders the result.
The rules themselves live in services.py.

    GET  /                     home: your role and what it lets you access
    GET  /users/               admins only: every user's role + the permission table
    POST /users/<id>/role/     admins only: change one user's role
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from common.errors import DomainError, NotAnAdmin

from .models import Role
from .services import RoleService


@login_required
def home(request):
    roles = RoleService()
    return render(request, "accounts/home.html", {
        "role": roles.role_of(request.user),
        "features": roles.features_of(request.user),
        "is_admin": roles.can(request.user, "manage_users"),
    })


@login_required
def manage_users(request):
    roles = RoleService()
    try:
        rows = roles.list_users(request.user)
    except NotAnAdmin as exc:
        raise PermissionDenied(str(exc)) from exc
    return render(request, "accounts/manage_users.html", {
        "rows": rows,
        "roles": Role.choices,
        "matrix": roles.permission_matrix(),
        "is_admin": True,
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
