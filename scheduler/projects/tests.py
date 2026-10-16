"""Tests for the New project page (project managers and admins only)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile, Role

from .models import Project

User = get_user_model()


class NewProjectPage(TestCase):
    def setUp(self):
        self.pm = User.objects.create_user("pat", password="pw")
        Profile.objects.create(user=self.pm, role=Role.PROJECT_MANAGER)
        self.john = User.objects.create_user("john", password="pw")
        self.eve = User.objects.create_user("eve", password="pw")
        self.url = reverse("new-project")

    def submit(self, **fields):
        form = {"name": "Website redesign", "start_date": "2026-10-19"}
        form.update(fields)
        return self.client.post(self.url, form, follow=True)

    def test_project_manager_creates_project_with_members(self):
        # Given a project manager is logged in
        self.client.force_login(self.pm)
        # When they create a project and pick its members
        response = self.submit(member_ids=[self.john.pk])
        # Then it exists, they and the chosen members are on it, and they land on its schedule
        project = Project.objects.get()
        self.assertEqual(set(project.members.all()), {self.pm, self.john})
        self.assertRedirects(response, reverse("project-schedule", args=[project.pk]))
        self.assertContains(response, "Created “Website redesign”")

    def test_admin_can_create_projects(self):
        root = User.objects.create_superuser("root", password="pw")
        self.client.force_login(root)
        self.submit()
        self.assertEqual(list(Project.objects.get().members.all()), [root])

    def test_team_member_is_denied(self):
        # Given a team member is logged in; when they try to create a project
        self.client.force_login(self.eve)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"name": "x", "start_date": "2026-10-19"}).status_code, 403)
        # Then nothing is created
        self.assertFalse(Project.objects.exists())

    def test_missing_name_or_date_shows_error_and_creates_nothing(self):
        self.client.force_login(self.pm)
        response = self.submit(name="", start_date="")
        self.assertContains(response, "The project wasn")
        self.assertContains(response, "Give the project a name.")
        self.assertContains(response, "Pick a start date.")
        self.assertFalse(Project.objects.exists())

    def test_home_shows_new_project_link_only_to_roles_that_can_use_it(self):
        self.client.force_login(self.pm)
        self.assertContains(self.client.get(reverse("home")), self.url)
        self.client.force_login(self.eve)
        self.assertNotContains(self.client.get(reverse("home")), self.url)
