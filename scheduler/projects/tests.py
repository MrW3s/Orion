"""Tests for the New project page (project managers and admins only) and the
Projects page, where admins set which client owns a project."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile, Role
from common.errors import InvalidProject

from .models import Project
from .services import ProjectService

User = get_user_model()


def make_user(username, role):
    user = User.objects.create_user(username, password="pw")
    Profile.objects.create(user=user, role=role)
    return user


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

    def test_clients_cant_be_picked_as_team_members(self):
        carla = make_user("carla", Role.CLIENT)
        self.client.force_login(self.pm)
        choices = self.client.get(self.url).context["form"].fields["member_ids"].choices
        self.assertNotIn(carla.pk, [pk for pk, _ in choices])
        # Posting them anyway creates nothing
        self.submit(member_ids=[carla.pk])
        self.assertFalse(Project.objects.exists())


class AdminSetsProjectOwner(TestCase):
    def setUp(self):
        self.admin = make_user("ada", Role.ADMIN)
        self.pm = make_user("pat", Role.PROJECT_MANAGER)
        self.carla = make_user("carla", Role.CLIENT)
        self.alice = User.objects.create_user("alice", password="pw")
        self.project = Project.objects.create(name="Website redesign", start_date=date(2026, 10, 19))

    def set_owner(self, owner_id):
        return self.client.post(reverse("set-project-owner", args=[self.project.pk]),
                                {"owner_id": owner_id}, follow=True)

    def owner(self):
        self.project.refresh_from_db()
        return self.project.owner

    def test_admin_makes_a_client_the_owner(self):
        # Given an admin is on the Projects page
        self.client.force_login(self.admin)
        response = self.client.get(reverse("manage-projects"))
        self.assertContains(response, "Website redesign")
        self.assertContains(response, ">carla</option>")
        self.assertNotContains(response, ">alice</option>")  # only clients can be picked
        # When they set the project's owner
        response = self.set_owner(self.carla.pk)
        # Then it's saved, and the client finds the project on their dashboard
        self.assertContains(response, "carla now owns “Website redesign”.")
        self.assertEqual(self.owner(), self.carla)
        self.client.force_login(self.carla)
        self.assertRedirects(self.client.get(reverse("client-dashboard")),
                             reverse("client-project", args=[self.project.pk]))

    def test_admin_can_clear_the_owner(self):
        self.project.owner = self.carla
        self.project.save()
        self.client.force_login(self.admin)
        self.assertContains(self.set_owner(""), "no longer has an owner")
        self.assertIsNone(self.owner())

    def test_only_clients_can_own_a_project(self):
        self.client.force_login(self.admin)
        self.assertContains(self.set_owner(self.alice.pk), "Pick the owner from the list.")
        self.assertIsNone(self.owner())
        with self.assertRaises(InvalidProject):  # the rule itself is in the service
            ProjectService().set_owner(self.admin, self.project.pk, self.alice.pk)

    def test_non_admins_cannot_set_owners(self):
        for user in (self.pm, self.alice, self.carla):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("manage-projects")).status_code, 403)
            self.assertEqual(self.client.post(reverse("set-project-owner", args=[self.project.pk]),
                                              {"owner_id": self.carla.pk}).status_code, 403)
        self.assertIsNone(self.owner())
