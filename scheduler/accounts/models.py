from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    TEAM_MEMBER = "team_member", "Team member"
    PROJECT_MANAGER = "project_manager", "Project manager"
    ADMIN = "admin", "Administrator"
    CLIENT = "client", "Client"  # outside the agency: sees only the projects they own


class Availability(models.TextChoices):
    AVAILABLE = "available", "Available"
    LIMITED = "limited", "Limited availability"
    UNAVAILABLE = "unavailable", "Unavailable"


class Profile(models.Model):
    """Extra data about a user: their role (story 4), plus the department and
    availability the employee list filters on.
    A user with no Profile row is an available team member with no department."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TEAM_MEMBER)
    department = models.CharField(max_length=60, blank=True, default="")
    availability = models.CharField(max_length=20, choices=Availability.choices,
                                    default=Availability.AVAILABLE)

    def __str__(self) -> str:
        return f"{self.user} ({self.get_role_display()})"
