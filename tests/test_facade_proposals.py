"""C-gate wired into the facade: reconcile a brief -> approve -> a REAL live decision + goals + tasks.

Deterministic (no LLM, no beats): promotion uses the analyst's own ``candidate_goals`` directly, so an
approved proposal becomes real goals + submitted tasks through horizon's existing intake — proving the
whole tail of the funnel end-to-end over fakes.
"""

from __future__ import annotations

import json

import pytest

from horizon import Horizon
from horizon.errors import HorizonError, ProposalNotOpen
from horizon.generation import CandidateGoal, DirectionBrief, ProposalStore, SeedSource
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed, SequenceSubstrate


def _horizon(tmp_path, *, reasoner=None):
    goals = FakeGoalStore()
    intake = FakeIntakePort()
    feed = FakeOutcomeFeed()
    horizon = Horizon(
        goals=goals,
        intake=intake,
        outcomes=feed,
        reasoner=reasoner,
        decisions=DecisionStore(tmp_path / "d.json"),
        strategy=StrategyStore(tmp_path / "s.json"),
        proposals=ProposalStore(tmp_path / "p.json"),
        default_assignee="moe",
    )
    return horizon, goals, intake


def _brief(recommendation: str = "Concentrate investment in region A", *, confidence: float = 0.9):
    return DirectionBrief(
        candidate_id="c1",
        recommendation=recommendation,
        rationale="the evidence points here",
        confidence=confidence,
        risks=["data may be stale"],
        candidate_goals=[
            CandidateGoal(
                title="Quantify region A upside",
                metric="incremental profit",
                target="+10% QoQ",
                rationale="ground it in numbers",
                score=0.9,
            ),
            CandidateGoal(
                title="Validate with a pilot",
                metric="pilot signups",
                target="100",
                rationale="de-risk before scaling",
                score=0.5,
            ),
        ],
        evidence_refs=["ev_1"],
    )


def test_reconcile_then_approve_creates_a_real_live_decision(tmp_path):
    horizon, _, intake = _horizon(tmp_path)

    created = horizon.reconcile([_brief()])
    assert len(created) == 1
    assert horizon.state() == []  # proposal-only: nothing live yet

    decision_id = horizon.approve_proposal(created[0].id, by="ceo")

    states = horizon.state()
    assert len(states) == 1
    view = states[0]
    assert view.decision.id == decision_id
    assert view.decision.status == "active"
    assert view.decision.statement == "Concentrate investment in region A"
    assert {g.title for g in view.goals} == {"Quantify region A upside", "Validate with a pilot"}

    # goals really carry the analyst's metric/target, and tasks were submitted with score-derived priority
    q = next(g for g in view.goals if g.title == "Quantify region A upside")
    assert q.metric == "incremental profit"
    assert q.target == "+10% QoQ"
    assert all(g.task_id is not None and g.owner == "moe" for g in view.goals)
    assert len(intake.submitted) == 2
    assert intake.priorities[q.task_id] == "high"  # score 0.9 -> high

    # the proposal is now approved + linked to the live decision
    p = horizon.list_proposals(status=None)[0]
    assert p.status == "approved"
    assert p.decided_by == "ceo"
    assert p.linked_decision_id == decision_id


def test_approve_falls_back_to_brief_confidence_when_a_goal_has_no_score(tmp_path):
    horizon, _, intake = _horizon(tmp_path)
    brief = DirectionBrief(
        candidate_id="c1",
        recommendation="Move upmarket",
        rationale="r",
        confidence=0.8,
        candidate_goals=[CandidateGoal(title="Size the segment", metric="TAM", target="$1M")],
        evidence_refs=["ev"],
    )
    created = horizon.reconcile([brief])
    horizon.approve_proposal(created[0].id, by="ceo")
    g = horizon.state()[0].goals[0]
    assert intake.priorities[g.task_id] == "high"  # brief.confidence 0.8 -> high


def test_reconcile_skips_a_statement_already_live(tmp_path):
    horizon, _, _ = _horizon(tmp_path)
    horizon.approve_proposal(horizon.reconcile([_brief("Grow in EU")])[0].id, by="ceo")
    again = horizon.reconcile([_brief("  grow   in EU ")])  # normalized-equal to the live decision
    assert again == []


def test_double_approve_is_blocked(tmp_path):
    horizon, _, _ = _horizon(tmp_path)
    pid = horizon.reconcile([_brief()])[0].id
    horizon.approve_proposal(pid, by="ceo")
    with pytest.raises(ProposalNotOpen):
        horizon.approve_proposal(pid, by="ceo")


def test_explain_and_reject_never_promote(tmp_path):
    horizon, _, intake = _horizon(tmp_path)
    pid = horizon.reconcile([_brief()])[0].id

    text = horizon.explain_proposal(pid)
    assert "Concentrate investment in region A" in text
    assert "Quantify region A upside" in text

    horizon.reject_proposal(pid, by="ceo", reason="not this sprint")
    rejected = horizon.list_proposals(status="rejected")
    assert rejected[0].note == "not this sprint"
    assert intake.submitted == []  # never promoted
    assert horizon.state() == []


def test_generate_runs_the_whole_funnel_head_to_tail(tmp_path):
    # scout call returns one candidate; analyst call returns one gate-clearing brief
    scout_reply = json.dumps(
        {
            "candidates": [
                {
                    "title": "Concentrate on region A",
                    "thesis": "A is outperforming",
                    "evidence_ids": ["__EV__"],
                    "confidence": 0.85,
                }
            ]
        }
    )
    analyst_reply = json.dumps(
        {
            "recommendation": "Shift next-quarter investment to region A",
            "rationale": "A has the best margins",
            "confidence": 0.8,
            "risks": ["data may be stale"],
            "candidate_goals": [
                {"title": "Quantify A upside", "metric": "profit", "target": "+10%", "rationale": "r", "score": 0.9}
            ],
            "evidence_refs": ["__EV__"],
        }
    )
    seed = SeedSource(now=lambda: "2026-07-10T00:00:00+00:00")
    packet = seed.add("Region A margins are climbing", provenance="cofounder")
    # pin the scripted evidence ids to the real packet id the seed minted
    reasoner = SequenceSubstrate(
        [scout_reply.replace("__EV__", packet.id), analyst_reply.replace("__EV__", packet.id)]
    )
    horizon, _, intake = _horizon(tmp_path, reasoner=reasoner)

    proposals = horizon.generate([seed])

    assert len(proposals) == 1
    assert proposals[0].decision_statement == "Shift next-quarter investment to region A"
    assert horizon.state() == []  # still proposal-only

    decision_id = horizon.approve_proposal(proposals[0].id, by="ceo")
    view = horizon.state()[0]
    assert view.decision.id == decision_id
    assert {g.title for g in view.goals} == {"Quantify A upside"}
    assert len(intake.submitted) == 1  # a real task was submitted


def test_generate_without_a_reasoner_raises(tmp_path):
    horizon, _, _ = _horizon(tmp_path)  # no reasoner
    seed = SeedSource()
    seed.add("some signal")
    with pytest.raises(HorizonError):
        horizon.generate([seed])
