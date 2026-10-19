"""Unit tests for the engine. No database needed: the engine is pure Python."""
import unittest
from datetime import date

from scheduling import CycleError, Scheduler, TaskNode
from scheduling.critical_path import analyse

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

    def test_cycle_error_names_only_the_loop(self):
        # c depends on the loop but isn't part of it, so it isn't reported
        with self.assertRaises(CycleError) as ctx:
            self.scheduler.compute(START, [
                TaskNode("a", 1, frozenset({"b"})),
                TaskNode("b", 1, frozenset({"a"})),
                TaskNode("c", 1, frozenset({"a"})),
            ])
        self.assertEqual(ctx.exception.nodes, ["a", "b"])
        self.assertIn("a -> b -> a", str(ctx.exception))

    def test_task_depending_on_itself_is_a_cycle(self):
        with self.assertRaises(CycleError) as ctx:
            self.scheduler.compute(START, [TaskNode("a", 1, frozenset({"a"}))])
        self.assertEqual(ctx.exception.nodes, ["a"])

    def test_compute_returns_slack_and_critical_path(self):
        result = self.scheduler.compute(START, [
            TaskNode("design", 2),
            TaskNode("db", 5),
            TaskNode("api", 3, frozenset({"design", "db"})),
        ])
        self.assertEqual(result.critical_path, ["db", "api"])
        self.assertEqual(result.tasks["design"].slack_days, 3)
        self.assertFalse(result.tasks["design"].is_critical)
        self.assertTrue(result.tasks["api"].is_critical)

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


class CriticalPathTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()

    def run_analysis(self, tasks):
        """Run the forward pass, then the backward pass, and return analyse()'s result."""
        tasks_by_id = {t.id: t for t in tasks}
        result = self.scheduler.compute(START, tasks)
        graph = Scheduler._build_graph(tasks_by_id)
        return analyse(graph, result.order, tasks_by_id, result.tasks, result.project_end)

    def test_shorter_branch_has_slack(self):
        result = self.run_analysis([
            TaskNode("design", 2),                               # Oct 19-20
            TaskNode("db", 5),                                   # Oct 19-23
            TaskNode("api", 3, frozenset({"design", "db"})),     # Oct 24-26
        ])
        self.assertEqual(result, {
            "design": (3, False),  # can slip 3 days before it holds up api
            "db": (0, True),
            "api": (0, True),
        })

    def test_every_task_in_a_chain_is_critical(self):
        result = self.run_analysis([
            TaskNode("a", 2),
            TaskNode("b", 3, frozenset({"a"})),
            TaskNode("c", 1, frozenset({"b"})),
        ])
        self.assertEqual(result, {"a": (0, True), "b": (0, True), "c": (0, True)})

    def test_equal_parallel_branches_are_both_critical(self):
        result = self.run_analysis([
            TaskNode("a", 2),
            TaskNode("b", 1, frozenset({"a"})),
            TaskNode("c", 2),
            TaskNode("d", 1, frozenset({"c"})),
        ])
        # Both branches take 3 days, so neither can slip
        self.assertEqual(result, {"a": (0, True), "b": (0, True), "c": (0, True), "d": (0, True)})

    def test_late_planned_start_gives_other_tasks_slack(self):
        result = self.run_analysis([
            TaskNode("a", 2),                                    # Oct 19-20
            TaskNode("c", 1, frozenset({"a"})),                  # Oct 21
            TaskNode("b", 1, earliest_start=date(2026, 10, 25)), # can't start before Oct 25
        ])
        # b sets the project end (Oct 25), so a -> c has until then:
        # c could start as late as Oct 25 and a as late as Oct 23, 4 days each.
        self.assertEqual(result, {"a": (4, False), "c": (4, False), "b": (0, True)})

