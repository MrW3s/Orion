"""Tests written from the story 4 acceptance criteria (given / when / then)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Profile, Role
from .services import RoleService

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("ada", password="pw")
        Profile.objects.create(user=self.admin, role=Role.ADMIN)
        self.john = User.objects.create_user("john", password="pw")
        self.eve = User.objects.create_user("eve", password="pw")
        self.roles = RoleService()

    def role_of(self, user) -> Role:
        return self.roles.role_of(User.objects.get(pk=user.pk))  # fresh copy, no cached profile

    def change_role(self, target, role):
        return self.client.post(reverse("change-role", args=[target.pk]), {"role": role})


class Story4AdminChangesRoles(Fixture):
    def test_admin_updates_a_users_role(self):
        # Given an admin selects a user
        self.client.force_login(self.admin)
        # When the admin updates the user's permissions
        response = self.client.post(
            reverse("change-role", args=[self.john.pk]), {"role": Role.PROJECT_MANAGER}, follow=True,
        )
        # Then the software saves the user's new permissions
        self.assertContains(response, "Updated john to Project manager.")
        self.assertEqual(self.role_of(self.john), Role.PROJECT_MANAGER)
        self.assertTrue(self.roles.can(User.objects.get(pk=self.john.pk), "view_risk"))

    def test_admin_sees_every_user(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("manage-users"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row.user.username for row in response.context["rows"]], ["ada", "eve", "john"])

    def test_admin_cannot_change_own_role(self):
        self.client.force_login(self.admin)
        self.change_role(self.admin, Role.TEAM_MEMBER)
        self.assertEqual(self.role_of(self.admin), Role.ADMIN)

    def test_unknown_role_is_rejected(self):
        self.client.force_login(self.admin)
        self.change_role(self.john, "boss")
        self.assertEqual(self.role_of(self.john), Role.TEAM_MEMBER)

    def test_superuser_is_always_an_admin(self):
        root = User.objects.create_superuser("root", password="pw")
        self.client.force_login(root)
        self.assertEqual(self.client.get(reverse("manage-users")).status_code, 200)
        self.change_role(root, Role.TEAM_MEMBER)
        self.assertEqual(self.role_of(root), Role.ADMIN)


class Story4NonAdminIsDenied(Fixture):
    def test_non_admin_cannot_change_another_users_role(self):
        # Given a non-admin user is logged in
        self.client.force_login(self.eve)
        # When they try to change another user's permissions
        response = self.change_role(self.john, Role.ADMIN)
        # Then the system denies access and the permissions stay unchanged
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.role_of(self.john), Role.TEAM_MEMBER)

    def test_non_admin_cannot_promote_themselves(self):
        self.client.force_login(self.eve)
        self.assertEqual(self.change_role(self.eve, Role.ADMIN).status_code, 403)
        self.assertEqual(self.role_of(self.eve), Role.TEAM_MEMBER)

    def test_project_manager_is_not_an_admin(self):
        Profile.objects.create(user=self.john, role=Role.PROJECT_MANAGER)
        self.client.force_login(self.john)
        self.assertEqual(self.change_role(self.eve, Role.ADMIN).status_code, 403)

    def test_non_admin_cannot_open_user_management(self):
        self.client.force_login(self.eve)
        response = self.client.get(reverse("manage-users"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Access denied", status_code=403)


class HomePage(Fixture):
    def test_shows_role_and_only_that_roles_features(self):
        self.client.force_login(self.eve)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Team member")
        self.assertContains(response, "Add tasks")
        self.assertNotContains(response, "Manage user")

    def test_client_role_can_view_but_not_change(self):
        Profile.objects.create(user=self.eve, role=Role.CLIENT)
        eve = User.objects.get(pk=self.eve.pk)
        self.assertTrue(self.roles.can(eve, "view_gantt"))
        self.assertTrue(self.roles.can(eve, "report_gantt"))
        for feature in ("add_task", "update_status", "review_gantt_reports"):
            self.assertFalse(self.roles.can(eve, feature))
        self.client.force_login(eve)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Client")
        self.assertContains(response, "View the Gantt chart")
        self.assertNotContains(response, "Add tasks")

    def test_admin_gets_link_to_user_management(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("home")), reverse("manage-users"))

    def test_logged_out_visitor_is_sent_to_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")


class AdminCreatesUsers(Fixture):
    GOOD = "orion-launch-2026"

    def create(self, **fields):
        form = {"username": "sam", "role": Role.PROJECT_MANAGER,
                "password1": self.GOOD, "password2": self.GOOD}
        form.update(fields)
        return self.client.post(reverse("manage-users"), form, follow=True)

    def test_admin_creates_user_who_can_log_in_with_that_role(self):
        # Given an admin is on the Manage users page
        self.client.force_login(self.admin)
        # When they add a user with a password and a role
        response = self.create()
        # Then the user exists with that role and can log in
        self.assertContains(response, "Created sam (Project manager).")
        sam = User.objects.get(username="sam")
        self.assertEqual(self.roles.role_of(sam), Role.PROJECT_MANAGER)
        self.client.logout()
        self.assertTrue(self.client.login(username="sam", password=self.GOOD))

    def test_taken_username_is_rejected_ignoring_case(self):
        self.client.force_login(self.admin)
        response = self.create(username="John")
        self.assertContains(response, "is already taken")
        self.assertEqual(User.objects.filter(username__iexact="john").count(), 1)

    def test_mismatched_passwords_are_rejected(self):
        self.client.force_login(self.admin)
        response = self.create(password2="something-else-2026")
        self.assertContains(response, "The passwords don")
        self.assertFalse(User.objects.filter(username="sam").exists())

    def test_weak_password_is_rejected(self):
        self.client.force_login(self.admin)
        response = self.create(password1="pw", password2="pw")
        self.assertContains(response, "too short")
        self.assertFalse(User.objects.filter(username="sam").exists())

    def test_non_admin_cannot_create_users(self):
        self.client.force_login(self.eve)
        response = self.client.post(reverse("manage-users"), {
            "username": "sneaky", "role": Role.ADMIN, "password1": self.GOOD, "password2": self.GOOD,
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="sneaky").exists())

    def test_user_can_change_their_own_password(self):
        self.client.force_login(self.eve)
        response = self.client.post(reverse("password-change"), {
            "old_password": "pw", "new_password1": self.GOOD, "new_password2": self.GOOD,
        }, follow=True)
        self.assertContains(response, "Your password was changed.")
        self.client.logout()
        self.assertTrue(self.client.login(username="eve", password=self.GOOD))
