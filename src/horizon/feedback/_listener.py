"""The OutcomeListener — close the loop: landed DoD verdict -> health + re-score -> re-priority.

Subscribes to the ``OutcomeFeed`` and, for each event that carries a DoD verdict (``run.evaluated`` with
``passed`` set) for a goal horizon owns, folds it into the goal's ``StrategyRecord`` (via the health
model) and re-prioritises the goal's task. Read-only w.r.t. chorus's schedule — horizon never dispatches;
it only writes ``task.priority`` through the port.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from horizon.feedback._health import HealthPolicy, apply_outcome
from horizon.intake._prioritiser import Prioritiser
from horizon.model._strategy import StrategyRecord
from horizon.ports import OutcomeEvent, OutcomeFeed
from horizon.store import StrategyStore

# The event kinds that carry a landed DoD verdict horizon reacts to (chorus RUN_EVALUATED).
_VERDICT_KINDS = frozenset({"run.evaluated"})

# An observer called after each folded verdict with (event, record_before, record_after) — for reports.
Observer = Callable[[OutcomeEvent, StrategyRecord, StrategyRecord], None]


class OutcomeListener:
    """Subscribe outcomes; on a landed verdict, update goal health + score, then re-prioritise."""

    def __init__(
        self,
        *,
        outcomes: OutcomeFeed,
        strategy: StrategyStore,
        prioritiser: Prioritiser,
        policy: HealthPolicy | None = None,
        observer: Observer | None = None,
    ) -> None:
        self._outcomes = outcomes
        self._strategy = strategy
        self._prioritiser = prioritiser
        self._policy = policy or HealthPolicy()
        self._observer = observer
        self._unsubscribe: Callable[[], None] | None = None
        self.handled = 0  # observability: verdicts folded in (useful for reports)

    def start(self) -> Callable[[], None]:
        """Begin listening; returns (and stores) the unsubscribe handle."""
        self._unsubscribe = self._outcomes.subscribe(self.on_event)
        return self._unsubscribe

    def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def on_event(self, event: OutcomeEvent) -> None:
        """Fold one outcome into the owning goal (public so it can be driven directly in tests)."""
        if event.kind not in _VERDICT_KINDS or event.passed is None or event.goal_id is None:
            return
        record = self._strategy.get(event.goal_id)
        if record is None:
            return  # not a goal horizon owns
        before = replace(record)
        apply_outcome(record, passed=event.passed, policy=self._policy)
        self._strategy.put(record)
        self.handled += 1
        if record.task_id is not None:
            self._prioritiser.apply(record.task_id, record.score)
        if self._observer is not None:
            self._observer(event, before, record)
