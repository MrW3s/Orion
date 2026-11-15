"""python manage.py seed_standup_demo [--reset]

Creates a clearly labelled demo project, "Mobile App Launch (demo)", with a
team, ~17 tasks, dependencies, bugs, blockers and two weeks of activity, so
the standup page looks like a real sprint. Everything goes through TaskService
(so the engine schedules it and the activity log is written the normal way);
only the timestamps are then moved back in time to spread the story over the
last working days. It never touches other projects.

Run it again with --reset to delete the demo project and start over.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile, Role
from notifications.publisher import InMemoryPublisher
from projects.access import ProjectAccess
from projects.models import Project
from scheduling import Scheduler
from tasks.models import Task, TaskEvent
from tasks.repository import TaskRepository
from tasks.services import NewTask, TaskService
from tasks.standup import previous_working_day

PROJECT_NAME = "Mobile App Launch (demo)"
PASSWORD = "orion-demo"
TEAM = [("sam", Role.PROJECT_MANAGER), ("alice", Role.TEAM_MEMBER), ("bob", Role.TEAM_MEMBER),
        ("carol", Role.TEAM_MEMBER), ("dan", Role.TEAM_MEMBER)]


class Command(BaseCommand):
    help = "Create a demo project with realistic standup activity."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the demo project first.")

    def handle(self, *args, reset=False, **options):
        existing = Project.objects.filter(name=PROJECT_NAME)
        if existing.exists() and not reset:
            self.stdout.write(f"“{PROJECT_NAME}” already exists. Use --reset to rebuild it.")
            return
        with transaction.atomic():
            existing.delete()
            people, created = self._team()
            project = self._story(people)
        self.stdout.write(self.style.SUCCESS(f"Created “{PROJECT_NAME}” (id {project.pk})."))
        if created:
            self.stdout.write(f"New users {', '.join(created)} have the password “{PASSWORD}”.")
        self.stdout.write(f"Log in as sam (project manager) and open /projects/{project.pk}/standup/")

    # ---- Team ----------------------------------------------------------
    def _team(self):
        User = get_user_model()
        people, created = {}, []
        for username, role in TEAM:
            user, new = User.objects.get_or_create(username=username)
            if new:
                user.set_password(PASSWORD)
                user.save()
                Profile.objects.create(user=user, role=role)
                created.append(username)
            people[username] = user
        return people, created

    # ---- Time helpers ----------------------------------------------------
    # Day 0 is the first day of the default "since last standup" window (the
    # previous working day); day 1 is the working day before it, and so on.
    def _clock(self):
        self.now = timezone.localtime()
        self.last_day = previous_working_day(self.now.date())

    def at(self, days_ago: int, hour: int, minute: int = 0) -> datetime:
        day = self.last_day
        for _ in range(days_ago):
            day = previous_working_day(day)
        moment = timezone.make_aware(datetime.combine(day, time(hour, minute)))
        return moment

    def did(self, when, fn, *args, **kwargs):
        """Run a TaskService call, then date what it wrote at `when`."""
        before = set(TaskEvent.objects.values_list("pk", flat=True))
        result = fn(*args, **kwargs)
        new = TaskEvent.objects.exclude(pk__in=before)
        for task_id, kind in new.values_list("task_id", "kind"):
            if kind == "created":
                Task.objects.filter(pk=task_id).update(created_at=when)
            if kind == "blocked":
                Task.objects.filter(pk=task_id, blocked_since__isnull=False).update(blocked_since=when)
        new.update(created_at=when)
        return result

    # ---- The sprint ----------------------------------------------------
    def _story(self, p):
        self._clock()
        svc = TaskService(TaskRepository(), Scheduler(), ProjectAccess(), InMemoryPublisher())
        start = self.at(12, 9).date()
        start -= timedelta(days=start.weekday())  # the Monday of that week
        project = Project.objects.create(name=PROJECT_NAME, start_date=start)
        project.members.add(*p.values())

        def add(when, who, title, first_day, days, assignee=None, deps=(), kind="task"):
            new = NewTask(title, start_date=start + timedelta(days=first_day),
                          end_date=start + timedelta(days=first_day + days - 1),
                          assignee_id=p[assignee].pk if assignee else None,
                          depends_on_ids=[t.pk for t in deps], kind=kind)
            return self.did(when, svc.add_task, p[who], project.pk, new)

        def status(when, who, task, value):
            self.did(when, svc.update_status, p[who], task.pk, value)

        early = self.at(12, 10)
        research = add(early, "sam", "Research user needs", 0, 3, "carol")
        wires = add(early, "sam", "UX wireframes", 3, 4, "carol", [research])
        visual = add(early, "sam", "Visual design", 7, 4, "carol", [wires])
        auth = add(early, "sam", "API: auth endpoints", 3, 3, "bob")
        payments = add(early, "sam", "API: payments", 6, 5, "bob", [auth])
        shell = add(early, "sam", "App shell and navigation", 7, 3, "alice", [wires])
        login = add(early, "sam", "Login screen", 10, 2, "alice", [shell, auth])
        checkout = add(early, "sam", "Checkout screen", 13, 4, "alice", [visual, payments])
        push = add(early, "sam", "Push notifications", 10, 3, "dan", [shell])
        analytics = add(early, "sam", "Analytics events", 10, 2, "dan", [shell])
        qa_plan = add(early, "sam", "QA test plan", 12, 2, "dan")
        store = add(early, "sam", "App store listing", 14, 2, "carol", [visual])
        add(early, "sam", "Beta release", 18, 1, "sam", [login, checkout, push, qa_plan])
        add(early, "sam", "Receipt emails", 11, 2, "dan", [payments])  # off the critical path

        # Two weeks ago to last week: the early work gets done.
        status(self.at(11, 9), "carol", research, "in_progress")
        status(self.at(9, 16), "carol", research, "complete")
        status(self.at(9, 10), "bob", auth, "in_progress")
        status(self.at(7, 15), "bob", auth, "complete")
        status(self.at(8, 9), "carol", wires, "in_progress")
        status(self.at(5, 17), "carol", wires, "complete")
        status(self.at(6, 9), "bob", payments, "in_progress")
        status(self.at(5, 10), "carol", visual, "in_progress")
        status(self.at(4, 9), "alice", shell, "in_progress")
        # Payments has been stuck for days: highlighted as more than 2 working days.
        self.did(self.at(4, 14), svc.set_blocked, p["bob"], payments.pk,
                 "Waiting for Stripe production keys from finance")
        status(self.at(3, 11), "dan", push, "in_progress")
        status(self.at(3, 14), "dan", analytics, "in_progress")
        login_block = self.at(2, 15)
        self.did(login_block, svc.set_blocked, p["alice"], login.pk, "Needs the refresh-token endpoint")

        # The previous window (the working day before last).
        status(self.at(1, 9, 40), "dan", analytics, "complete")
        currency = add(self.at(1, 10, 15), "bob", "Bug: prices show the wrong currency", 12, 1, "bob",
                       kind="bug")
        status(self.at(1, 11), "bob", currency, "in_progress")
        status(self.at(1, 13, 30), "alice", shell, "complete")
        status(self.at(1, 14), "alice", login, "in_progress")
        self.did(self.at(1, 16), svc.set_blocked, p["dan"], push.pk,
                 "Apple developer account renewal is pending")
        status(self.at(1, 16, 30), "sam", qa_plan, "in_progress")

        # Since the last standup.
        status(self.at(0, 9, 5), "bob", currency, "complete")
        self.did(self.at(0, 9, 20), svc.unblock, p["bob"], login.pk)
        rotate = add(self.at(0, 9, 45), "alice", "Bug: crash when rotating the checkout screen", 13, 1,
                     "alice", kind="bug")
        token = add(self.at(0, 10, 10), "dan", "Bug: push token isn't saved after login", 13, 1, "dan",
                    kind="bug")
        self.did(self.at(0, 10, 30), svc.reassign, p["sam"], token.pk, p["bob"].pk)
        status(self.at(0, 10, 50), "bob", token, "in_progress")
        # A security review is added in front of payments: the critical path slips.
        review = add(self.at(0, 11, 5), "sam", "Security review of payment flow", 9, 3, "sam")
        self.did(self.at(0, 11, 15), svc.set_dependencies, p["sam"], payments.pk, [auth.pk, review.pk])
        status(self.at(0, 11, 30), "carol", visual, "complete")
        status(self.at(0, 11, 45), "carol", store, "in_progress")
        status(self.at(0, 12, 10), "alice", rotate, "in_progress")
        # The standup order the scrum master uses.
        from tasks.models import StandupOrder
        StandupOrder.objects.bulk_create([
            StandupOrder(project=project, user=p[name], position=i)
            for i, name in enumerate(["alice", "bob", "carol", "dan", "sam"])])
        return project
