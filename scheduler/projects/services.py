"""Creating projects, and (admins only) setting which client owns one.

Who may create one is a role rule ("create_projects" in
accounts.services.ROLE_FEATURES: project managers and admins), so this
module asks RoleService instead of checking roles itself. Whoever creates
a project becomes a member of it, so they can open its schedule straight away.

Members are the people doing the work ("view_schedule"); the owner is the
client the work is for ("client_dashboard"). Nobody can be both.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from accounts.services import RoleService
from common.errors import InvalidProject, NotAllowed, ProjectNotFound

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
        """Everyone the creator can add (the creator is added automatically). Not clients."""
        users = get_user_model().objects.exclude(pk=user.pk).select_related("profile")
        return [u for u in users.order_by("username") if self._roles.can(u, "view_schedule")]

    def create_project(self, user, new: NewProject) -> Project:
        if not self.can_create(user):
            raise NotAllowed("Your role can't create projects")
        if not new.name.strip():
            raise InvalidProject("Give the project a name")
        members = list(get_user_model().objects.filter(pk__in=new.member_ids)
                       .select_related("profile"))
        if len(members) != len(set(new.member_ids)):
            raise InvalidProject("Some of the selected members don't exist")
        if not all(self._roles.can(m, "view_schedule") for m in members):
            raise InvalidProject("Clients can't be team members. An administrator can make "
                                 "them the project's owner instead")

        with transaction.atomic():
            project = Project.objects.create(name=new.name.strip(), start_date=new.start_date)
            project.members.set([user, *members])
        return project

    # ---- Project owners (admins only) ----------------------------------
    def can_set_owner(self, user) -> bool:
        return self._roles.can(user, "set_project_owner")

    def list_projects(self, admin) -> list[Project]:
        self._require_owner_setter(admin)
        return list(Project.objects.select_related("owner").order_by("name"))

    def possible_owners(self) -> list:
        """Only clients can own a project."""
        users = get_user_model().objects.select_related("profile").order_by("username")
        return [u for u in users if self._roles.can(u, "client_dashboard")]

    def set_owner(self, admin, project_id: int, owner_id: int | None) -> Project:
        """Give the project to a client (or, with owner_id None, to nobody)."""
        self._require_owner_setter(admin)
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            raise ProjectNotFound(f"Project {project_id} does not exist") from None

        owner = None
        if owner_id is not None:
            owner = get_user_model().objects.filter(pk=owner_id).first()
            if owner is None or not self._roles.can(owner, "client_dashboard"):
                raise InvalidProject("A project's owner must be a user with the Client role")

        project.owner = owner
        project.save(update_fields=["owner"])
        return project

    def _require_owner_setter(self, user) -> None:
        if not self.can_set_owner(user):
            raise NotAllowed("Only administrators can set a project's owner")
