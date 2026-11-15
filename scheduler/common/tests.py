"""Security story 1: as an admin, I want all user inputs to be validated and
sanitized so that malicious scripts can't be injected into or run on our site.

Success: given I am adding or editing an employee, project, or task, when I
enter valid input, then it is accepted and saved.
Failure: given someone bypasses the frontend, when the server receives invalid
or malicious input, then it rejects it with an error and saves nothing.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Profile, Role
from accounts.services import RoleService
from common.errors import InvalidNote, InvalidProject, InvalidReport, InvalidTask, InvalidUser
from projects.models import ClientNote, Project
from projects.services import NewProject, ProjectService
from tasks.models import GanttReport, Task

from .validation import check_name, check_text, check_username

User = get_user_model()
START = date(2026, 12, 1)

SCRIPT = "<script>alert('XSS')</script>"
IMG = "<img src=x onerror=alert('XSS')>"
BOLD = "<b onmouseover=alert(1)>Demo</b>"


class Validators(SimpleTestCase):
    """The rules themselves: payloads are rejected, normal input is not."""

    def test_normal_names_are_allowed(self):
        for name in ["Website redesign", "Q&A prep (v2)", "Café launch", "Phase 2: beta / QA",
                     "Ship it!", "50% done", 'The "big" one', "O'Brien's task", "Launch — v2"]:
            check_name(name, InvalidTask)  # doesn't raise

    def test_names_with_tags_or_control_characters_are_rejected(self):
        for name in [SCRIPT, IMG, BOLD, "a<b", "a>b", "null\x00byte", "two\nlines"]:
            with self.assertRaisesMessage(InvalidTask, "Name contains invalid characters"):
                check_name(name, InvalidTask)

    def test_normal_text_is_allowed(self):
        for text in ["Costs < budget", "a < b > c", "x > 3 -> done", "<3 the new design",
                     "Line one\nLine two\r\n\tindented", "Email me at a@b.com"]:
            check_text(text, InvalidNote, "Note")

    def test_html_in_text_is_rejected(self):
        for text in [SCRIPT, IMG, BOLD, "hi </textarea>", "<SCRIPT>x", "<!-- x -->",
                     "<svg onload=alert(1)>"]:
            with self.assertRaisesMessage(InvalidNote, "Note can't contain HTML or script tags"):
                check_text(text, InvalidNote, "Note")

    def test_usernames_follow_djangos_rule(self):
        for name in ["alice", "j.doe", "jdoe@test.com", "a+b-c_d"]:
            check_username(name, InvalidUser)
        for name in [SCRIPT, "two words", "semi;colon"]:
            with self.assertRaisesMessage(InvalidUser, "Username contains invalid characters"):
                check_username(name, InvalidUser)


class Fixture(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin1", password="pw")  # always an admin
        self.project = Project.objects.create(name="Website redesign", start_date=START)
        self.project.members.add(self.admin)
        self.client.force_login(self.admin)


class TestCase1AddUser(Fixture):
    """Admin enters a <script> username on the Manage users page."""

    def test_page_rejects_script_username_and_saves_nothing(self):
        response = self.client.post(reverse("manage-users"), {
            "username": SCRIPT, "role": Role.TEAM_MEMBER,
            "password1": "TestPass123!", "password2": "TestPass123!",
        })
        self.assertContains(response, "Username contains invalid characters")
        self.assertNotContains(response, SCRIPT)  # shown escaped, if at all
        self.assertFalse(User.objects.filter(username=SCRIPT).exists())

    def test_server_rejects_it_even_without_the_form(self):
        with self.assertRaisesMessage(InvalidUser, "Username contains invalid characters"):
            RoleService().create_user(self.admin, SCRIPT, "TestPass123!", Role.TEAM_MEMBER)
        self.assertFalse(User.objects.filter(username=SCRIPT).exists())

    def test_valid_user_is_still_saved(self):
        RoleService().create_user(self.admin, "jdoe", "TestPass123!", Role.TEAM_MEMBER)
        self.assertTrue(User.objects.filter(username="jdoe").exists())


class TestCase2AddTaskThroughApi(Fixture):
    """Someone skips the schedule page and posts an <img onerror> title to the API."""

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.url = f"/api/projects/{self.project.pk}/tasks/"

    def post(self, **fields):
        return self.api.post(self.url, {"start_date": "2026-12-01", "end_date": "2026-12-05",
                                        **fields}, format="json")

    def test_api_rejects_malicious_title_with_400_and_saves_nothing(self):
        response = self.post(title=IMG)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Name contains invalid characters")
        self.assertFalse(Task.objects.exists())

    def test_api_rejects_script_in_description(self):
        response = self.post(title="Design", description=SCRIPT)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Description can't contain HTML or script tags")
        self.assertFalse(Task.objects.exists())

    def test_valid_task_is_still_saved(self):
        response = self.post(title="Q&A prep (v2)", description="Costs < budget")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Task.objects.get().title, "Q&A prep (v2)")

    def test_schedule_page_rejects_it_too(self):
        url = reverse("project-schedule", args=[self.project.pk])
        response = self.client.post(url, {"title": IMG, "start_date": "2026-12-01",
                                          "end_date": "2026-12-05"})
        self.assertContains(response, "Name contains invalid characters")
        self.assertFalse(Task.objects.exists())


class TestCase3NewProject(Fixture):
    def test_page_rejects_html_project_name_and_saves_nothing(self):
        response = self.client.post(reverse("new-project"),
                                    {"name": BOLD, "start_date": "2026-12-01"})
        self.assertContains(response, "Name contains invalid characters")
        self.assertFalse(Project.objects.filter(name=BOLD).exists())

    def test_server_rejects_it_even_without_the_form(self):
        with self.assertRaisesMessage(InvalidProject, "Name contains invalid characters"):
            ProjectService().create_project(self.admin, NewProject(BOLD, START))

    def test_valid_project_is_still_saved(self):
        ProjectService().create_project(self.admin, NewProject("Café launch & beta", START))
        self.assertTrue(Project.objects.filter(name="Café launch & beta").exists())


class FreeText(Fixture):
    """Client notes and Gantt chart reports."""

    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user("client1", password="pw")
        Profile.objects.create(user=self.owner, role=Role.CLIENT)
        self.project.owner = self.owner
        self.project.save()

    def test_client_note_with_script_is_rejected(self):
        from clients.services import ClientDashboardService
        with self.assertRaises(InvalidNote):
            ClientDashboardService().add_note(self.owner, self.project.pk, SCRIPT)
        self.assertFalse(ClientNote.objects.exists())

    def test_client_note_page_shows_the_error(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("client-project", args=[self.project.pk]),
                                    {"text": SCRIPT})
        self.assertContains(response, "contain HTML or script tags")
        self.assertFalse(ClientNote.objects.exists())

    def test_normal_note_is_still_saved(self):
        from clients.services import ClientDashboardService
        ClientDashboardService().add_note(self.owner, self.project.pk, "Budget < $5k, thanks!")
        self.assertEqual(ClientNote.objects.get().text, "Budget < $5k, thanks!")

    def test_gantt_report_with_html_is_rejected(self):
        from tasks.container import task_service
        with self.assertRaises(InvalidReport):
            task_service().report_gantt_problem(self.admin, self.project.pk, IMG)
        self.assertFalse(GanttReport.objects.exists())


class OutputIsEscaped(Fixture):
    """The second layer: text saved before these checks existed is shown, never run."""

    def test_old_malicious_title_is_displayed_as_text(self):
        Task.objects.create(project=self.project, title=SCRIPT)
        response = self.client.get(reverse("project-schedule", args=[self.project.pk]))
        self.assertNotContains(response, SCRIPT)
        self.assertContains(response, "&lt;script&gt;")
