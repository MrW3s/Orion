"""Tests written from the Sprint 1 acceptance criteria (given / when / then)."""
from datetime import date, timedelta

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from config.asgi import application
from notifications.publisher import InMemoryPublisher
from projects.access import ProjectAccess
from projects.models import Project
from scheduling import Scheduler

from .models import Task, TaskStatus
from .repository import TaskRepository
from .services import NewTask, TaskService

User = get_user_model()
START = date(2026, 10, 19)  # the project's start date


def new_task(title, days=1, start=START, **kwargs) -> NewTask:
    return NewTask(title, start_date=start, end_date=start + timedelta(days=days - 1), **kwargs)


class Fixture(TransactionTestCase):
    """TransactionTestCase so transaction.on_commit() callbacks really run."""

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw")
        self.bob = User.objects.create_user("bob", password="pw")
        self.outsider = User.objects.create_user("eve", password="pw")
        self.project = Project.objects.create(name="Website redesign", start_date=START)
        self.project.members.add(self.alice, self.bob)

        self.publisher = InMemoryPublisher()
        self.service = TaskService(TaskRepository(), Scheduler(), ProjectAccess(), self.publisher)


class Story1AddTask(Fixture):
    def test_new_task_is_placed_into_schedule(self):
        # Given a team member is on the site
        design = self.service.add_task(self.alice, self.project.pk, new_task("Design", days=3))
        # When they add a task that depends on another
        build = self.service.add_task(
            self.alice, self.project.pk,
            new_task("Build", days=2, depends_on_ids=[design.pk]),
        )
        # Then the graph puts it into the schedule
        self.assertEqual(design.scheduled_start, date(2026, 10, 19))
        self.assertEqual(build.scheduled_start, date(2026, 10, 22))
        self.assertEqual(build.scheduled_end, date(2026, 10, 23))
        # ...and other members are told the schedule changed
        self.assertEqual(self.publisher.events[-1].type, "schedule.changed")

    def test_outsider_cannot_add(self):
        from common.errors import NotAProjectMember
        with self.assertRaises(NotAProjectMember):
            self.service.add_task(self.outsider, self.project.pk, new_task("Sneaky"))

    def test_dependency_from_other_project_rejected(self):
        from common.errors import InvalidDependency
        other = Project.objects.create(name="Other", start_date=date(2026, 10, 19))
        foreign = Task.objects.create(project=other, title="Foreign")
        with self.assertRaises(InvalidDependency):
            self.service.add_task(self.alice, self.project.pk,
                                  new_task("Bad", depends_on_ids=[foreign.pk]))
        self.assertFalse(Task.objects.filter(title="Bad").exists())


    def test_new_task_is_not_started_and_keeps_its_dates(self):
        task = self.service.add_task(self.alice, self.project.pk,
                                     new_task("Copy", days=3, start=date(2026, 10, 21)))
        self.assertEqual(task.status, TaskStatus.TODO)
        self.assertEqual(task.get_status_display(), "Not started")
        self.assertEqual((task.scheduled_start, task.scheduled_end), (date(2026, 10, 21), date(2026, 10, 23)))
        self.assertEqual(task.duration_days, 3)
        self.assertFalse(task.moved_by_dependencies)

    def test_dependency_moves_task_later_and_keeps_its_length(self):
        design = self.service.add_task(self.alice, self.project.pk, new_task("Design", days=5))
        build = self.service.add_task(self.alice, self.project.pk,
                                      new_task("Build", days=2, depends_on_ids=[design.pk]))
        self.assertEqual(list(build.depends_on.all()), [design])  # dependencies saved
        self.assertEqual((build.scheduled_start, build.scheduled_end), (date(2026, 10, 24), date(2026, 10, 25)))
        self.assertTrue(build.moved_by_dependencies)

    def test_end_before_start_rejected(self):
        from common.errors import InvalidTask
        with self.assertRaises(InvalidTask):
            self.service.add_task(self.alice, self.project.pk,
                                  NewTask("Backwards", start_date=date(2026, 10, 22), end_date=date(2026, 10, 20)))
        self.assertFalse(Task.objects.exists())

    def test_start_before_project_start_rejected(self):
        from common.errors import InvalidTask
        with self.assertRaises(InvalidTask):
            self.service.add_task(self.alice, self.project.pk, new_task("Early", start=date(2026, 10, 1)))
        self.assertFalse(Task.objects.exists())

    def test_api_requires_name_and_dates(self):
        # Given a team member is on the site to add a new task
        client = APIClient()
        client.force_authenticate(self.alice)
        url = f"/api/projects/{self.project.pk}/tasks/"
        # When they submit it without a name, or without a duration estimate (dates)
        for body in ({"start_date": "2026-10-19", "end_date": "2026-10-20"},
                     {"title": "No dates"},
                     {"title": "No end", "start_date": "2026-10-19"}):
            r = client.post(url, body, format="json")
            # Then the system shows an error...
            self.assertEqual(r.status_code, 400, body)
        # ...and the task is not added to the schedule
        self.assertFalse(Task.objects.exists())


class Story2UpdateStatus(Fixture):
    def test_status_saved_and_broadcast(self):
        task = self.service.add_task(self.alice, self.project.pk, new_task("Write copy"))
        # Given bob is viewing the schedule; when he marks it in progress
        self.service.update_status(self.bob, task.pk, TaskStatus.IN_PROGRESS)
        # Then it is saved...
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        # ...and reflected for every relevant member
        event = self.publisher.events[-1]
        self.assertEqual(event.type, "task.status_changed")
        self.assertEqual(event.data["status"], "in_progress")

    def test_same_status_does_not_broadcast(self):
        task = self.service.add_task(self.alice, self.project.pk, new_task("Write copy"))
        before = len(self.publisher.events)
        self.service.update_status(self.bob, task.pk, TaskStatus.TODO)
        self.assertEqual(len(self.publisher.events), before)


class ApiAndRealtime(Fixture):
    """End to end: REST call by one user -> WebSocket message to another."""

    def test_status_change_reaches_other_members_websocket(self):
        task = Task.objects.create(project=self.project, title="Launch")

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/projects/{self.project.pk}/",
                                                 headers=[(b"origin", b"http://localhost")])
            communicator.scope["user"] = self.bob  # bob has the schedule open
            connected, _ = await communicator.connect()
            assert connected

            from asgiref.sync import sync_to_async

            @sync_to_async
            def alice_patches():
                client = APIClient()
                client.force_authenticate(self.alice)
                return client.patch(f"/api/tasks/{task.pk}/status/", {"status": "complete"},
                                    format="json")

            response = await alice_patches()
            message = await communicator.receive_json_from(timeout=2)
            await communicator.disconnect()
            return response, message

        response, message = async_to_sync(scenario)()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(message["type"], "task.status_changed")
        self.assertEqual(message["data"]["status"], "complete")

    def test_outsider_websocket_rejected(self):
        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/projects/{self.project.pk}/",
                                                 headers=[(b"origin", b"http://localhost")])
            communicator.scope["user"] = self.outsider
            connected, _ = await communicator.connect()
            return connected

        self.assertFalse(async_to_sync(scenario)())

    def test_api_maps_errors_to_http(self):
        client = APIClient()
        client.force_authenticate(self.outsider)
        r = client.post(f"/api/projects/{self.project.pk}/tasks/", {"title": "x", "start_date": "2026-10-19", "end_date": "2026-10-19"},
                        format="json")
        self.assertEqual(r.status_code, 403)

        client.force_authenticate(self.alice)
        r = client.post(f"/api/projects/{self.project.pk}/tasks/", {"title": "Plan", "start_date": "2026-10-19", "end_date": "2026-10-21"},
                        format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["scheduled_start"], "2026-10-19")
        r = client.get(f"/api/projects/{self.project.pk}/tasks/")
        self.assertEqual([t["title"] for t in r.json()], ["Plan"])


class Story1SchedulePage(TestCase):
    """The "Add a task" form on /projects/<id>/ (plain TestCase: no real-time needed here)."""

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw")
        self.outsider = User.objects.create_user("eve", password="pw")
        self.project = Project.objects.create(name="Website redesign", start_date=START)
        self.project.members.add(self.alice)
        self.url = reverse("project-schedule", args=[self.project.pk])
        self.client.force_login(self.alice)

    def submit(self, **fields):
        form = {"title": "Design", "start_date": "2026-10-19", "end_date": "2026-10-21"}
        form.update(fields)
        return self.client.post(self.url, form, follow=True)

    def test_added_task_appears_in_schedule_as_not_started(self):
        # Given a team member is on the site; when they add a new task
        response = self.submit()
        # Then it appears in the schedule list with status Not started
        self.assertContains(response, "Added “Design” to the schedule.")
        self.assertContains(response, "Not started")
        self.assertContains(response, "Oct 21")
        self.assertEqual(Task.objects.get().duration_days, 3)

    def test_dependencies_from_form_are_saved(self):
        self.submit()
        design = Task.objects.get()
        self.submit(title="Build", depends_on_ids=[design.pk])
        self.assertEqual(list(Task.objects.get(title="Build").depends_on.all()), [design])

    def test_missing_name_shows_error_and_adds_nothing(self):
        response = self.submit(title="")
        self.assertContains(response, "The task wasn")
        self.assertContains(response, "Give the task a name.")
        self.assertFalse(Task.objects.exists())

    def test_missing_dates_show_error_and_add_nothing(self):
        response = self.submit(start_date="", end_date="")
        self.assertContains(response, "Pick a start date.")
        self.assertContains(response, "Pick an end date.")
        self.assertFalse(Task.objects.exists())

    def test_end_before_start_shows_error_and_adds_nothing(self):
        response = self.submit(start_date="2026-10-22", end_date="2026-10-20")
        self.assertContains(response, "The end date can")
        self.assertFalse(Task.objects.exists())

    def test_non_member_cannot_see_schedule(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"title": "x"}).status_code, 403)

    def test_home_links_to_project_schedule(self):
        self.assertContains(self.client.get(reverse("home")), self.url)
