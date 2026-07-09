"""Slice 1 (planning): the LLM Decomposer turns a Decision into validated Goals + strategy records."""

from __future__ import annotations

import json

import pytest

from horizon.errors import DecompositionError, UnknownDecision
from horizon.model import Decision
from horizon.planning import Decomposer
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeSubstrate, SequenceSubstrate


def _decomposer(tmp_path, text):
    decisions = DecisionStore(tmp_path / "decisions.json")
    strategy = StrategyStore(tmp_path / "strategy.json")
    goals = FakeGoalStore()
    reasoner = FakeSubstrate(text)
    decomposer = Decomposer(
        goals=goals, strategy=strategy, decisions=decisions, reasoner=reasoner
    )
    return decomposer, decisions, strategy, goals, reasoner


def test_decompose_writes_goals_records_and_links(tmp_path):
    text = json.dumps(
        {
            "goals": [
                {
                    "title": "Build the note-capture REST API",
                    "metric": "endpoints live",
                    "target": "3",
                    "rationale": "core capability",
                    "score": 0.9,
                },
                {
                    "title": "Design the mobile capture UI",
                    "metric": "screens shipped",
                    "target": "2",
                    "rationale": "user entry point",
                    "score": 0.6,
                },
            ]
        }
    )
    decomposer, decisions, strategy, goals, reasoner = _decomposer(tmp_path, text)
    decisions.put(
        Decision(
            id="dec_1",
            statement="Build an AI note-taker for working professionals",
            owner="moe",
        )
    )

    out = decomposer.decompose("dec_1")

    # returns the rich goals
    assert [g.title for g in out] == [
        "Build the note-capture REST API",
        "Design the mobile capture UI",
    ]
    assert all(g.decision_id == "dec_1" and g.owner == "moe" for g in out)

    # goals written to the chorus seam at level 'goal', roots (parent_id None)
    seam = {n.id: n for n in goals.children(None)}
    assert len(seam) == 2
    assert all(n.level == "goal" and n.owner == "moe" for n in seam.values())

    # strategy records carry score/metric/target + decision link
    records = {r.goal_id: r for r in strategy.all()}
    assert len(records) == 2
    top = next(r for r in records.values() if r.score == 0.9)
    assert top.metric == "endpoints live" and top.target == "3"
    assert all(r.decision_id == "dec_1" for r in records.values())

    # decision now links to exactly those goals
    assert set(decisions.get("dec_1").goal_ids) == {g.id for g in out}

    # the prompt actually carried the decision statement
    assert "AI note-taker for working professionals" in reasoner.calls[0]


def test_decompose_unknown_decision_raises(tmp_path):
    decomposer, *_ = _decomposer(tmp_path, "{}")
    with pytest.raises(UnknownDecision):
        decomposer.decompose("nope")


def test_decompose_clamps_score_and_skips_untitled(tmp_path):
    text = json.dumps(
        {
            "goals": [
                {"title": "Ship it", "score": 5},  # clamp to 1.0
                {"title": "   ", "score": 0.5},  # no title -> skipped
                {"metric": "x"},  # no title -> skipped
            ]
        }
    )
    decomposer, decisions, _, _, _ = _decomposer(tmp_path, text)
    decisions.put(Decision(id="dec_1", statement="do a thing"))

    out = decomposer.decompose("dec_1")
    assert [g.title for g in out] == ["Ship it"]
    assert out[0].score == 1.0


def test_decompose_rejects_empty_goal_list(tmp_path):
    decomposer, decisions, *_ = _decomposer(tmp_path, json.dumps({"goals": []}))
    decisions.put(Decision(id="dec_1", statement="do a thing"))
    with pytest.raises(DecompositionError):
        decomposer.decompose("dec_1")


def test_decompose_tolerates_fenced_json(tmp_path):
    inner = {"goals": [{"title": "Only goal", "score": 0.5}]}
    text = f"Here is the plan:\n```json\n{json.dumps(inner)}\n```\nDone."
    decomposer, decisions, _, _, _ = _decomposer(tmp_path, text)
    decisions.put(Decision(id="dec_1", statement="do a thing"))

    out = decomposer.decompose("dec_1")
    assert [g.title for g in out] == ["Only goal"]


def test_decompose_tolerates_top_level_array(tmp_path):
    text = json.dumps([{"title": "A", "score": 0.9}, {"title": "B", "score": 0.5}])
    decomposer, decisions, _, _, _ = _decomposer(tmp_path, text)
    decisions.put(Decision(id="dec_1", statement="x"))

    out = decomposer.decompose("dec_1")
    assert [g.title for g in out] == ["A", "B"]


def test_decompose_dedups_by_normalized_title(tmp_path):
    text = json.dumps(
        {"goals": [{"title": "Build API", "score": 0.9}, {"title": "build   api", "score": 0.4}]}
    )
    decomposer, decisions, _, _, _ = _decomposer(tmp_path, text)
    decisions.put(Decision(id="dec_1", statement="x"))

    out = decomposer.decompose("dec_1")
    assert [g.title for g in out] == ["Build API"]


def test_decompose_retries_once_then_succeeds(tmp_path):
    good = json.dumps({"goals": [{"title": "A", "score": 0.9}]})
    reasoner = SequenceSubstrate(["not json at all", good])
    decisions = DecisionStore(tmp_path / "decisions.json")
    decomposer = Decomposer(
        goals=FakeGoalStore(),
        strategy=StrategyStore(tmp_path / "strategy.json"),
        decisions=decisions,
        reasoner=reasoner,
    )
    decisions.put(Decision(id="dec_1", statement="x"))

    out = decomposer.decompose("dec_1")
    assert [g.title for g in out] == ["A"]
    assert len(reasoner.calls) == 2  # retried once
    assert "STRICT JSON ONLY" in reasoner.calls[1]


def test_decompose_retry_then_still_bad_raises(tmp_path):
    reasoner = SequenceSubstrate(["garbage", "still not json"])
    decisions = DecisionStore(tmp_path / "decisions.json")
    decomposer = Decomposer(
        goals=FakeGoalStore(),
        strategy=StrategyStore(tmp_path / "strategy.json"),
        decisions=decisions,
        reasoner=reasoner,
    )
    decisions.put(Decision(id="dec_1", statement="x"))

    with pytest.raises(DecompositionError):
        decomposer.decompose("dec_1")
    assert len(reasoner.calls) == 2


def test_decompose_requests_structured_output_by_default(tmp_path):
    reasoner = FakeSubstrate(json.dumps({"goals": [{"title": "A", "score": 0.9}]}))
    decisions = DecisionStore(tmp_path / "decisions.json")
    decomposer = Decomposer(
        goals=FakeGoalStore(),
        strategy=StrategyStore(tmp_path / "strategy.json"),
        decisions=decisions,
        reasoner=reasoner,
    )
    decisions.put(Decision(id="dec_1", statement="grow profit"))

    decomposer.decompose("dec_1")

    response_format = reasoner.params[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert "goals" in response_format["json_schema"]["schema"]["properties"]


def test_decompose_structured_false_omits_response_format(tmp_path):
    reasoner = FakeSubstrate(json.dumps({"goals": [{"title": "A", "score": 0.9}]}))
    decisions = DecisionStore(tmp_path / "decisions.json")
    decomposer = Decomposer(
        goals=FakeGoalStore(),
        strategy=StrategyStore(tmp_path / "strategy.json"),
        decisions=decisions,
        reasoner=reasoner,
        structured=False,
    )
    decisions.put(Decision(id="dec_1", statement="grow profit"))

    decomposer.decompose("dec_1")
    assert "response_format" not in reasoner.params[0]


def test_decompose_grounds_the_prompt_in_available_context(tmp_path):
    reasoner = FakeSubstrate(json.dumps({"goals": [{"title": "A", "score": 0.9}]}))
    decisions = DecisionStore(tmp_path / "decisions.json")
    decomposer = Decomposer(
        goals=FakeGoalStore(),
        strategy=StrategyStore(tmp_path / "strategy.json"),
        decisions=decisions,
        reasoner=reasoner,
        context="Only a warehouse.db with sales + costs tables. No CRM data.",
    )
    decisions.put(Decision(id="dec_1", statement="grow profit"))

    decomposer.decompose("dec_1")

    assert "AVAILABLE CONTEXT" in reasoner.calls[0]
    assert "No CRM data" in reasoner.calls[0]
