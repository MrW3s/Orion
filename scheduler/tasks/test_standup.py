"""Tests for the standup story, from its acceptance criteria (given / when / then)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from common.errors import InvalidTask, NotAProjectMember
from notifications.publisher import InMemoryPublisher
from projects.access import ProjectAccess
from projects.models import Project
from scheduling import Scheduler

from .models import TaskEvent, TaskEventKind, TaskStatus
from .repository import TaskRepository
from .services import NewTask, TaskService

User = get_user_model()
START = date(2026, 10, 19)  # a Monday


def new_task(title, days=1, start=START, **kwargs) -> NewTask:
    return NewTask(title, start_date=start, end_date=start + timedelta(days=days - 1), **kwargs)


class StandupFixture(TestCase):
    def setUp(self):
        from accounts.models import Profile, Role
        self.sam = User.objects.create_user("sam", password="pw")  # scrum master
        Profile.objects.create(user=self.sam, role=Role.PROJECT_MANAGER)
        self.alice = User.objects.create_user("alice", password="pw")
        self.bob = User.objects.create_user("bob", password="pw")
        self.outsider = User.objects.create_user("eve", password="pw")
        self.project = Project.objects.create(name="Mobile app", start_date=START)
        self.project.members.add(self.sam, self.alice, self.bob)
        self.publisher = InMemoryPublisher()
        self.service = TaskService(TaskRepository(), Scheduler(), ProjectAccess(), self.publisher)

    def add(self, title, days=1, user=None, **kw):
        return self.service.add_task(user or self.alice, self.project.pk, new_task(title, days, **kw))

    def kinds(self, task):
        return [e.kind for e in TaskEvent.objects.filter(task=task)]


class ActivityLogIsRecorded(StandupFixture):
    """Every change the standup reviews is written to the activity log, with who and when."""

    def test_creating_a_task_logs_created_with_its_kind(self):
        bug = self.add("Crash on login", kind="bug")
        event = TaskEvent.objects.get(task=bug)
        self.assertEqual((event.kind, event.actor, event.new_value), ("created", self.alice, "bug"))

    def test_status_changes_log_in_progress_done_and_reopened(self):
        task = self.add("Design")
        self.service.update_status(self.bob, task.pk, TaskStatus.IN_PROGRESS)
        self.service.update_status(self.bob, task.pk, TaskStatus.COMPLETE)
        self.service.update_status(self.bob, task.pk, TaskStatus.TODO)
        self.assertEqual(self.kinds(task), ["created", "in_progress", "done", "reopened"])
        done = TaskEvent.objects.get(task=task, kind="done")
        self.assertEqual((done.old_value, done.new_value, done.actor), ("in_progress", "complete", self.bob))

    def test_unchanged_status_logs_nothing(self):
        task = self.add("Design")
        self.service.update_status(self.bob, task.pk, TaskStatus.TODO)
        self.assertEqual(self.kinds(task), ["created"])

    def test_block_and_unblock(self):
        task = self.add("API")
        task = self.service.set_blocked(self.bob, task.pk, "Waiting for API keys")
        self.assertTrue(task.is_blocked)
        self.assertEqual(task.blocked_reason, "Waiting for API keys")
        since = task.blocked_since
        # A new reason keeps the date it was first blocked
        task = self.service.set_blocked(self.bob, task.pk, "Still waiting for keys")
        self.assertEqual(task.blocked_since, since)
        with self.captureOnCommitCallbacks(execute=True):
            task = self.service.unblock(self.alice, task.pk)
        self.assertFalse(task.is_blocked)
        self.assertEqual(self.kinds(task), ["created", "blocked", "blocked", "unblocked"])
        self.assertEqual(self.publisher.events[-1].type, "task.changed")

    def test_blocking_needs_a_reason(self):
        task = self.add("API")
        with self.assertRaises(InvalidTask):
            self.service.set_blocked(self.bob, task.pk, "  ")
        self.assertEqual(self.kinds(task), ["created"])

    def test_reassign_logs_old_and_new_assignee(self):
        task = self.add("API", assignee_id=self.alice.pk)
        self.service.reassign(self.sam, task.pk, self.bob.pk)
        event = TaskEvent.objects.get(task=task, kind="reassigned")
        self.assertEqual((event.old_value, event.new_value), (str(self.alice.pk), str(self.bob.pk)))

    def test_reassign_to_outsider_is_rejected(self):
        task = self.add("API")
        with self.assertRaises(InvalidTask):
            self.service.reassign(self.sam, task.pk, self.outsider.pk)

    def test_outsider_cannot_block(self):
        task = self.add("API")
        with self.assertRaises(NotAProjectMember):
            self.service.set_blocked(self.outsider, task.pk, "nope")

    def test_engine_moving_a_due_date_logs_rescheduled(self):
        design = self.add("Design", days=2)   # Oct 19-20
        build = self.add("Build", days=2)     # Oct 19-20, no dependency yet
        # When Build is made to wait for Design, its due date moves to Oct 22
        self.service.set_dependencies(self.sam, build.pk, [design.pk])
        event = TaskEvent.objects.get(task=build, kind=TaskEventKind.RESCHEDULED)
        self.assertEqual((event.old_value, event.new_value), ("2026-10-20", "2026-10-22"))
        self.assertEqual(event.actor, self.sam)
        # A brand-new task's first dates aren't a move
        self.assertFalse(TaskEvent.objects.filter(task=design, kind="rescheduled").exists())


class UpdateTaskFromSchedulePage(StandupFixture):
    def test_form_saves_only_what_changed(self):
        task = self.add("API")
        self.client.force_login(self.bob)
        url = reverse("project-schedule", args=[self.project.pk])
        self.client.post(url, {"upd-task_id": task.pk, "upd-status": "in_progress",
                               "upd-assignee_id": self.bob.pk, "upd-blocked": "on",
                               "upd-blocked_reason": "Needs design sign-off"})
        self.assertEqual(self.kinds(task), ["created", "in_progress", "reassigned", "blocked"])

    def test_blocked_without_reason_is_an_error(self):
        task = self.add("API")
        self.client.force_login(self.bob)
        response = self.client.post(reverse("project-schedule", args=[self.project.pk]),
                                    {"upd-task_id": task.pk, "upd-status": "todo",
                                     "upd-assignee_id": "", "upd-blocked": "on"})
        self.assertContains(response, "Say what the task is blocked on.")
        self.assertEqual(self.kinds(task), ["created"])
