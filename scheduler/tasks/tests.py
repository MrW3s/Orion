"""Tests written from the Sprint 1 acceptance criteria (given / when / then)."""
from datetime import date

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
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


class Fixture(TransactionTestCase):
    """TransactionTestCase so transaction.on_commit() callbacks really run."""

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw")
        self.bob = User.objects.create_user("bob", password="pw")
        self.outsider = User.objects.create_user("eve", password="pw")
        self.project = Project.objects.create(name="Website redesign", start_date=date(2026, 10, 19))
        self.project.members.add(self.alice, self.bob)

        self.publisher = InMemoryPublisher()
        self.service = TaskService(TaskRepository(), Scheduler(), ProjectAccess(), self.publisher)


class Story1AddTask(Fixture):
    def test_new_task_is_placed_into_schedule(self):
        # Given a team member is on the site
        design = self.service.add_task(self.alice, self.project.pk, NewTask("Design", duration_days=3))
        # When they add a task that depends on another
        build = self.service.add_task(
            self.alice, self.project.pk,
            NewTask("Build", duration_days=2, depends_on_ids=[design.pk]),
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
            self.service.add_task(self.outsider, self.project.pk, NewTask("Sneaky"))

    def test_dependency_from_other_project_rejected(self):
        from common.errors import InvalidDependency
        other = Project.objects.create(name="Other", start_date=date(2026, 10, 19))
        foreign = Task.objects.create(project=other, title="Foreign")
        with self.assertRaises(InvalidDependency):
            self.service.add_task(self.alice, self.project.pk,
                                  NewTask("Bad", depends_on_ids=[foreign.pk]))
        self.assertFalse(Task.objects.filter(title="Bad").exists())


class Story2UpdateStatus(Fixture):
    def test_status_saved_and_broadcast(self):
        task = self.service.add_task(self.alice, self.project.pk, NewTask("Write copy"))
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
        task = self.service.add_task(self.alice, self.project.pk, NewTask("Write copy"))
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
        r = client.post(f"/api/projects/{self.project.pk}/tasks/", {"title": "x"}, format="json")
        self.assertEqual(r.status_code, 403)

        client.force_authenticate(self.alice)
        r = client.post(f"/api/projects/{self.project.pk}/tasks/", {"title": "Plan"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["scheduled_start"], "2026-10-19")
        r = client.get(f"/api/projects/{self.project.pk}/tasks/")
        self.assertEqual([t["title"] for t in r.json()], ["Plan"])
