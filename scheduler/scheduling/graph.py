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
    """Raised when the dependencies form a loop (A needs B, B needs A).

    `nodes` is the loop itself, in order: each one depends on the next, and
    the last depends on the first. Tasks that merely sit downstream of the
    loop are left out, so the user sees exactly which dependency to remove.
    """

    def __init__(self, nodes: Iterable[NodeId]):
        self.nodes = list(nodes)
        loop = " -> ".join(map(str, self.nodes + self.nodes[:1]))
        super().__init__(f"Dependency cycle detected: {loop}")


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

    def successors(self, node: NodeId) -> set[NodeId]:
        return set(self._successors.get(node, ()))

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
            raise CycleError(self._find_cycle(self._nodes - set(order)))
        return order

    def _find_cycle(self, stuck: set[NodeId]) -> list[NodeId]:
        """Return one loop among the nodes Kahn's algorithm couldn't order.

        Every stuck node still waits on at least one stuck predecessor (that's
        why it got stuck), so following predecessors from any of them must
        eventually revisit a node. The path from that node onwards is a loop.
        """
        path: list[NodeId] = []
        position: dict[NodeId, int] = {}
        node = min(stuck, key=str)
        while node not in position:
            position[node] = len(path)
            path.append(node)
            node = min((p for p in self._predecessors[node] if p in stuck), key=str)
        return path[position[node]:]
