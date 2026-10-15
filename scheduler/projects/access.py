"""Who is allowed to see/change a project.

Membership rules live only here. If the rules change later (roles, guests,
per-task visibility), only this module changes: that design decision is
hidden behind is_member() / require_member() (information hiding).
"""
from common.errors import NotAProjectMember

from .models import Project


class ProjectAccess:
    def is_member(self, user, project_id: int) -> bool:
        if not getattr(user, "is_authenticated", False):
            return False
        return Project.objects.filter(pk=project_id, members=user).exists()

    def is_member_id(self, user_id: int, project_id: int) -> bool:
        return Project.objects.filter(pk=project_id, members__pk=user_id).exists()

    def require_member(self, user, project_id: int) -> None:
        if not self.is_member(user, project_id):
            raise NotAProjectMember(f"User is not a member of project {project_id}")

    def get_project(self, project_id: int) -> Project:
        return Project.objects.get(pk=project_id)
