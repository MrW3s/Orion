from django.conf import settings
from django.db import models


class Project(models.Model):
    """A project an agency team works on. Its members are the 'relevant
    team members' who can see and change its tasks."""

    name = models.CharField(max_length=200)
    start_date = models.DateField()
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="projects")
    # The client the project is for (set by an admin). They follow its progress on
    # their own dashboard; they aren't a member, so the team's pages stay closed to them.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_projects",
    )

    def __str__(self) -> str:
        return self.name


class ClientNote(models.Model):
    """A note the client leaves for the people working on the project."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="client_notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                               related_name="client_notes")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]  # newest first

    def __str__(self) -> str:
        return f"Note on {self.project}"
