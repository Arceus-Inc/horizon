"""``HorizonGovernance`` — horizon's adapter satisfying dream's :class:`GovernancePort`.

This is the composition seam's horizon end. Chorus's CEO employee carries governance *tools* that bind to
an abstract :class:`~dream.contracts.GovernancePort`; horizon supplies the concrete port here by wrapping
its own facade. Chorus never imports horizon and horizon never imports chorus — they meet only at
``dream.contracts``. ``read_direction`` folds horizon's read model (the Decision → Goal tree) and the
funnel's proposal queue into the neutral :class:`~dream.contracts.GovernanceView`; the write verbs
delegate straight through to the facade's existing CEO levers (approve / reject / reprioritise / archive).
"""

from __future__ import annotations

from dream.contracts import (
    GovDecision,
    GovernanceView,
    GovGoal,
    GovProposal,
)

from horizon.facade import Horizon
from horizon.intake import ScorePolicy


class HorizonGovernance:
    """A :class:`~dream.contracts.GovernancePort` backed by the live Horizon facade.

    Structurally implements the Port (``@runtime_checkable`` — no nominal inheritance needed); the
    composition root hands an instance to the chorus harness factory as ``governance=…``.
    """

    def __init__(self, horizon: Horizon, *, score_policy: ScorePolicy | None = None) -> None:
        self._horizon = horizon
        self._score_policy = score_policy or ScorePolicy()

    def read_direction(self) -> GovernanceView:
        decisions: list[GovDecision] = []
        for st in self._horizon.state():
            goals = tuple(
                GovGoal(
                    goal_id=g.id,
                    title=g.title,
                    score=g.score,
                    priority=self._score_policy.priority_for(g.score),
                    health=g.health,
                    status=g.status,
                    task_id=g.task_id,
                    metric=g.metric,
                    target=g.target,
                )
                for g in sorted(st.goals, key=lambda g: g.score, reverse=True)
            )
            decisions.append(
                GovDecision(
                    decision_id=st.decision.id,
                    statement=st.decision.statement,
                    status=st.decision.status,
                    goals=goals,
                )
            )
        proposals = tuple(
            GovProposal(
                proposal_id=p.id,
                statement=p.decision_statement,
                status=p.status,
                confidence=p.brief.confidence if p.brief is not None else None,
                evidence=len(p.brief.evidence_refs) if p.brief is not None else 0,
            )
            for p in self._horizon.list_proposals(status="proposed")
        )
        return GovernanceView(decisions=tuple(decisions), proposals=proposals)

    def approve_proposal(self, proposal_id: str, *, by: str) -> str:
        return self._horizon.approve_proposal(proposal_id, by=by)

    def reject_proposal(self, proposal_id: str, *, by: str, reason: str = "") -> None:
        self._horizon.reject_proposal(proposal_id, by=by, reason=reason)

    def set_priority(self, goal_id: str, priority: str) -> str:
        return self._horizon.set_priority(goal_id, priority)

    def archive_goal(self, goal_id: str) -> None:
        self._horizon.archive_goal(goal_id)


__all__ = ["HorizonGovernance"]
