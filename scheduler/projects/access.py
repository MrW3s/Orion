"""Who is allowed to see/change a project.

Membership rules live only here. If the rules change later (roles, guests,
per-task visibility), only this module changes: that design decision is
hidden behind is_member() / require_member() (information hiding).

A project's owner (its client) is not a member. They get their own,
view-only dashboard instead, through is_owner() / require_owner().
"""
from accounts.services import RoleService
from common.errors import NotAProjectMember, ProjectOutOfScope

from .models import Project


class ProjectAccess:
    def __init__(self, roles: RoleService | None = None):
        self._roles = roles or RoleService()

    def is_member(self, user, project_id: int) -> bool:
        # Roles without "view_schedule" (clients) never count as members, even if
        # they were added to the project before their role changed.
        if not self._roles.can(user, "view_schedule"):
            return False
        return Project.objects.filter(pk=project_id, members=user).exists()

    def is_member_id(self, user_id: int, project_id: int) -> bool:
        return Project.objects.filter(pk=project_id, members__pk=user_id).exists()

    def require_member(self, user, project_id: int) -> None:
        if not self.is_member(user, project_id):
            raise NotAProjectMember(f"User is not a member of project {project_id}")

    def get_project(self, project_id: int) -> Project:
        return Project.objects.get(pk=project_id)

    # ---- The client who owns a project ---------------------------------
    def owned_projects(self, user) -> list[Project]:
        return list(Project.objects.filter(owner=user).order_by("start_date", "name"))

    def require_owner(self, user, project_id: int) -> Project:
        # A project that doesn't exist gets the same answer, so clients can't probe for them.
        try:
            return Project.objects.get(pk=project_id, owner=user)
        except Project.DoesNotExist:
            raise ProjectOutOfScope("That project is out of scope for your permissions") from None
