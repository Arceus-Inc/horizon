"""The Submitter — push a leaf **Goal** into chorus as exactly one idempotent task.

Turns a goal into an ``IntakePort.submit`` at a score-derived priority, linked by ``goal_id`` and
fingerprinted so re-submitting the same goal is a no-op. Records the resulting ``task_id`` on the goal's
``StrategyRecord`` so the feedback loop can find (and re-prioritise) the task later. Assignee resolution:
``Goal.owner`` if set, else the Submitter's ``default_assignee`` (the one employee in v1).
"""

from __future__ import annotations

from horizon.intake._fingerprint import fingerprint
from horizon.intake._prioritiser import ScorePolicy
from horizon.model import Goal
from horizon.model._strategy import StrategyRecord
from horizon.ports import IntakePort
from horizon.store import StrategyStore


class Submitter:
    """Leaf goal -> one idempotent, prioritised, linked chorus task."""

    def __init__(
        self,
        *,
        intake: IntakePort,
        strategy: StrategyStore,
        default_assignee: str | None = None,
        policy: ScorePolicy | None = None,
    ) -> None:
        self._intake = intake
        self._strategy = strategy
        self._default_assignee = default_assignee
        self._policy = policy or ScorePolicy()

    def submit(self, goal: Goal) -> str:
        """Submit ``goal`` (idempotent); return the task id realizing it."""
        record = self._strategy.get(goal.id) or StrategyRecord(
            goal_id=goal.id,
            title=goal.title,
            score=goal.score,
            metric=goal.metric,
            target=goal.target,
            decision_id=goal.decision_id,
        )
        if record.task_id is not None:
            return record.task_id  # already submitted — do not open a second task

        assignee = goal.owner or self._default_assignee
        priority = self._policy.priority_for(record.score)
        task_id = self._intake.submit(
            goal.title,
            assignee=assignee,
            priority=priority,
            goal_id=goal.id,
            origin_fingerprint=fingerprint(goal.id, goal.title),
        )
        record.task_id = task_id
        self._strategy.put(record)
        return task_id
