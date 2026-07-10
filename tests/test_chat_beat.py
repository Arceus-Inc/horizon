"""Theme D, slice D4: the CEO as an employee — bounded executive beats (governance/decision review).

Deterministic — a scripted substrate drives the CEO through an audit: inspect the tree, prepare a
correction for a blocked goal, write a memo. Proves the beat packages findings + gated actions and logs
itself to the decision-log, and that confirming a prepared action really re-aims the company.
"""

from __future__ import annotations

import json

from horizon import Horizon
from horizon.chat import CeoBeat, CeoChat, CeoMemory
from horizon.generation import ProposalStore
from horizon.model import Decision
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import (
    FakeGoalStore,
    FakeIntakePort,
    FakeOutcomeFeed,
    FakeSubstrate,
    SequenceSubstrate,
)


def _horizon_with_a_blocked_goal(tmp_path):
    goals_json = json.dumps(
        {"goals": [
            {"title": "Ship the core API", "metric": "e", "target": "5", "rationale": "r", "score": 0.9},
            {"title": "Prove an impossible theorem", "metric": "x", "target": "y", "rationale": "r",
             "score": 0.8},
        ]}
    )
    horizon = Horizon(
        goals=FakeGoalStore(), intake=FakeIntakePort(), outcomes=FakeOutcomeFeed(),
        reasoner=FakeSubstrate(goals_json),
        decisions=DecisionStore(tmp_path / "d.json"), strategy=StrategyStore(tmp_path / "s.json"),
        proposals=ProposalStore(tmp_path / "p.json"), default_assignee="moe",
    )
    horizon.seed_decision(Decision(id="dec_1", statement="Build the product", owner="moe"))
    horizon.decompose("dec_1")
    horizon.submit_decision("dec_1")
    horizon.start()
    # make the second goal blocked (a landed failure)
    blocked = next(g for g in horizon.state()[0].goals if g.title.startswith("Prove"))
    horizon.note_outcome(blocked.id, passed=False, diagnostic="mathematically impossible")
    return horizon, blocked


def _step(*, tool="", args=None, answer="", cites=None):
    return json.dumps({"thought": "…", "tool": tool, "args_json": json.dumps(args) if args else "",
                       "answer_text": answer, "citations": cites or []})


def test_governance_audit_prepares_corrections_and_logs_itself(tmp_path):
    horizon, blocked = _horizon_with_a_blocked_goal(tmp_path)
    mem = CeoMemory(tmp_path / "mem.json")
    reasoner = SequenceSubstrate([
        _step(tool="query_direction"),
        _step(tool="archive_goal", args={"goal_id": blocked.id}),
        _step(answer="Audit: 1 blocked goal ('Prove an impossible theorem') is dead — prepared an "
                     "archive. The core API goal is healthy.", cites=[blocked.id]),
    ])
    chat = CeoChat(reasoner=reasoner, horizon=horizon, memory=mem, directive=True)
    beat = CeoBeat(chat=chat, memory=mem)

    result = beat.governance_audit()

    assert result.label == "governance-audit"
    assert "blocked" in result.findings.lower()
    assert len(result.prepared_actions) == 1
    assert result.prepared_actions[0].kind == "archive_goal"
    # the beat logged itself to the decision-log
    log = mem.all(layer="decision-log")
    assert any("governance-audit" in e.tags for e in log)

    # confirming the prepared action really archives the dead goal
    chat.confirm(result.prepared_actions[0], by="ceo")
    assert horizon.goal_view(blocked.id).status == "archived"


def test_governance_audit_grounds_on_the_real_tree(tmp_path):
    horizon, _blocked = _horizon_with_a_blocked_goal(tmp_path)
    reasoner = SequenceSubstrate([
        _step(tool="query_direction"),
        _step(answer="Reviewed the tree.", cites=[]),
    ])
    beat = CeoBeat(chat=CeoChat(reasoner=reasoner, horizon=horizon, directive=True))
    result = beat.governance_audit()
    obs = result.steps[0].observation
    assert "Prove an impossible theorem" in obs and "health blocked" in obs


def test_beat_without_actions_still_returns_a_memo(tmp_path):
    horizon, _ = _horizon_with_a_blocked_goal(tmp_path)
    reasoner = SequenceSubstrate([_step(answer="Everything looks fine.", cites=[])])
    beat = CeoBeat(chat=CeoChat(reasoner=reasoner, horizon=horizon, directive=True))
    result = beat.run("quick check", label="spot-check")
    assert result.label == "spot-check"
    assert result.findings == "Everything looks fine."
    assert result.prepared_actions == []
