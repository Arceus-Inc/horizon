"""Theme D, slice D1: the CEO context assembler + read-only chat (ReAct, grounded, cited).

Offline + deterministic — a scripted substrate drives the reasoning steps, so these prove the loop:
tool dispatch, grounding (observations from the real read model), citations, the retry-on-bad-JSON
fallback, unknown-tool handling, and the step budget — without a live LLM.
"""

from __future__ import annotations

import json

from horizon import Horizon
from horizon.chat import CeoChat, ContextAssembler
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


def _populated_horizon(tmp_path):
    goals_json = json.dumps(
        {
            "goals": [
                {"title": "Build the note-capture API", "metric": "endpoints", "target": "5",
                 "rationale": "core capability", "score": 0.9},
                {"title": "Ship the mobile UI", "metric": "screens", "target": "3",
                 "rationale": "user-facing", "score": 0.5},
            ]
        }
    )
    horizon = Horizon(
        goals=FakeGoalStore(),
        intake=FakeIntakePort(),
        outcomes=FakeOutcomeFeed(),
        reasoner=FakeSubstrate(goals_json),
        decisions=DecisionStore(tmp_path / "d.json"),
        strategy=StrategyStore(tmp_path / "s.json"),
        proposals=ProposalStore(tmp_path / "p.json"),
        default_assignee="moe",
    )
    horizon.seed_decision(Decision(id="dec_1", statement="Build an AI note-taker", owner="moe"))
    horizon.decompose("dec_1")
    horizon.submit_decision("dec_1")
    return horizon


def _step(*, tool: str = "", args: dict | None = None, answer: str = "", cites: list | None = None):
    return json.dumps(
        {
            "thought": "…",
            "tool": tool,
            "args_json": json.dumps(args) if args else "",
            "answer_text": answer,
            "citations": cites or [],
        }
    )


# --- context assembler --------------------------------------------------------


def test_assembler_renders_decisions_goals_and_priority(tmp_path):
    ctx = ContextAssembler(_populated_horizon(tmp_path)).assemble()
    rendered = ctx.render()
    assert "Build an AI note-taker" in rendered
    assert "Build the note-capture API" in rendered
    assert "priority high" in rendered  # score 0.9 -> high
    assert "priority medium" in rendered  # score 0.5 -> medium
    assert not ctx.is_empty()


def test_assembler_is_empty_on_a_fresh_horizon(tmp_path):
    horizon = Horizon(
        goals=FakeGoalStore(), intake=FakeIntakePort(), outcomes=FakeOutcomeFeed(),
        decisions=DecisionStore(tmp_path / "d.json"), strategy=StrategyStore(tmp_path / "s.json"),
        proposals=ProposalStore(tmp_path / "p.json"),
    )
    assert ContextAssembler(horizon).assemble().is_empty()


# --- chat: the ReAct loop -----------------------------------------------------


def test_chat_calls_a_tool_then_answers_with_citations(tmp_path):
    horizon = _populated_horizon(tmp_path)
    reasoner = SequenceSubstrate(
        [
            _step(tool="query_direction"),
            _step(answer="We are building the note-capture API (high) and the mobile UI (medium).",
                  cites=["dec_1"]),
        ]
    )
    chat = CeoChat(reasoner=reasoner, horizon=horizon)
    ans = chat.ask("What are we working on?")

    assert "note-capture API" in ans.text
    assert ans.citations == ["dec_1"]
    assert len(ans.steps) == 1
    assert ans.steps[0].tool == "query_direction"
    assert "Build the note-capture API" in ans.steps[0].observation  # grounded in the real read model


def test_chat_can_answer_directly_without_tools(tmp_path):
    reasoner = SequenceSubstrate([_step(answer="Hello — ask me about the company.", cites=[])])
    chat = CeoChat(reasoner=reasoner, horizon=_populated_horizon(tmp_path))
    ans = chat.ask("hi")
    assert ans.text.startswith("Hello")
    assert ans.steps == []


def test_chat_inspect_goal_grounds_on_the_real_goal(tmp_path):
    horizon = _populated_horizon(tmp_path)
    goal_id = horizon.state()[0].goals[0].id  # a real minted goal id
    reasoner = SequenceSubstrate(
        [_step(tool="inspect_goal", args={"goal_id": goal_id}), _step(answer="done", cites=[goal_id])]
    )
    chat = CeoChat(reasoner=reasoner, horizon=horizon)
    ans = chat.ask("tell me about that goal")
    assert goal_id in ans.steps[0].observation
    assert "score" in ans.steps[0].observation.lower()


def test_chat_handles_an_unknown_tool_then_recovers(tmp_path):
    reasoner = SequenceSubstrate(
        [_step(tool="frobnicate"), _step(answer="Recovered.", cites=[])]
    )
    chat = CeoChat(reasoner=reasoner, horizon=_populated_horizon(tmp_path))
    ans = chat.ask("do a thing")
    assert "Unknown tool" in ans.steps[0].observation
    assert ans.text == "Recovered."


def test_chat_retries_on_unparseable_step(tmp_path):
    reasoner = SequenceSubstrate(["not json at all", _step(answer="ok", cites=[])])
    chat = CeoChat(reasoner=reasoner, horizon=_populated_horizon(tmp_path))
    ans = chat.ask("status?")
    assert ans.text == "ok"
    assert len(reasoner.calls) == 2  # first unparseable -> retried
    assert "response_format" not in reasoner.params[-1]  # retry dropped the schema


def test_chat_stops_at_the_step_budget(tmp_path):
    # a substrate that always calls a tool, never answers
    reasoner = SequenceSubstrate([_step(tool="query_direction")])
    chat = CeoChat(reasoner=reasoner, horizon=_populated_horizon(tmp_path), max_steps=3)
    ans = chat.ask("loop forever?")
    assert len(ans.steps) == 3
    assert "step budget" in ans.text
