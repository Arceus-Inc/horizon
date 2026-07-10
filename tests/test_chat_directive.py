"""Theme D, slice D3: directive chat — gated write tools (prepare -> human confirm -> apply).

Deterministic — a scripted substrate drives the CEO to prepare write actions; the test confirms them and
asserts the REAL facade write happened. Proves the confirm-to-write invariant: preparing never mutates;
only confirm does.
"""

from __future__ import annotations

import json

from horizon import Horizon
from horizon.chat import CeoChat, CeoMemory
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
        {"goals": [
            {"title": "Build the API", "metric": "e", "target": "5", "rationale": "r", "score": 0.9},
            {"title": "Ship the UI", "metric": "s", "target": "3", "rationale": "r", "score": 0.5},
        ]}
    )
    horizon = Horizon(
        goals=FakeGoalStore(), intake=FakeIntakePort(), outcomes=FakeOutcomeFeed(),
        reasoner=FakeSubstrate(goals_json),
        decisions=DecisionStore(tmp_path / "d.json"), strategy=StrategyStore(tmp_path / "s.json"),
        proposals=ProposalStore(tmp_path / "p.json"), default_assignee="moe",
    )
    horizon.seed_decision(Decision(id="dec_1", statement="Build an AI note-taker", owner="moe"))
    horizon.decompose("dec_1")
    horizon.submit_decision("dec_1")
    return horizon


def _brief(rec):
    return DirectionBrief(candidate_id="c", recommendation=rec, rationale="ev", confidence=0.8,
                          candidate_goals=[CandidateGoal(title="g", metric="m", target="t", score=0.9)],
                          evidence_refs=["ev_1"])


def _step(*, tool="", args=None, answer="", cites=None):
    return json.dumps({"thought": "…", "tool": tool, "args_json": json.dumps(args) if args else "",
                       "answer_text": answer, "citations": cites or []})


def test_read_only_chat_has_no_write_tools(tmp_path):
    chat = CeoChat(reasoner=FakeSubstrate(_step(answer="hi")), horizon=_horizon(tmp_path))
    assert chat._write_tools == {}


def test_prepare_set_priority_does_not_apply_until_confirmed(tmp_path):
    horizon = _horizon(tmp_path)
    goal = next(g for g in horizon.state()[0].goals if g.title == "Ship the UI")  # score 0.5 -> medium
    reasoner = SequenceSubstrate([
        _step(tool="set_priority", args={"goal_id": goal.id, "priority": "high"}),
        _step(answer="I've prepared a priority bump to high — confirm to apply.", cites=[goal.id]),
    ])
    chat = CeoChat(reasoner=reasoner, horizon=horizon, directive=True)

    ans = chat.ask("make the UI goal top priority")

    assert len(ans.pending_actions) == 1
    action = ans.pending_actions[0]
    assert action.kind == "set_priority" and action.status == "pending"
    # NOT applied yet — priority unchanged
    assert horizon.goal_view(goal.id).score == 0.5

    result = chat.confirm(action, by="ceo")
    assert "high" in result
    assert action.status == "applied"
    assert horizon.goal_view(goal.id).score >= horizon._score_policy.high  # now really high


def test_approve_proposal_via_chat_seeds_a_live_decision(tmp_path):
    horizon = _horizon(tmp_path)
    pid = horizon.reconcile([_brief("Expand into the enterprise segment")])[0].id
    reasoner = SequenceSubstrate([
        _step(tool="approve_proposal", args={"proposal_id": pid}),
        _step(answer="Prepared the approval — confirm to make it live.", cites=[pid]),
    ])
    chat = CeoChat(reasoner=reasoner, horizon=horizon, directive=True)

    ans = chat.ask(f"approve proposal {pid}")
    action = ans.pending_actions[0]
    assert action.kind == "approve_proposal"
    before = len(horizon.state())
    decision_line = chat.confirm(action, by="ceo")
    assert "decision" in decision_line.lower()
    assert len(horizon.state()) == before + 1  # a new live decision exists


def test_record_directive_writes_to_memory_on_confirm(tmp_path):
    horizon = _horizon(tmp_path)
    mem = CeoMemory(tmp_path / "mem.json")
    reasoner = SequenceSubstrate([
        _step(tool="record_directive",
              args={"text": "Always prioritise the deliverable over analysis polish."}),
        _step(answer="Prepared the directive.", cites=[]),
    ])
    chat = CeoChat(reasoner=reasoner, horizon=horizon, memory=mem, directive=True)

    ans = chat.ask("remember: prioritise the deliverable over analysis polish")
    assert not mem.all(layer="directives")  # not yet written
    chat.confirm(ans.pending_actions[0], by="ceo")
    directives = mem.all(layer="directives")
    assert len(directives) == 1 and "deliverable" in directives[0].text


def test_draft_decision_seeds_on_confirm(tmp_path):
    horizon = _horizon(tmp_path)
    reasoner = SequenceSubstrate([
        _step(tool="draft_decision",
              args={"statement": "Launch a self-serve tier", "rationale": "widen the funnel"}),
        _step(answer="Prepared a new decision draft.", cites=[]),
    ])
    chat = CeoChat(reasoner=reasoner, horizon=horizon, directive=True)
    ans = chat.ask("let's launch a self-serve tier")
    before = len(horizon.state())
    chat.confirm(ans.pending_actions[0], by="ceo")
    assert len(horizon.state()) == before + 1
    assert any(st.decision.statement == "Launch a self-serve tier" for st in horizon.state())


def test_discard_leaves_the_company_unchanged(tmp_path):
    horizon = _horizon(tmp_path)
    goal = horizon.state()[0].goals[0]
    reasoner = SequenceSubstrate([
        _step(tool="archive_goal", args={"goal_id": goal.id}),
        _step(answer="Prepared an archive.", cites=[goal.id]),
    ])
    chat = CeoChat(reasoner=reasoner, horizon=horizon, directive=True)
    ans = chat.ask(f"archive {goal.id}")
    chat.discard(ans.pending_actions[0])
    assert ans.pending_actions[0].status == "discarded"
    assert horizon.goal_view(goal.id).status != "archived"  # untouched
