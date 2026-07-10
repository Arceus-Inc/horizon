"""Theme D, slice D5: standing directives / bounded autonomy + the Ceo wrapper.

Deterministic — proves the autonomy leash: a pre-approved, high-confidence approval auto-applies
(report-after) while a risky action stays pending; and the Ceo wrapper wires chat+beat+memory as one.
"""

from __future__ import annotations

import json

from horizon import Horizon
from horizon.chat import AutonomyPolicy, Ceo, CeoBeat, CeoChat
from horizon.chat._actions import PendingAction, permits
from horizon.generation import CandidateGoal, DirectionBrief, ProposalStore
from horizon.model import Decision
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import (
    FakeGoalStore,
    FakeIntakePort,
    FakeOutcomeFeed,
    FakeSubstrate,
    SequenceSubstrate,
)


def _horizon(tmp_path):
    goals_json = json.dumps(
        {"goals": [{"title": "Core", "metric": "e", "target": "5", "rationale": "r", "score": 0.9}]}
    )
    horizon = Horizon(
        goals=FakeGoalStore(), intake=FakeIntakePort(), outcomes=FakeOutcomeFeed(),
        reasoner=FakeSubstrate(goals_json),
        decisions=DecisionStore(tmp_path / "d.json"), strategy=StrategyStore(tmp_path / "s.json"),
        proposals=ProposalStore(tmp_path / "p.json"), default_assignee="moe",
    )
    horizon.seed_decision(Decision(id="dec_1", statement="Build", owner="moe"))
    horizon.decompose("dec_1")
    horizon.submit_decision("dec_1")
    return horizon


def _brief(rec, *, conf, refs):
    return DirectionBrief(candidate_id="c", recommendation=rec, rationale="ev", confidence=conf,
                          candidate_goals=[CandidateGoal(title="g", metric="m", target="t", score=0.9)],
                          evidence_refs=[f"ev_{i}" for i in range(refs)])


def _step(*, tool="", args=None, answer="", cites=None):
    return json.dumps({"thought": "…", "tool": tool, "args_json": json.dumps(args) if args else "",
                       "answer_text": answer, "citations": cites or []})


# --- the policy --------------------------------------------------------------


def test_permits_only_pre_approved_kinds(tmp_path):
    horizon = _horizon(tmp_path)
    policy = AutonomyPolicy(auto_kinds=frozenset({"set_priority"}))
    assert permits(policy, PendingAction(id="a", kind="set_priority", args={}, preview=""), horizon)
    assert not permits(policy, PendingAction(id="a", kind="archive_goal", args={}, preview=""), horizon)


def test_permits_approve_only_above_confidence_and_evidence(tmp_path):
    horizon = _horizon(tmp_path)
    strong = horizon.reconcile([_brief("Strong bet", conf=0.85, refs=3)])[0]
    weak = horizon.reconcile([_brief("Weak bet", conf=0.65, refs=3)])[0]
    thin = horizon.reconcile([_brief("Thin bet", conf=0.9, refs=1)])[0]
    policy = AutonomyPolicy(auto_kinds=frozenset({"approve_proposal"}), min_proposal_confidence=0.8, min_evidence=3)

    def act(pid):
        return PendingAction(id="a", kind="approve_proposal", args={"proposal_id": pid}, preview="")

    assert permits(policy, act(strong.id), horizon)
    assert not permits(policy, act(weak.id), horizon)  # confidence too low
    assert not permits(policy, act(thin.id), horizon)  # too little evidence


def test_permits_auto_reject_only_below_the_bar(tmp_path):
    horizon = _horizon(tmp_path)
    strong = horizon.reconcile([_brief("Strong bet", conf=0.85, refs=3)])[0]
    weak = horizon.reconcile([_brief("Weak bet", conf=0.5, refs=1)])[0]
    policy = AutonomyPolicy(auto_kinds=frozenset({"reject_proposal"}), min_proposal_confidence=0.8, min_evidence=3)

    def act(pid):
        return PendingAction(id="a", kind="reject_proposal", args={"proposal_id": pid}, preview="")

    assert permits(policy, act(weak.id), horizon)  # below the bar -> safe to auto-reject
    assert not permits(policy, act(strong.id), horizon)  # strong -> a human should decide


# --- the beat under autonomy -------------------------------------------------


def test_beat_auto_applies_permitted_and_leaves_risky_pending(tmp_path):
    horizon = _horizon(tmp_path)
    strong = horizon.reconcile([_brief("Auto-worthy bet", conf=0.9, refs=3)])[0]
    goal = horizon.state()[0].goals[0]
    reasoner = SequenceSubstrate([
        _step(tool="approve_proposal", args={"proposal_id": strong.id}),
        _step(tool="archive_goal", args={"goal_id": goal.id}),  # risky, not in auto_kinds
        _step(answer="Approved the strong proposal; flagged the core goal for your call.", cites=[]),
    ])
    chat = CeoChat(reasoner=reasoner, horizon=horizon, directive=True)
    policy = AutonomyPolicy(auto_kinds=frozenset({"approve_proposal"}))
    beat = CeoBeat(chat=chat, autonomy=policy)

    n_decisions_before = len(horizon.state())
    result = beat.run("do the sweep", label="sweep")

    approve = next(a for a in result.prepared_actions if a.kind == "approve_proposal")
    archive = next(a for a in result.prepared_actions if a.kind == "archive_goal")
    assert approve.id in result.auto_applied and approve.status == "applied"
    assert archive.id not in result.auto_applied and archive.status == "pending"
    assert len(horizon.state()) == n_decisions_before + 1  # the auto-approved proposal went live
    assert horizon.goal_view(goal.id).status != "archived"  # risky action still needs a human


# --- the Ceo wrapper ----------------------------------------------------------


def test_ceo_wrapper_chats_and_remembers(tmp_path):
    horizon = _horizon(tmp_path)
    ceo = Ceo(
        horizon=horizon,
        reasoner=SequenceSubstrate([_step(answer="We are building the core.", cites=["dec_1"])]),
        memory_path=tmp_path / "mem.json",
    )
    ans = ceo.ask("what are we building?")
    assert "core" in ans.text
    assert len(ceo.memory.all(layer="conversation")) == 1  # the exchange was remembered
