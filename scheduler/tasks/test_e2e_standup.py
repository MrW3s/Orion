"""End-to-end test for the standup page (standup story, AC11): a real browser
logs in, opens the page, changes the window and clicks a tile.

Needs the dev-only Playwright package and its browser:
    pip install -r requirements-dev.txt && python -m playwright install chromium
Without them this test is skipped, so the rest of the suite still runs.
"""
import os
import unittest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone

from notifications.publisher import InMemoryPublisher
from projects.access import ProjectAccess
from projects.models import Project
from scheduling import Scheduler

from .repository import TaskRepository
from .services import NewTask, TaskService

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # dev dependency not installed
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "Playwright isn't installed (see requirements-dev.txt)")
class StandupEndToEnd(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        # Playwright's sync API runs an event loop in this thread; the ORM calls in
        # setUp are still synchronous, so Django's async-safety check doesn't apply.
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception as exc:  # browser not downloaded
            cls.playwright.stop()
            super().tearDownClass()
            raise unittest.SkipTest(f"No Playwright browser: run `python -m playwright install chromium` ({exc})")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)

    def setUp(self):
        User = get_user_model()
        self.alice = User.objects.create_user("alice", password="standup-pass-1")
        bob = User.objects.create_user("bob", password="standup-pass-1")
        today = timezone.localdate()
        self.project = Project.objects.create(name="Mobile app", start_date=today - timedelta(days=7))
        self.project.members.add(self.alice, bob)
        other = Project.objects.create(name="Website", start_date=today)
        other.members.add(self.alice)
        service = TaskService(TaskRepository(), Scheduler(), ProjectAccess(), InMemoryPublisher())

        def add(title):
            return service.add_task(self.alice, self.project.pk,
                                    NewTask(title, start_date=today, end_date=today + timedelta(days=1)))
        add("Build")
        add("Launch")
        design = add("Design")
        service.update_status(bob, design.pk, "complete")  # done today
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 900})

    def tearDown(self):
        self.page.close()

    def test_login_open_change_window_and_click_a_tile(self):
        page = self.page
        # Log in
        page.goto(f"{self.live_server_url}/login/")
        page.fill("input[name=username]", "alice")
        page.fill("input[name=password]", "standup-pass-1")
        page.click("main form button")
        # Open the standup page
        page.goto(f"{self.live_server_url}/projects/{self.project.pk}/standup/")
        expect(page.locator(".tile:not(.skeleton)")).to_have_count(6)
        expect(page.locator('section[data-section="tasks"] tbody tr')).to_have_count(3)
        expect(page.locator("#window-label")).to_contain_text("Since")
        # Change the window
        page.select_option("#window-select", "today")
        expect(page).to_have_url(f"{self.live_server_url}/projects/{self.project.pk}/standup/?window=today")
        expect(page.locator("#window-label")).to_have_text("Today")
        completed = page.locator('.tile[data-key="completed"]')
        expect(completed.locator(".count")).to_have_text("1")
        # Click a tile: the task list shows only those tasks
        completed.click()
        expect(completed).to_have_attribute("aria-pressed", "true")
        rows = page.locator('section[data-section="tasks"] tbody tr')
        expect(rows).to_have_count(1)
        expect(rows.first).to_contain_text("Design")
        # No horizontal scroll at 1280px
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 1280)
