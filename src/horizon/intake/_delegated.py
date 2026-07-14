"""Submit team-shaped goals through Dream's delegated-intake contract."""

from __future__ import annotations

from horizon.intake._fingerprint import fingerprint
from horizon.intake._prioritiser import ScorePolicy
from horizon.model import Goal
from horizon.model._strategy import StrategyRecord
from horizon.ports import (
    DelegatedIntakePort,
    DelegatedWorkRef,
    DelegatedWorkRequest,
    StaffingBlocked,
)
from horizon.store import StrategyStore


class DelegatedSubmitter:
    """Team goal -> one idempotent, policy-staffed Chorus delegation root."""

    def __init__(
        self,
        *,
        intake: DelegatedIntakePort,
        strategy: StrategyStore,
        policy: ScorePolicy | None = None,
    ) -> None:
        self._intake = intake
        self._strategy = strategy
        self._policy = policy or ScorePolicy()

    def submit(self, goal: Goal) -> DelegatedWorkRef | StaffingBlocked:
        """Submit one team-shaped goal without naming an employee or task topology."""
        record = self._strategy.get(goal.id) or StrategyRecord(
            goal_id=goal.id,
            title=goal.title,
            score=goal.score,
            metric=goal.metric,
            target=goal.target,
            decision_id=goal.decision_id,
            delivery_shape=goal.delivery_shape,
            staffing_requirements=goal.staffing_requirements,
        )
        if record.root_task_id is not None:
            if record.team_id is None or record.lead_id is None:
                raise ValueError("delegated strategy record is missing Team or lead identity")
            return DelegatedWorkRef(
                root_task_id=record.root_task_id,
                team_id=record.team_id,
                lead_id=record.lead_id,
            )
        if record.delivery_shape != "team":
            raise ValueError("DelegatedSubmitter requires delivery_shape='team'")

        result = self._intake.submit_delegated(
            DelegatedWorkRequest(
                intent=goal.title,
                goal_id=goal.id,
                priority=self._policy.priority_for(record.score),
                requirements=record.staffing_requirements,
                lead_professions=record.lead_professions,
                origin_fingerprint=fingerprint(goal.id, goal.title),
            )
        )
        if isinstance(result, StaffingBlocked):
            return result

        record.root_task_id = result.root_task_id
        record.task_id = result.root_task_id
        record.task_ids = list(dict.fromkeys([*record.task_ids, result.root_task_id]))
        record.team_id = result.team_id
        record.lead_id = result.lead_id
        record.attempts += 1
        self._strategy.put(record)
        return result


__all__ = ["DelegatedSubmitter"]