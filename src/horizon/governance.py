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

from horizon.errors import ProposalNotOpen
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
                    root_task_id=g.root_task_id,
                    task_ids=tuple(g.task_ids),
                    team_id=g.team_id,
                    lead_id=g.lead_id,
                    task_outcomes=dict(g.task_outcomes),
                    delivery_shape=g.delivery_shape,
                    staffing_requirements=g.staffing_requirements,
                    effective_score=g.effective_score,
                    effective_priority=g.effective_priority,
                    priority_reason=g.priority_reason,
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
        # The recently-decided proposals (approved / rejected). Without these, the CEO's own just-made
        # approve/reject actions would vanish from the next read (they leave the "proposed" set), and a
        # verifier re-reading the tree would wrongly conclude the work was never done.
        decided = tuple(
            GovProposal(
                proposal_id=p.id,
                statement=p.decision_statement,
                status=p.status,
                confidence=p.brief.confidence if p.brief is not None else None,
                evidence=len(p.brief.evidence_refs) if p.brief is not None else 0,
            )
            for p in self._horizon.list_proposals(status=None)
            if p.status != "proposed"
        )
        return GovernanceView(decisions=tuple(decisions), proposals=proposals, decided=decided)

    def approve_proposal(self, proposal_id: str, *, by: str) -> str:
        # Idempotent by design: a governance beat may re-attempt the same call across dream's
        # planner/generator/evaluator phases and sprints. Approving an already-approved proposal is a
        # no-op success (returns its id), not an error — otherwise the "already approved" refusal spirals
        # the CEO into re-reading/re-acting. A proposal in any OTHER non-open state (rejected) is a real
        # conflict and still raises.
        try:
            return self._horizon.approve_proposal(proposal_id, by=by)
        except ProposalNotOpen:
            if self._status_of(proposal_id) == "approved":
                return proposal_id
            raise

    def reject_proposal(self, proposal_id: str, *, by: str, reason: str = "") -> None:
        # Idempotent for the same reason as ``approve_proposal``: rejecting an already-rejected proposal
        # succeeds as a no-op; an already-approved one is a real conflict and still raises.
        try:
            self._horizon.reject_proposal(proposal_id, by=by, reason=reason)
        except ProposalNotOpen:
            if self._status_of(proposal_id) == "rejected":
                return
            raise

    def set_priority(self, goal_id: str, priority: str) -> str:
        return self._horizon.set_priority(goal_id, priority)

    def archive_goal(self, goal_id: str) -> None:
        self._horizon.archive_goal(goal_id)

    def _status_of(self, proposal_id: str) -> str | None:
        """The current status of one proposal (any state), or ``None`` if it does not exist."""
        for p in self._horizon.list_proposals(status=None):
            if p.id == proposal_id:
                return p.status
        return None


__all__ = ["HorizonGovernance"]
