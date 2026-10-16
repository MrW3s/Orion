"""Unit tests for the engine. No database needed: the engine is pure Python."""
import unittest
from datetime import date

from scheduling import CycleError, Scheduler, TaskNode

START = date(2026, 10, 19)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()

    def test_independent_tasks_start_on_project_start(self):
        result = self.scheduler.compute(START, [TaskNode(1, 3), TaskNode(2, 1)])
        self.assertEqual(result.tasks[1].start, START)
        self.assertEqual(result.tasks[1].end, date(2026, 10, 21))
        self.assertEqual(result.tasks[2].start, START)

    def test_task_starts_after_latest_dependency(self):
        result = self.scheduler.compute(START, [
            TaskNode("design", 2),
            TaskNode("db", 5),
            TaskNode("api", 3, frozenset({"design", "db"})),
        ])
        self.assertEqual(result.tasks["api"].start, date(2026, 10, 24))  # day after db ends
        self.assertEqual(result.order[-1], "api")
        self.assertEqual(result.project_end, date(2026, 10, 26))

    def test_cycle_is_detected(self):
        with self.assertRaises(CycleError):
            self.scheduler.compute(START, [
                TaskNode("a", 1, frozenset({"b"})),
                TaskNode("b", 1, frozenset({"a"})),
            ])

    def test_unknown_dependency_rejected(self):
        with self.assertRaises(KeyError):
            self.scheduler.compute(START, [TaskNode("a", 1, frozenset({"ghost"}))])

    def test_task_waits_for_its_own_start_date(self):
        result = self.scheduler.compute(START, [TaskNode("copy", 3, earliest_start=date(2026, 10, 22))])
        self.assertEqual(result.tasks["copy"].start, date(2026, 10, 22))
        self.assertEqual(result.tasks["copy"].end, date(2026, 10, 24))

    def test_unfinished_dependency_moves_task_past_its_start_date(self):
        result = self.scheduler.compute(START, [
            TaskNode("design", 5),                                     # Oct 19-23
            TaskNode("build", 2, frozenset({"design"}), earliest_start=date(2026, 10, 20)),
        ])
        self.assertEqual(result.tasks["build"].start, date(2026, 10, 24))  # keeps its 2 days
        self.assertEqual(result.tasks["build"].end, date(2026, 10, 25))
