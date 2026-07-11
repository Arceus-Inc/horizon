"""``HorizonGovernance`` — horizon's end of the governance seam, proven over fakes (no LLM, no beats).

The mirror of chorus's ``tests/tools/test_governance.py`` (which pins the CEO's tools against a fake
port). Here the real Horizon facade *is* the port: an approved proposal has already authored a live
decision + goals, so ``read_direction`` folds that tree, and each write verb delegates to the facade and
mutates real state. Chorus's tool tests + this adapter test together prove the whole seam end-to-end:
CEO tool → dream ``GovernancePort`` → horizon facade → the direction changes.
"""

from __future__ import annotations

from dream.contracts import GovernancePort

from horizon import Horizon
from horizon.generation import CandidateGoal, DirectionBrief, ProposalStore
from horizon.governance import HorizonGovernance
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed


def _horizon(tmp_path):
    horizon = Horizon(
        goals=FakeGoalStore(),
        intake=FakeIntakePort(),
        outcomes=FakeOutcomeFeed(),
        reasoner=None,
        decisions=DecisionStore(tmp_path / "d.json"),
        strategy=StrategyStore(tmp_path / "s.json"),
        proposals=ProposalStore(tmp_path / "p.json"),
        default_assignee="moe",
    )
    return horizon


def _brief(recommendation: str, *, confidence: float = 0.9):
    return DirectionBrief(
        candidate_id="c1",
        recommendation=recommendation,
        rationale="the evidence points here",
        confidence=confidence,
        risks=["data may be stale"],
        candidate_goals=[
            CandidateGoal(
                title="Quantify the upside",
                metric="incremental profit",
                target="+10% QoQ",
                rationale="ground it in numbers",
                score=0.9,
            )
        ],
        evidence_refs=["ev_1"],
    )


def test_horizon_governance_satisfies_the_port(tmp_path) -> None:
    gov = HorizonGovernance(_horizon(tmp_path))
    # structural (runtime_checkable) — no nominal inheritance, exactly how the factory accepts it
    assert isinstance(gov, GovernancePort)


def test_read_direction_folds_the_live_tree_and_open_proposals(tmp_path) -> None:
    horizon = _horizon(tmp_path)
    dec_id = horizon.approve_proposal(horizon.reconcile([_brief("Grow in region A")])[0].id, by="ceo")
    open_p = horizon.reconcile([_brief("Expand to region B")])[0]

    view = HorizonGovernance(horizon).read_direction()

    live = next(d for d in view.decisions if d.decision_id == dec_id)
    assert live.goals  # the approved proposal authored real goals
    assert all(g.priority in {"high", "medium", "low"} for g in live.goals)
    proposal = next(p for p in view.proposals if p.proposal_id == open_p.id)
    assert proposal.confidence is not None and proposal.evidence >= 1


def test_write_verbs_delegate_to_the_facade_and_mutate_state(tmp_path) -> None:
    horizon = _horizon(tmp_path)
    horizon.approve_proposal(horizon.reconcile([_brief("Grow in region A")])[0].id, by="ceo")
    open_p = horizon.reconcile([_brief("Expand to region B")])[0]
    gov = HorizonGovernance(horizon)

    # approve the still-open proposal through the port — a new live decision appears
    new_dec = gov.approve_proposal(open_p.id, by="ceo")
    assert horizon.list_proposals(status="proposed") == []
    after = gov.read_direction()
    assert any(d.decision_id == new_dec for d in after.decisions)

    # reprioritise then archive a real goal through the port
    goal = next(d for d in after.decisions if d.goals).goals[0]
    assert gov.set_priority(goal.goal_id, "high") == "high"
    gov.archive_goal(goal.goal_id)
    archived = next(
        g
        for d in gov.read_direction().decisions
        for g in d.goals
        if g.goal_id == goal.goal_id
    )
    assert archived.status == "archived"


def test_reject_through_the_port_closes_the_proposal(tmp_path) -> None:
    horizon = _horizon(tmp_path)
    open_p = horizon.reconcile([_brief("Expand to region B")])[0]
    gov = HorizonGovernance(horizon)

    gov.reject_proposal(open_p.id, by="ceo", reason="too thin")

    assert gov.read_direction().proposals == ()
    assert horizon.list_proposals(status="rejected")[0].id == open_p.id
