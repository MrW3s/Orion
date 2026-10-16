"""Creating projects.

Who may create one is a role rule ("create_projects" in
accounts.services.ROLE_FEATURES: project managers and admins), so this
module asks RoleService instead of checking roles itself. Whoever creates
a project becomes a member of it, so they can open its schedule straight away.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from accounts.services import RoleService
from common.errors import InvalidProject, NotAllowed

from .models import Project


@dataclass(frozen=True)
class NewProject:
    name: str
    start_date: date
    member_ids: list[int] = field(default_factory=list)


class ProjectService:
    def __init__(self, roles: RoleService | None = None):
        self._roles = roles or RoleService()

    def can_create(self, user) -> bool:
        return self._roles.can(user, "create_projects")

    def possible_members(self, user) -> list:
        """Everyone the creator can add (the creator is added automatically)."""
        return list(get_user_model().objects.exclude(pk=user.pk).order_by("username"))

    def create_project(self, user, new: NewProject) -> Project:
        if not self.can_create(user):
            raise NotAllowed("Your role can't create projects")
        if not new.name.strip():
            raise InvalidProject("Give the project a name")
        members = list(get_user_model().objects.filter(pk__in=new.member_ids))
        if len(members) != len(set(new.member_ids)):
            raise InvalidProject("Some of the selected members don't exist")

        with transaction.atomic():
            project = Project.objects.create(name=new.name.strip(), start_date=new.start_date)
            project.members.set([user, *members])
        return project
