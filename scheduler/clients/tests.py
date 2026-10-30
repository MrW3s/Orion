"""Tests written from the client dashboard story's acceptance criteria (given / when / then)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile, Role
from projects.access import ProjectAccess
from projects.models import ClientNote, Project
from tasks.models import Task, TaskStatus

from .services import ClientTask

User = get_user_model()
START = date(2026, 10, 19)


def make_client(username):
    user = User.objects.create_user(username, password="pw")
    Profile.objects.create(user=user, role=Role.CLIENT)
    return user


def add_task(project, title, status, start_day, end_day, **kwargs):
    return Task.objects.create(
        project=project, title=title, status=status, planned_start=date(2026, 10, start_day),
        scheduled_start=date(2026, 10, start_day), scheduled_end=date(2026, 10, end_day), **kwargs,
    )


class Fixture(TestCase):
    def setUp(self):
        self.carla = make_client("carla")
        self.otto = make_client("otto")
        self.alice = User.objects.create_user("alice", password="pw")  # works on both projects

        self.project = Project.objects.create(name="Website redesign", start_date=START,
                                              owner=self.carla)
        self.project.members.add(self.alice)
        design = add_task(self.project, "Design", TaskStatus.COMPLETE, 19, 21, assignee=self.alice,
                          description="Internal: reuse the 2024 logo files", is_critical=True)
        add_task(self.project, "Copywriting", TaskStatus.COMPLETE, 19, 22)
        build = add_task(self.project, "Build pages", TaskStatus.IN_PROGRESS, 22, 28, slack_days=2)
        build.depends_on.add(design)
        add_task(self.project, "QA", TaskStatus.TODO, 29, 30)

        self.other = Project.objects.create(name="Brand refresh", start_date=START, owner=self.otto)
        self.other.members.add(self.alice)
        add_task(self.other, "Secret rebrand", TaskStatus.TODO, 19, 20)

    def open(self, project_id, **kwargs):
        return self.client.get(reverse("client-project", args=[project_id]), **kwargs)

    def their_project(self):
        return reverse("client-project", args=[self.project.pk])


class ClientViewsProgress(Fixture):
    def test_client_views_their_projects_progress(self):
        # Given a client opens their project
        self.client.force_login(self.carla)
        response = self.open(self.project.pk)
        # Then they can view its progress
        self.assertContains(response, "Website redesign")
        self.assertContains(response, "<strong>50%</strong>", html=True)
        self.assertContains(response, "2 of 4 tasks complete")
        self.assertContains(response, "1 in progress")
        self.assertContains(response, "expected to finish Oct 30, 2026")
        for title in ("Design", "Copywriting", "Build pages", "QA"):
            self.assertContains(response, title)

    def test_internal_details_are_hidden(self):
        # When they have accessed their dashboard
        self.client.force_login(self.carla)
        response = self.open(self.project.pk)
        # Then they can't see internal project details
        self.assertNotContains(response, "reuse the 2024 logo files")  # task description
        self.assertNotContains(response, "alice")                      # assignee, team members
        for internal in ("Depends on", "Slack", "Critical", "Add a task", "Edit dependencies"):
            self.assertNotContains(response, internal)
        # ...because the page is only handed the fields a client may see, never the Task rows
        self.assertTrue(all(isinstance(t, ClientTask) for t in response.context["progress"].tasks))

    def test_home_takes_the_client_to_their_project(self):
        self.client.force_login(self.carla)
        self.assertRedirects(self.client.get(reverse("home"), follow=True), self.their_project())

    def test_client_with_several_projects_picks_from_a_list(self):
        Project.objects.create(name="Mobile app", start_date=START, owner=self.carla)
        self.client.force_login(self.carla)
        response = self.client.get(reverse("client-dashboard"))
        self.assertContains(response, "Website redesign")
        self.assertContains(response, "Mobile app")
        self.assertNotContains(response, "Brand refresh")

    def test_project_with_no_tasks_yet(self):
        empty = Project.objects.create(name="Mobile app", start_date=START, owner=self.carla)
        self.client.force_login(self.carla)
        self.assertContains(self.open(empty.pk), "The team hasn")

    def test_team_pages_stay_closed_to_clients(self):
        self.client.force_login(self.carla)
        # The team's schedule page sends them to their own view of the project
        self.assertRedirects(self.client.get(reverse("project-schedule", args=[self.project.pk])),
                             self.their_project())
        # The API (and the live-update socket, which uses the same check) is for members only
        self.assertEqual(self.client.get(f"/api/projects/{self.project.pk}/tasks/").status_code, 403)
        self.assertFalse(ProjectAccess().is_member(self.carla, self.project.pk))

    def test_client_added_as_a_member_still_only_gets_the_dashboard(self):
        self.project.members.add(self.carla)  # e.g. a team member whose role became Client
        self.client.force_login(self.carla)
        self.assertRedirects(self.client.get(reverse("project-schedule", args=[self.project.pk])),
                             self.their_project())
        self.assertFalse(ProjectAccess().is_member(self.carla, self.project.pk))


class ClientOpensAnotherPartysProject(Fixture):
    def assert_out_of_scope(self, response):
        self.assertRedirects(response, self.their_project())
        self.assertContains(response, "That project is out of scope for your permissions.")
        self.assertNotContains(response, "Brand refresh")
        self.assertNotContains(response, "Secret rebrand")

    def test_told_out_of_scope_and_sent_to_their_project(self):
        # Given a client is signed in
        self.client.force_login(self.carla)
        # When they try to view a project owned by another party
        response = self.open(self.other.pk, follow=True)
        # Then they're told it's out of scope for their permissions, and sent to their project
        self.assert_out_of_scope(response)

    def test_same_through_the_team_schedule_url(self):
        self.client.force_login(self.carla)
        self.assert_out_of_scope(
            self.client.get(reverse("project-schedule", args=[self.other.pk]), follow=True))

    def test_a_project_that_doesnt_exist_gets_the_same_answer(self):
        self.client.force_login(self.carla)
        self.assert_out_of_scope(self.open(9999, follow=True))

    def test_client_without_a_project_lands_on_their_empty_dashboard(self):
        self.client.force_login(make_client("nina"))
        response = self.open(self.project.pk, follow=True)
        self.assertRedirects(response, reverse("client-dashboard"))
        self.assertContains(response, "out of scope for your permissions")
        self.assertContains(response, "You don't have a project yet")


class ClientLeavesNotesForTheTeam(Fixture):
    def leave_note(self, project, text):
        return self.client.post(reverse("client-project", args=[project.pk]), {"text": text},
                                follow=True)

    def test_note_reaches_the_people_working_on_the_project(self):
        # Given a client is on their dashboard
        self.client.force_login(self.carla)
        # When they leave a note for the team
        response = self.leave_note(self.project, "Can we add a pricing page?")
        # Then it's saved and they see it among their notes
        self.assertContains(response, "Your note was sent to the project team.")
        self.assertContains(response, "Can we add a pricing page?")
        # ...and the team sees it on the project's schedule page
        self.client.force_login(self.alice)
        response = self.client.get(reverse("project-schedule", args=[self.project.pk]))
        self.assertContains(response, "Notes from the client")
        self.assertContains(response, "Can we add a pricing page?")
        self.assertContains(response, "carla")

    def test_empty_note_is_rejected(self):
        self.client.force_login(self.carla)
        response = self.leave_note(self.project, "   ")
        self.assertContains(response, "Write a note first.")
        self.assertFalse(ClientNote.objects.exists())

    def test_cannot_leave_a_note_on_another_partys_project(self):
        self.client.force_login(self.carla)
        response = self.leave_note(self.other, "Sneaky")
        self.assertContains(response, "out of scope for your permissions")
        self.assertFalse(ClientNote.objects.exists())


class OnlyClientsHaveTheDashboard(Fixture):
    def test_team_member_is_denied(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("client-dashboard")).status_code, 403)
        self.assertEqual(self.open(self.project.pk).status_code, 403)

    def test_logged_out_visitor_is_sent_to_login(self):
        response = self.client.get(reverse("client-dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('client-dashboard')}")
