from django.conf import settings
from django.db import models


class Project(models.Model):
    """A project an agency team works on. Its members are the 'relevant
    team members' who can see and change its tasks."""

    name = models.CharField(max_length=200)
    start_date = models.DateField()
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="projects")

    def __str__(self) -> str:
        return self.name
