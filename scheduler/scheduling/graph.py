"""Dependency graph of tasks.

This module is pure Python: it imports nothing from Django or from any other
app. It only knows about task ids and the edges between them, which keeps it
loosely (data-)coupled to the rest of the system and easy to unit test.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Hashable, Iterable

NodeId = Hashable


class CycleError(ValueError):
    """Raised when the dependencies form a loop (A needs B, B needs A)."""

    def __init__(self, nodes: Iterable[NodeId]):
        self.nodes = list(nodes)
        super().__init__(f"Dependency cycle detected among: {self.nodes}")


class DependencyGraph:
    """Directed graph where an edge u -> v means 'v depends on u'."""

    def __init__(self) -> None:
        self._successors: dict[NodeId, set[NodeId]] = defaultdict(set)
        self._predecessors: dict[NodeId, set[NodeId]] = defaultdict(set)
        self._nodes: set[NodeId] = set()

    def add_node(self, node: NodeId) -> None:
        self._nodes.add(node)

    def add_dependency(self, node: NodeId, depends_on: NodeId) -> None:
        self._nodes.update((node, depends_on))
        self._successors[depends_on].add(node)
        self._predecessors[node].add(depends_on)

    def predecessors(self, node: NodeId) -> set[NodeId]:
        return set(self._predecessors.get(node, ()))

    def topological_order(self) -> list[NodeId]:
        """Kahn's algorithm. Raises CycleError if the graph is not a DAG."""
        in_degree = {n: len(self._predecessors.get(n, ())) for n in self._nodes}
        # sorted() makes the order deterministic when ids are comparable
        queue = deque(sorted((n for n, d in in_degree.items() if d == 0), key=str))
        order: list[NodeId] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for succ in sorted(self._successors.get(node, ()), key=str):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(order) != len(self._nodes):
            raise CycleError(n for n, d in in_degree.items() if d > 0)
        return order
