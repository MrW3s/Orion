"""Tests for the standup story, from its acceptance criteria (given / when / then)."""
from datetime import date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from common.errors import InvalidStandupOrder, InvalidTask, InvalidWindow, NotAProjectMember
from notifications.publisher import InMemoryPublisher
from projects.access import ProjectAccess
from projects.models import Project
from scheduling import Scheduler

from .models import Task, TaskEvent, TaskEventKind, TaskStatus
from .repository import TaskRepository
from .services import NewTask, TaskService
from .standup import (
    build_window, group_markers, previous_working_day, value_at, working_days_between,
)
from .standup_service import StandupService

User = get_user_model()
START = date(2026, 10, 19)  # a Monday
NY = ZoneInfo("America/New_York")  # settings.TIME_ZONE


def at(day: int, hour: int = 9, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=NY)


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

    def did(self, when, fn, *args, **kwargs):
        """Run a service call, then date the log entries (and task) it wrote at `when`."""
        before = set(TaskEvent.objects.values_list("pk", flat=True))
        result = fn(*args, **kwargs)
        new = TaskEvent.objects.exclude(pk__in=before)
        new.update(created_at=when)
        if isinstance(result, Task):
            for task_id, kind in new.values_list("task_id", "kind"):
                if kind == "created":
                    Task.objects.filter(pk=task_id).update(created_at=when)
                if kind == "blocked":
                    Task.objects.filter(pk=task_id, blocked_since__isnull=False).update(blocked_since=when)
            result.refresh_from_db()
        return result

    def add_at(self, when, title, days=1, user=None, **kw):
        return self.did(when, self.add, title, days, user, **kw)


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

    def test_blocked_reason_rejects_html(self):
        # Security story 1: same rule as descriptions, notes and reports
        task = self.add("API")
        with self.assertRaises(InvalidTask):
            self.service.set_blocked(self.bob, task.pk, "<script>alert(1)</script>")
        self.assertFalse(TaskRepository().get(task.pk).is_blocked)
        self.service.set_blocked(self.bob, task.pk, "Waiting on keys (cost < budget)")  # plain "<" is fine

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


# ---- Time window (AC2) ------------------------------------------------
class WindowRules(SimpleTestCase):
    def test_since_last_standup_looks_back_to_the_previous_working_day(self):
        window = build_window("since_last", at(11, 10), NY)  # Wednesday
        self.assertEqual(window.start, at(10, 0))              # Tuesday 00:00
        self.assertEqual(window.end, at(11, 10))
        self.assertEqual(window.label, "Since Tue, Nov 10")

    def test_monday_looks_back_to_friday(self):
        window = build_window("since_last", at(16, 9, 30), NY)  # Monday
        self.assertEqual(window.start, at(13, 0))                # Friday 00:00
        self.assertEqual(window.label, "Since Fri, Nov 13")

    def test_weekend_also_looks_back_to_friday(self):
        self.assertEqual(previous_working_day(date(2026, 11, 15)), date(2026, 11, 13))  # Sunday
        self.assertEqual(previous_working_day(date(2026, 11, 14)), date(2026, 11, 13))  # Saturday

    def test_default_is_since_last_standup(self):
        self.assertEqual(build_window(None, at(11, 10), NY).key, "since_last")

    def test_today_and_last_24h(self):
        self.assertEqual(build_window("today", at(11, 10), NY).start, at(11, 0))
        self.assertEqual(build_window("24h", at(11, 10), NY).start, at(10, 10))

    def test_custom_range_covers_whole_days(self):
        window = build_window("custom", at(20, 10), NY, date(2026, 11, 2), date(2026, 11, 6))
        self.assertEqual((window.start, window.end), (at(2, 0), at(7, 0)))
        self.assertEqual(window.label, "Nov 2 – Nov 6")

    def test_custom_range_ending_today_stops_at_now(self):
        window = build_window("custom", at(11, 10), NY, date(2026, 11, 9), date(2026, 11, 11))
        self.assertEqual(window.end, at(11, 10))

    def test_bad_custom_ranges_are_rejected(self):
        now = at(11, 10)
        for start, end in [(None, date(2026, 11, 2)), (date(2026, 11, 6), date(2026, 11, 2)),
                           (date(2026, 11, 12), date(2026, 11, 13)),
                           (date(2026, 1, 1), date(2026, 11, 1))]:
            with self.subTest(start=start, end=end), self.assertRaises(InvalidWindow):
                build_window("custom", now, NY, start, end)
        with self.assertRaises(InvalidWindow):
            build_window("last_week", now, NY)

    def test_previous_window_is_the_same_length_just_before(self):
        window = build_window("since_last", at(11, 10), NY)
        previous = window.previous()
        self.assertEqual(previous.end, window.start)
        self.assertEqual(previous.end - previous.start, window.end - window.start)

    def test_working_days_skip_weekends(self):
        self.assertEqual(working_days_between(date(2026, 11, 9), date(2026, 11, 11)), 2)  # Mon -> Wed
        self.assertEqual(working_days_between(date(2026, 11, 13), date(2026, 11, 16)), 1)  # Fri -> Mon
        self.assertEqual(working_days_between(date(2026, 11, 11), date(2026, 11, 11)), 0)

    def test_value_at_reads_the_first_change_after_the_moment(self):
        changes = [(at(9), "todo"), (at(10), "in_progress")]  # (when, old value)
        self.assertEqual(value_at(at(8), "complete", changes), "todo")
        self.assertEqual(value_at(at(9, 12), "complete", changes), "in_progress")
        self.assertEqual(value_at(at(11), "complete", changes), "complete")


# ---- Timeline grouping (AC4) --------------------------------------------
class TimelineGrouping(SimpleTestCase):
    def events(self, n, start=at(10, 9)):
        return [{"at": start + timedelta(minutes=5 * i), "kind": "done" if i % 2 else "created"}
                for i in range(n)]

    def test_up_to_30_events_get_a_marker_each(self):
        grouped, markers = group_markers(self.events(30), NY)
        self.assertFalse(grouped)
        self.assertEqual(len(markers), 30)
        self.assertTrue(all(m.count == 1 for m in markers))

    def test_more_than_30_events_share_one_marker_per_hour(self):
        grouped, markers = group_markers(self.events(31), NY)  # 9:00 to 11:30, every 5 minutes
        self.assertTrue(grouped)
        self.assertEqual([m.count for m in markers], [12, 12, 7])
        self.assertEqual(markers[0].at, at(10, 9))
        self.assertEqual(markers[0].kind, "mixed")

    def test_an_hour_of_one_kind_keeps_its_kind(self):
        events = [{"at": at(10, 9, i), "kind": "done"} for i in range(31)]
        _, markers = group_markers(events, NY)
        self.assertEqual([(m.kind, m.count) for m in markers], [("done", 31)])


# ---- Aggregation (AC3, 5, 6, 7) ------------------------------------------
class StandupAggregation(StandupFixture):
    """Wednesday Nov 11, 10:00. The window is "since last standup": Tuesday 00:00 to now.
    The previous window is the 34 hours before that."""

    NOW = at(11, 10)

    def setUp(self):
        super().setUp()
        self.standups = StandupService(TaskRepository(), Scheduler(), ProjectAccess())
        self.design = self.add_at(at(2), "Design", 2, assignee_id=self.alice.pk)
        self.api = self.add_at(at(2), "API", user=self.bob, assignee_id=self.bob.pk)
        self.did(at(6), self.service.set_blocked, self.bob, self.api.pk, "Waiting for API keys")
        # Previous window (Sun 14:00 to Tue 00:00)
        self.did(at(9, 11), self.service.update_status, self.alice, self.design.pk, "in_progress")
        self.old_bug = self.add_at(at(9, 12), "Old bug", kind="bug")
        # This window
        self.did(at(10, 11), self.service.update_status, self.alice, self.design.pk, "complete")
        self.did(at(10, 15), self.service.update_status, self.bob, self.api.pk, "in_progress")
        self.crash = self.add_at(at(10, 9), "Crash on login", user=self.bob, kind="bug")

    def standup(self, user=None, **kw):
        return self.standups.standup(user or self.sam, self.project.pk, now=self.NOW, **kw)

    def test_tiles_count_the_window_and_compare_with_the_one_before(self):
        tiles = {t["key"]: t for t in self.standup()["tiles"]}
        expect = {  # key: (count, previous, delta)
            "completed": (1, 0, 1), "in_progress": (1, 1, 0), "blocked": (1, 1, 0),
            "active_members": (2, 1, 1), "overdue": (3, 3, 0), "bugs_created": (1, 1, 0),
        }
        for key, numbers in expect.items():
            with self.subTest(key):
                t = tiles[key]
                self.assertEqual((t["count"], t["previous"], t["delta"]), numbers)
        self.assertEqual(tiles["completed"]["task_ids"], [self.design.pk])
        self.assertEqual(tiles["bugs_created"]["task_ids"], [self.crash.pk])
        self.assertEqual(tiles["overdue"]["task_ids"],
                         sorted([self.api.pk, self.crash.pk, self.old_bug.pk]))

    def test_unblocking_shows_in_the_blocked_delta(self):
        self.did(at(11, 9), self.service.unblock, self.bob, self.api.pk)
        blocked = next(t for t in self.standup()["tiles"] if t["key"] == "blocked")
        self.assertEqual((blocked["count"], blocked["previous"], blocked["delta"]), (0, 1, -1))

    def test_timeline_lists_the_window_events_with_task_and_person(self):
        timeline = self.standup()["timeline"]
        self.assertFalse(timeline["grouped"])
        self.assertEqual([(m["kind"], m["events"][0]["task"], m["events"][0]["person"])
                          for m in timeline["markers"]],
                         [("created", "Crash on login", "bob"), ("done", "Design", "alice"),
                          ("in_progress", "API", "bob")])
        self.assertEqual(len(timeline["legend"]), 7)

    def test_person_cards(self):
        cards = {c["name"]: c for c in self.standup()["people"]}
        self.assertEqual(list(cards), ["alice", "bob", "sam"])  # no saved order yet: by name
        self.assertEqual(cards["alice"]["completed"], [{"id": self.design.pk, "title": "Design"}])
        self.assertEqual(cards["bob"]["in_progress"], [{"id": self.api.pk, "title": "API"}])
        self.assertEqual(cards["bob"]["blocked"][0]["reason"], "Waiting for API keys")
        self.assertTrue(cards["alice"]["active"])
        self.assertFalse(cards["sam"]["active"])  # "No activity in window."

    def test_saved_order_is_used_and_shared(self):
        self.standups.save_order(self.alice, self.project.pk, [self.sam.pk, self.bob.pk])
        self.assertEqual([c["name"] for c in self.standup(user=self.bob)["people"]],
                         ["sam", "bob", "alice"])

    def test_order_must_name_team_members_once(self):
        with self.assertRaises(InvalidStandupOrder):
            self.standups.save_order(self.sam, self.project.pk, [self.outsider.pk])
        with self.assertRaises(InvalidStandupOrder):
            self.standups.save_order(self.sam, self.project.pk, [self.bob.pk, self.bob.pk])

    def test_blockers_oldest_first_with_working_days(self):
        newer = self.add_at(at(2), "Payments")
        self.did(at(10, 16), self.service.set_blocked, self.alice, newer.pk, "Needs legal review")
        blockers = self.standup()["blockers"]
        self.assertEqual([b["title"] for b in blockers], ["API", "Payments"])
        self.assertEqual((blockers[0]["days_blocked"], blockers[0]["stale"]), (3, True))  # Fri -> Wed
        self.assertEqual((blockers[1]["days_blocked"], blockers[1]["stale"]), (1, False))
        self.assertEqual(blockers[0]["owner"], "bob")

    def test_outsider_gets_not_a_member(self):
        with self.assertRaises(NotAProjectMember):
            self.standup(user=self.outsider)

    def test_one_failing_section_does_not_blank_the_others(self):
        with mock.patch.object(StandupService, "_timeline", side_effect=RuntimeError("boom")), \
                self.assertLogs("tasks.standup_service", "ERROR"):
            data = self.standup()
        self.assertIn("error", data["timeline"])
        self.assertEqual(len(data["tiles"]), 6)
        self.assertEqual(len(data["people"]), 3)

    def test_sections_can_be_asked_for_one_at_a_time(self):
        data = self.standup(sections=["blockers"])
        self.assertIn("blockers", data)
        self.assertNotIn("tiles", data)


class ScheduleHealth(StandupFixture):
    """Design -> Build -> Launch is the critical path; Docs hangs off Design with slack."""

    NOW = at(11, 10)

    def setUp(self):
        super().setUp()
        self.standups = StandupService(TaskRepository(), Scheduler(), ProjectAccess())
        self.design = self.add_at(at(2), "Design", 2)
        self.build = self.add_at(at(2), "Build", 2, depends_on_ids=[self.design.pk])
        self.launch = self.add_at(at(2), "Launch", 1, depends_on_ids=[self.build.pk])
        self.docs = self.add_at(at(2), "Docs", 1, depends_on_ids=[self.design.pk])

    def health(self):
        return self.standups.standup(self.sam, self.project.pk, now=self.NOW)["schedule_health"]

    def test_critical_path_comes_from_the_engine(self):
        health = self.health()
        self.assertEqual([t["title"] for t in health["critical_path"]], ["Design", "Build", "Launch"])
        self.assertEqual(health["critical_path"][-1]["due"], date(2026, 10, 23))
        self.assertEqual((health["slipped"], health["downstream_moved"]), ([], []))

    def test_slip_on_the_critical_path_and_what_moved_downstream(self):
        # In the window, Design is made to wait for 3 days of research
        research = self.add_at(at(10, 9), "Research", 3)
        self.did(at(10, 10), self.service.set_dependencies, self.sam, self.design.pk, [research.pk])
        health = self.health()
        slipped = {t["title"]: (t["from"], t["to"], t["days"]) for t in health["slipped"]}
        self.assertEqual(slipped["Design"], (date(2026, 10, 20), date(2026, 10, 23), 3))
        self.assertEqual(set(slipped), {"Design", "Build", "Launch"})
        self.assertEqual([(t["title"], t["because_of"]) for t in health["downstream_moved"]],
                         [("Docs", ["Design"])])
        self.assertTrue(all(t["slipped"] for t in health["critical_path"] if t["title"] != "Research"))

    def test_forecast_says_it_is_not_available(self):
        self.assertFalse(self.health()["forecast"]["available"])


class StandupPerformance(StandupFixture):
    """AC8: under 2 seconds for 500 tasks and 2,000 events."""

    def test_500_tasks_and_2000_events(self):
        import time
        from .models import TaskEvent as E
        now = at(11, 10)
        tasks = Task.objects.bulk_create([
            Task(project=self.project, title=f"Task {i}", duration_days=1, planned_start=START,
                 scheduled_start=START, scheduled_end=START, assignee=self.alice if i % 2 else self.bob,
                 status="in_progress" if i % 3 else "todo")
            for i in range(500)])
        Task.objects.update(created_at=at(1))
        E.objects.bulk_create([
            E(project=self.project, task=tasks[i % 500], actor=self.alice,
              kind=["created", "in_progress", "done", "blocked", "unblocked"][i % 5],
              old_value="todo", created_at=now - timedelta(minutes=i))
            for i in range(2000)])
        standups = StandupService(TaskRepository(), Scheduler(), ProjectAccess())
        started = time.perf_counter()
        data = standups.standup(self.sam, self.project.pk, now=now)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        self.assertTrue(data["timeline"]["grouped"])
        self.assertTrue(all("error" not in data[s] for s in ("tiles", "people", "blockers")
                            if isinstance(data[s], dict)))


# ---- API: one endpoint, members only (AC1, AC8) -----------------------------
class StandupApi(StandupFixture):
    def setUp(self):
        super().setUp()
        self.add("Design")
        self.api = APIClient()
        self.url = reverse("project-standup-api", args=[self.project.pk])

    def test_member_gets_every_section(self):
        self.api.force_authenticate(self.alice)
        response = self.api.get(self.url)
        self.assertEqual(response.status_code, 200)
        for key in ("window", "previous_window", "generated_at", "tiles", "tasks", "timeline",
                    "people", "schedule_health", "blockers"):
            self.assertIn(key, response.data)
        self.assertEqual(response.data["window"]["key"], "since_last")

    def test_non_members_get_403(self):
        from accounts.models import Profile, Role
        client = User.objects.create_user("client2", password="pw")
        Profile.objects.create(user=client, role=Role.CLIENT)
        self.project.owner = client
        self.project.save()
        for user in (self.outsider, client):
            with self.subTest(user.username):
                self.api.force_authenticate(user)
                self.assertEqual(self.api.get(self.url).status_code, 403)

    def test_anonymous_gets_403(self):
        self.assertEqual(self.api.get(self.url).status_code, 403)

    def test_window_options(self):
        self.api.force_authenticate(self.alice)
        for query, key in [({"window": "today"}, "today"), ({"window": "24h"}, "24h"),
                           ({"window": "custom", "from": "2026-11-02", "to": "2026-11-06"}, "custom")]:
            with self.subTest(key):
                self.assertEqual(self.api.get(self.url, query).data["window"]["key"], key)

    def test_bad_window_is_400(self):
        self.api.force_authenticate(self.alice)
        for query in [{"window": "forever"}, {"window": "custom", "from": "2026-11-06", "to": "2026-11-02"},
                      {"window": "custom"}, {"sections": "tiles,weather"}]:
            with self.subTest(query=query):
                self.assertEqual(self.api.get(self.url, query).status_code, 400)

    def test_retry_one_section(self):
        self.api.force_authenticate(self.alice)
        data = self.api.get(self.url, {"sections": "people"}).data
        self.assertIn("people", data)
        self.assertNotIn("tiles", data)

    def test_save_order(self):
        self.api.force_authenticate(self.bob)
        url = reverse("project-standup-order", args=[self.project.pk])
        response = self.api.put(url, {"user_ids": [self.bob.pk, self.sam.pk]}, format="json")
        self.assertEqual(response.data["user_ids"], [self.bob.pk, self.sam.pk, self.alice.pk])
        self.assertEqual(self.api.put(url, {"user_ids": [self.outsider.pk]}, format="json").status_code, 400)
        self.api.force_authenticate(self.outsider)
        self.assertEqual(self.api.put(url, {"user_ids": []}, format="json").status_code, 403)


# ---- The page (AC1) -------------------------------------------------------
class StandupPage(StandupFixture):
    def test_member_sees_the_page_with_a_project_selector(self):
        other = Project.objects.create(name="Website", start_date=START)
        other.members.add(self.alice)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("project-standup", args=[self.project.pk]))
        self.assertContains(response, 'id="standup"')
        self.assertContains(response, reverse("project-standup-api", args=[self.project.pk]))
        self.assertContains(response, "tasks/standup.js")
        self.assertContains(response, ">Website</option>")

    def test_window_from_the_url_is_preselected(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("project-standup", args=[self.project.pk]),
                                   {"window": "custom", "from": "2026-11-02", "to": "2026-11-06"})
        self.assertContains(response, '<option value="custom" selected>')
        self.assertContains(response, 'value="2026-11-02"')

    def test_outsider_gets_403_and_client_goes_to_their_dashboard(self):
        from accounts.models import Profile, Role
        self.client.force_login(self.outsider)
        url = reverse("project-standup", args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        client = User.objects.create_user("client2", password="pw")
        Profile.objects.create(user=client, role=Role.CLIENT)
        self.client.force_login(client)
        self.assertRedirects(self.client.get(url), reverse("client-project", args=[self.project.pk]),
                             fetch_redirect_response=False)

    def test_schedule_page_links_to_the_standup(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("project-schedule", args=[self.project.pk]))
        self.assertContains(response, reverse("project-standup", args=[self.project.pk]))


class SeedDemo(TestCase):
    def test_seed_builds_a_realistic_project_and_can_be_rebuilt(self):
        from io import StringIO
        from django.core.management import call_command
        call_command("seed_standup_demo", stdout=StringIO())
        project = Project.objects.get(name="Mobile App Launch (demo)")
        sam = User.objects.get(username="sam")
        data = StandupService(TaskRepository(), Scheduler(), ProjectAccess()).standup(sam, project.pk)
        self.assertGreater(data["timeline"]["event_count"], 5)
        self.assertTrue(any(b["stale"] for b in data["blockers"]))
        self.assertTrue(data["schedule_health"]["slipped"])
        self.assertTrue(data["schedule_health"]["downstream_moved"])
        call_command("seed_standup_demo", "--reset", stdout=StringIO())
        self.assertEqual(Project.objects.filter(name="Mobile App Launch (demo)").count(), 1)
