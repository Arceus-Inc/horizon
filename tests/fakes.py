"""In-memory fakes of horizon's ports + the LLM reasoner, for fast, network-free unit tests.

Each fake satisfies the corresponding ``dream.contracts`` Protocol (or the ``Reasoner`` port)
structurally, so an engine under test cannot tell it from the real chorus-backed adapter. Integration
tests use the real chorus bridge instead (see ``test_m1_seam.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any

from dream.api.substrate import CompletionResult
from dream.contracts import GoalNode, OutcomeEvent, Priority


class FakeGoalStore:
    """In-memory ``GoalStore``."""

    def __init__(self) -> None:
        self._nodes: dict[str, GoalNode] = {}

    def upsert(self, node: GoalNode) -> str:
        self._nodes[node.id] = node
        return node.id

    def get(self, goal_id: str) -> GoalNode | None:
        return self._nodes.get(goal_id)

    def children(self, parent_id: str | None) -> list[GoalNode]:
        return [n for n in self._nodes.values() if n.parent_id == parent_id]


class FakeIntakePort:
    """In-memory ``IntakePort`` — records submissions + priorities, idempotent on the fingerprint."""

    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.priorities: dict[str, str] = {}
        self._by_fingerprint: dict[str, str] = {}
        self._counter = 0

    def submit(
        self,
        intent: str,
        *,
        assignee: str | None = None,
        priority: Priority = "medium",
        depends_on: Sequence[str] = (),
        goal_id: str | None = None,
        origin_fingerprint: str | None = None,
    ) -> str:
        fingerprint = origin_fingerprint or "default"
        if fingerprint in self._by_fingerprint:
            return self._by_fingerprint[fingerprint]
        self._counter += 1
        task_id = f"task_{self._counter}"
        self._by_fingerprint[fingerprint] = task_id
        self.submitted.append(
            {
                "task_id": task_id,
                "intent": intent,
                "assignee": assignee,
                "priority": priority,
                "goal_id": goal_id,
                "fingerprint": fingerprint,
            }
        )
        self.priorities[task_id] = priority
        return task_id

    def set_priority(self, task_id: str, priority: Priority) -> None:
        self.priorities[task_id] = priority


class FakeOutcomeFeed:
    """In-memory ``OutcomeFeed`` — ``emit`` is a test helper that pushes to live subscribers + the log."""

    def __init__(self) -> None:
        self.log: list[OutcomeEvent] = []
        self._subscribers: list[Callable[[OutcomeEvent], None]] = []

    def subscribe(self, callback: Callable[[OutcomeEvent], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def replay(self, *, after: str | None = None) -> Iterator[OutcomeEvent]:
        return iter(list(self.log))

    def emit(self, event: OutcomeEvent) -> None:
        self.log.append(event)
        for callback in tuple(self._subscribers):
            callback(event)


class FakeSubstrate:
    """A ``Reasoner`` that returns a canned completion + records the prompts it was asked."""

    name = "fake"

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[str] = []

    def complete(self, prompt: str, params: dict[str, Any] | None = None) -> CompletionResult:
        self.calls.append(prompt)
        return CompletionResult(text=self._text)


class SequenceSubstrate:
    """A ``Reasoner`` that returns a scripted sequence of completions (the last one repeats)."""

    name = "sequence"

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls: list[str] = []

    def complete(self, prompt: str, params: dict[str, Any] | None = None) -> CompletionResult:
        self.calls.append(prompt)
        index = min(len(self.calls) - 1, len(self._texts) - 1)
        return CompletionResult(text=self._texts[index])
