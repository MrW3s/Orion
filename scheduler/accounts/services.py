"""Use cases for story 4: role-based permissions.

    Given an admin selects a user,
    when the admin updates the user's permissions,
    then the software saves the user's new permissions.

    Given a non-admin user is logged in,
    when they try to change another user's permissions,
    then the system denies access and the permissions stay unchanged.

Admins can also create users (with a password and a role), since there is
no sign-up page.

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

from common.errors import InvalidRoleChange, InvalidUser, NotAnAdmin, UserNotFound

from .models import Profile, Role

FEATURES = {
    "view_schedule": "View project schedules",
    "add_task": "Add tasks",
    "update_status": "Update task status",
    "create_projects": "Create projects",
    "view_risk": "Dependency graph and critical path",
    "manage_users": "Manage user roles",
}

ROLE_FEATURES = {
    Role.TEAM_MEMBER: {"view_schedule", "add_task", "update_status"},
    Role.PROJECT_MANAGER: {"view_schedule", "add_task", "update_status", "create_projects",
                           "view_risk"},
    Role.ADMIN: set(FEATURES),
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
