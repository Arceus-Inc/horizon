"""The OutcomeListener — close the loop: landed DoD verdict -> health + re-score -> re-priority.

Subscribes to the ``OutcomeFeed`` and, for each ``outcome.landed`` event with a pass/fail verdict
for a goal horizon owns, folds it into the goal's ``StrategyRecord`` (via the health model) and
re-prioritises the goal's task. ``needs_recovery`` is set only when ``phase == needs_rework``.
Read-only w.r.t. chorus's schedule — horizon never dispatches; it only writes ``task.priority``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from horizon.feedback._fold import OutcomeFold
from horizon.feedback._health import HealthPolicy, apply_outcome
from horizon.intake._prioritiser import Prioritiser
from horizon.model._strategy import StrategyRecord
from horizon.ports import OutcomeEvent, OutcomeFeed
from horizon.store import StrategyStore

# Authoritative strategy verdict — outcome.landed only (RUN_EVALUATED / RUN_DONE stay off this feed).
_VERDICT_KINDS = frozenset({"outcome.landed"})
_TEAM_OUTCOME_KINDS = _VERDICT_KINDS | {"task.status", "recovery.escalated"}

# An observer called after each folded verdict with (event, record_before, record_after) — for reports.
Observer = Callable[[OutcomeEvent, StrategyRecord, StrategyRecord], None]


class OutcomeListener:
    """Subscribe outcomes; on a landed verdict, update goal health + score + done, then re-prioritise.

    Observable by construction — every event lands in exactly one counter so a report or test can prove
    the listener is really wired: ``handled`` (a verdict folded), ``dropped`` (a verdict for a goal
    horizon does not own), ``deferred`` (a verdict-kind event with no pass/fail yet, e.g. a mid-beat
    ``needs-changes``). Non-outcome kinds (``run.text`` / ``run.tool_*`` / ``run.done`` / …) are ignored
    silently — they are not verdicts.
    """

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
        self._fold = OutcomeFold()
        self._observer = observer
        self._unsubscribe: Callable[[], None] | None = None
        self.handled = 0  # verdicts folded into a goal horizon owns
        self.dropped = 0  # verdicts for a goal horizon does not own (unresolved goal_id)
        self.deferred = 0  # verdict-kind events without a pass/fail yet (needs-changes)

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
        if event.kind not in _TEAM_OUTCOME_KINDS:
            return  # not an outcome kind — ignored silently (run.text / run.tool_* / run.done / …)
        if event.goal_id is None:
            self.dropped += 1
            return
        record = self._strategy.get(event.goal_id)
        if record is None:
            self.dropped += 1  # a verdict for a goal horizon does not own
            return
        if record.delivery_shape == "team":
            self._on_team_event(record, event)
            return
        if event.kind not in _VERDICT_KINDS:
            return
        if event.passed is None:
            self.deferred += 1  # delegated / stranded / cancelled — not a solo pass/fail fold
            return
        before = replace(record)
        apply_outcome(record, passed=event.passed, policy=self._policy)
        if event.passed:
            record.done = True  # the DoD landed — in v1 (one task per goal) the goal's work is done
            record.needs_recovery = False
            record.last_diagnostic = ""
        else:
            # Locked: recovery only for needs_rework — terminal_fail downranks without recover()
            record.needs_recovery = event.phase == "needs_rework"
            record.last_diagnostic = event.detail or record.last_diagnostic
        self._strategy.put(record)
        self.handled += 1
        if record.task_id is not None:
            self._prioritiser.apply(record.task_id, record.score)
        if self._observer is not None:
            self._observer(event, before, record)

    def _on_team_event(self, record: StrategyRecord, event: OutcomeEvent) -> None:
        before = replace(
            record,
            task_ids=list(record.task_ids),
            task_outcomes=dict(record.task_outcomes),
        )
        if not self._fold.apply(record, event):
            if event.kind in _VERDICT_KINDS and event.passed is None:
                self.deferred += 1
            return
        aggregate_health = record.health
        aggregate_done = record.done
        apply_outcome(record, passed=event.passed is True, policy=self._policy)
        record.health = aggregate_health
        record.done = aggregate_done
        if event.is_root_outcome and event.passed is True:
            record.needs_recovery = False
            record.last_diagnostic = ""
        self._strategy.put(record)
        if event.kind in _VERDICT_KINDS and event.passed is not None:
            self.handled += 1
        if record.root_task_id is not None:
            self._prioritiser.apply(record.root_task_id, record.score)
        if self._observer is not None:
            self._observer(event, before, record)
