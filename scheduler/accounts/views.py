"""Server-rendered pages for story 4: a simple stand-in until the React UI exists.

Like tasks/views.py, each view calls the service and renders the result.
The rules themselves live in services.py.

    GET  /                     home: your role and what it lets you access
                               (clients go straight to their dashboard)
    GET  /users/               admins only: every user's role + the permission table
    POST /users/               admins only: create a user (username, password, role)
    POST /users/<id>/role/     admins only: change one user's role
    GET/POST /users/<id>/details/  admins only: name, email, department, availability
    GET  /employees/           admins + PMs: search (?q=) and filter the employee list
                               (?role= &department= &availability=)
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

from common.errors import DomainError, NotAllowed, NotAnAdmin

from .forms import EmployeeDetailsForm, NewUserForm
from .models import Availability, Role
from .services import EMPLOYEE_ROLES, EmployeeDirectory, RoleService


@login_required
def home(request):
    roles = RoleService()
    if roles.can(request.user, "client_dashboard"):
        return redirect("client-dashboard")  # clients get their own, view-only dashboard
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


@login_required
def employees(request):
    directory = EmployeeDirectory()
    try:
        directory.require_viewer(request.user)
    except NotAllowed as exc:
        raise PermissionDenied(str(exc)) from exc

    filters = {key: request.GET.get(key, "").strip()
               for key in ("q", "role", "department", "availability")}
    try:
        rows = directory.search(request.user, **filters)
    except DomainError as exc:
        messages.error(request, f"{exc}. Showing everyone instead.")
        rows = directory.search(request.user)
        filters = dict.fromkeys(filters, "")

    return render(request, "accounts/employees.html", {
        "rows": rows,
        "total": len(rows) if not any(filters.values()) else len(directory.search(request.user)),
        "filters": filters,
        "filtering": any(filters.values()),
        "roles": [(r.value, r.label) for r in EMPLOYEE_ROLES],
        "departments": directory.departments(request.user),
        "availabilities": Availability.choices,
        "can_edit": RoleService().can(request.user, "manage_users"),
    })


@login_required
def employee_details(request, user_id: int):
    directory = EmployeeDirectory()
    try:
        row = directory.get(request.user, user_id)
    except NotAnAdmin as exc:
        raise PermissionDenied(str(exc)) from exc
    except DomainError as exc:
        messages.error(request, str(exc))
        return redirect("employees")

    initial = {"first_name": row.user.first_name, "last_name": row.user.last_name,
               "email": row.user.email, "department": row.department,
               "availability": row.availability}
    form = EmployeeDetailsForm(request.POST if request.method == "POST" else None, initial=initial)
    if form.is_valid():
        try:
            row = directory.update_details(request.user, user_id, **form.cleaned_data)
        except DomainError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"Saved {row.user.username}'s details.")
            return redirect("employees")

    return render(request, "accounts/employee_details.html", {"row": row, "form": form})


class ChangePasswordView(SuccessMessageMixin, PasswordChangeView):
    success_url = reverse_lazy("home")
    success_message = "Your password was changed."
