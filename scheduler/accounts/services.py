"""Use cases for story 4: role-based permissions.

    Given an admin selects a user,
    when the admin updates the user's permissions,
    then the software saves the user's new permissions.

    Given a non-admin user is logged in,
    when they try to change another user's permissions,
    then the system denies access and the permissions stay unchanged.

Admins can also create users (with a password and a role), since there is
no sign-up page.

Admins and project managers can also search and filter the employee list
(EmployeeDirectory below):

    Given I am an admin or PM on the employee list,
    when I filter by role, department or availability, or search by name or email,
    then only the matching employees are shown.

Admins edit each employee's name, email, department and availability.

Which role may use which feature is decided only here (ROLE_FEATURES). If
the rules change, this dict changes and the views and templates don't
(information hiding). The service never mentions HTTP; it raises domain
errors and the views translate them.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from django.core.validators import validate_email
from django.db.models import Q

from common.errors import (InvalidFilter, InvalidRoleChange, InvalidUser, NotAllowed, NotAnAdmin,
                           UserNotFound)
from common.validation import check_name, check_username

from .models import Availability, Profile, Role

FEATURES = {
    "view_schedule": "View project schedules",
    "view_gantt": "View the Gantt chart",
    "report_gantt": "Report a Gantt chart that looks wrong",
    "add_task": "Add tasks and edit dependencies",
    "update_status": "Update task status",
    "create_projects": "Create projects",
    "view_risk": "Dependency graph and critical path",
    "review_gantt_reports": "Read and resolve Gantt chart reports",
    "view_employees": "Search and filter the employee list",
    "manage_users": "Manage user roles",
    "set_project_owner": "Set which client owns a project",
    "client_dashboard": "Your project's progress, and notes for the team",
}

# Everyone who can see a Gantt chart can also report that it looks wrong.
_GANTT = {"view_gantt", "report_gantt"}

ROLE_FEATURES = {
    Role.TEAM_MEMBER: {"view_schedule", "add_task", "update_status"} | _GANTT,
    # Project managers act as the scrum master: Gantt chart reports go to them.
    Role.PROJECT_MANAGER: {"view_schedule", "add_task", "update_status", "create_projects",
                           "view_risk", "review_gantt_reports", "view_employees"} | _GANTT,
    Role.ADMIN: set(FEATURES) - {"client_dashboard"},  # admins use the team's pages
    # No "view_schedule": the team's pages stay closed. Clients see their own
    # project's Gantt chart on their dashboard, without assignees.
    Role.CLIENT: {"client_dashboard"} | _GANTT,
}


@dataclass(frozen=True)
class UserRow:
    user: object
    role: Role
    locked_reason: str = ""  # why an admin can't change this user's role, if they can't


class RoleService:
    def role_of(self, user) -> Role:
        if user.is_superuser:
            return Role.ADMIN  # so `createsuperuser` always gives you a first admin
        try:
            return Role(user.profile.role)
        except Profile.DoesNotExist:
            return Role.TEAM_MEMBER

    def can(self, user, feature: str) -> bool:
        if not getattr(user, "is_authenticated", False):
            return False
        return feature in ROLE_FEATURES[self.role_of(user)]

    def features_of(self, user) -> list[str]:
        allowed = ROLE_FEATURES[self.role_of(user)]
        return [label for key, label in FEATURES.items() if key in allowed]

    def permission_matrix(self) -> list[tuple[str, list[bool]]]:
        """One row per feature, one column per role (in Role order)."""
        return [(label, [key in ROLE_FEATURES[role] for role in Role])
                for key, label in FEATURES.items()]

    def require_admin(self, user) -> None:
        if not self.can(user, "manage_users"):
            raise NotAnAdmin("Only administrators can manage user roles")

    def list_users(self, admin) -> list[UserRow]:
        self.require_admin(admin)
        users = get_user_model().objects.select_related("profile").order_by("username")
        return [UserRow(u, self.role_of(u), self._locked_reason(admin, u)) for u in users]

    def set_role(self, admin, user_id: int, role: str) -> UserRow:
        self.require_admin(admin)
        if role not in Role.values:
            raise InvalidRoleChange(f"Unknown role {role!r}")
        User = get_user_model()
        try:
            target = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise UserNotFound(f"User {user_id} does not exist") from None

        reason = self._locked_reason(admin, target)
        if reason:
            raise InvalidRoleChange(f"Can't change {target.username}'s role: {reason}")

        Profile.objects.update_or_create(user=target, defaults={"role": role})
        return UserRow(target, Role(role))

    def create_user(self, admin, username: str, password: str, role: str) -> UserRow:
        self.require_admin(admin)
        if role not in Role.values:
            raise InvalidUser(f"Unknown role {role!r}")
        username = username.strip()
        if not username:
            raise InvalidUser("Enter a username")
        check_username(username, InvalidUser)
        User = get_user_model()
        # Case-insensitive, so "John" and "john" can't both exist.
        if User.objects.filter(username__iexact=username).exists():
            raise InvalidUser(f"The username \u201c{username}\u201d is already taken")

        user = User(username=username)
        try:
            validate_password(password, user)  # AUTH_PASSWORD_VALIDATORS in settings
        except ValidationError as exc:
            raise InvalidUser(" ".join(exc.messages).rstrip(".")) from None

        with transaction.atomic():
            user.set_password(password)
            user.save()
            Profile.objects.create(user=user, role=role)
        return UserRow(user, Role(role))

    @staticmethod
    def _locked_reason(admin, target) -> str:
        if target.pk == admin.pk:
            return "you can't change your own role"  # stops an admin locking everyone out
        if target.is_superuser:
            return "superusers are always administrators"
        return ""


# --- Employee list: search and filter -------------------------------------

@dataclass(frozen=True)
class EmployeeRow:
    user: object
    role: Role
    department: str
    availability: Availability


# Clients are outside the agency, so they never appear on the employee list.
EMPLOYEE_ROLES = [r for r in Role if r != Role.CLIENT]


def _role_q(role: Role) -> Q:
    """Match role_of() in the database: superusers are admins, and a user
    with no Profile row is a team member."""
    if role == Role.ADMIN:
        return Q(is_superuser=True) | Q(profile__role=Role.ADMIN)
    if role == Role.TEAM_MEMBER:
        return Q(is_superuser=False) & (Q(profile__isnull=True) | Q(profile__role=Role.TEAM_MEMBER))
    return Q(is_superuser=False, profile__role=role)


class EmployeeDirectory:
    def __init__(self, roles: RoleService | None = None):
        self.roles = roles or RoleService()

    def require_viewer(self, user) -> None:
        if not self.roles.can(user, "view_employees"):
            raise NotAllowed("Only administrators and project managers can view the employee list")

    def departments(self, viewer) -> list[str]:
        """Every department in use, for the filter dropdown (case-insensitively unique)."""
        self.require_viewer(viewer)
        names = (Profile.objects.exclude(department="")
                 .values_list("department", flat=True).distinct())
        unique: dict[str, str] = {}
        for name in sorted(names):  # capitalised spellings sort first, so they win
            unique.setdefault(name.casefold(), name)
        return sorted(unique.values(), key=str.casefold)

    def search(self, viewer, q: str = "", role: str = "", department: str = "",
               availability: str = "") -> list[EmployeeRow]:
        """Employees matching every filter given. Blank filters are ignored.

        q matches username, first name, last name or email (case-insensitive,
        partial). Each word must match somewhere, so "jane doe" finds Jane Doe.
        """
        self.require_viewer(viewer)
        users = (get_user_model().objects.filter(is_active=True)
                 .exclude(Q(is_superuser=False) & Q(profile__role=Role.CLIENT))
                 .select_related("profile"))

        for word in (q or "").split():
            users = users.filter(Q(username__icontains=word) | Q(first_name__icontains=word)
                                 | Q(last_name__icontains=word) | Q(email__icontains=word))
        if role:
            if role not in [r.value for r in EMPLOYEE_ROLES]:
                raise InvalidFilter(f"Unknown role {role!r}")
            users = users.filter(_role_q(Role(role)))
        if department := (department or "").strip():
            users = users.filter(profile__department__iexact=department)
        if availability:
            if availability not in Availability.values:
                raise InvalidFilter(f"Unknown availability {availability!r}")
            match = Q(profile__availability=availability)
            if availability == Availability.AVAILABLE:
                match |= Q(profile__isnull=True)
            users = users.filter(match)

        users = users.order_by("last_name", "first_name", "username").distinct()
        return [self._row(u) for u in users]

    def get(self, admin, user_id: int) -> EmployeeRow:
        self.roles.require_admin(admin)
        User = get_user_model()
        try:
            return self._row(User.objects.select_related("profile").get(pk=user_id))
        except User.DoesNotExist:
            raise UserNotFound(f"User {user_id} does not exist") from None

    def update_details(self, admin, user_id: int, *, first_name: str = "", last_name: str = "",
                       email: str = "", department: str = "",
                       availability: str = Availability.AVAILABLE) -> EmployeeRow:
        """Admins only: the details the employee list searches and filters on."""
        self.roles.require_admin(admin)
        User = get_user_model()
        try:
            target = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise UserNotFound(f"User {user_id} does not exist") from None

        first_name, last_name = first_name.strip(), last_name.strip()
        email, department = email.strip(), " ".join(department.split())
        check_name(first_name, InvalidUser, "First name")
        check_name(last_name, InvalidUser, "Last name")
        check_name(department, InvalidUser, "Department")
        if len(department) > 60:
            raise InvalidUser("Department must be 60 characters or fewer")
        if availability not in Availability.values:
            raise InvalidUser(f"Unknown availability {availability!r}")
        if email:
            try:
                validate_email(email)
            except ValidationError:
                raise InvalidUser("Enter a valid email address") from None
            if User.objects.filter(email__iexact=email).exclude(pk=target.pk).exists():
                raise InvalidUser(f"Another user already has the email {email}")

        with transaction.atomic():
            target.first_name, target.last_name, target.email = first_name, last_name, email
            target.save(update_fields=["first_name", "last_name", "email"])
            Profile.objects.update_or_create(
                user=target, defaults={"department": department, "availability": availability})
        return self._row(User.objects.select_related("profile").get(pk=target.pk))

    def _row(self, user) -> EmployeeRow:
        try:
            profile = user.profile
            department, availability = profile.department, Availability(profile.availability)
        except Profile.DoesNotExist:
            department, availability = "", Availability.AVAILABLE
        return EmployeeRow(user, self.roles.role_of(user), department, availability)
