from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    TEAM_MEMBER = "team_member", "Team member"
    PROJECT_MANAGER = "project_manager", "Project manager"
    ADMIN = "admin", "Administrator"


class Profile(models.Model):
    """Extra data about a user; for now just their role (story 4).
    A user with no Profile row is a team member."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TEAM_MEMBER)

    def __str__(self) -> str:
        return f"{self.user} ({self.get_role_display()})"
