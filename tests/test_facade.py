"""Slice 3 (facade): the Horizon facade composes the full loop over fakes."""

from __future__ import annotations

import json

import pytest

from horizon import Horizon
from horizon.errors import HorizonError
from horizon.model import Decision
from horizon.ports import OutcomeEvent
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed, FakeSubstrate


def _horizon(tmp_path, substrate_text):
    goals = FakeGoalStore()
    intake = FakeIntakePort()
    feed = FakeOutcomeFeed()
    horizon = Horizon(
        goals=goals,
        intake=intake,
        outcomes=feed,
        reasoner=FakeSubstrate(substrate_text),
        decisions=DecisionStore(tmp_path / "decisions.json"),
        strategy=StrategyStore(tmp_path / "strategy.json"),
        default_assignee="moe",
    )
    return horizon, goals, intake, feed


def test_full_loop_seed_decompose_submit_state(tmp_path):
    text = json.dumps(
        {"goals": [{"title": "Build API", "score": 0.9}, {"title": "Build UI", "score": 0.5}]}
    )
    horizon, _, intake, _ = _horizon(tmp_path, text)
    horizon.seed_decision(Decision(id="dec_1", statement="Build an AI note-taker", owner="moe"))

    made = horizon.decompose("dec_1")
    assert len(made) == 2

    task_ids = horizon.submit_decision("dec_1")
    assert len(task_ids) == 2
    assert len(intake.submitted) == 2

    states = horizon.state()
    assert len(states) == 1
    view = states[0]
    assert view.decision.id == "dec_1"
    assert {g.title for g in view.goals} == {"Build API", "Build UI"}
    assert all(g.task_id is not None and g.owner == "moe" for g in view.goals)

    priorities = {g.title: intake.priorities[g.task_id] for g in view.goals}
    assert priorities["Build API"] == "high"  # score 0.9
    assert priorities["Build UI"] == "medium"  # score 0.5


def test_submit_decision_is_idempotent(tmp_path):
    text = json.dumps({"goals": [{"title": "Build API", "score": 0.9}]})
    horizon, _, intake, _ = _horizon(tmp_path, text)
    horizon.seed_decision(Decision(id="dec_1", statement="x", owner="moe"))
    horizon.decompose("dec_1")

    first = horizon.submit_decision("dec_1")
    second = horizon.submit_decision("dec_1")
    assert first == second
    assert len(intake.submitted) == 1


def test_start_then_failed_outcome_updates_state_and_priority(tmp_path):
    text = json.dumps({"goals": [{"title": "Build API", "score": 0.9}]})
    horizon, _, intake, feed = _horizon(tmp_path, text)
    horizon.seed_decision(Decision(id="dec_1", statement="x", owner="moe"))
    horizon.decompose("dec_1")
    horizon.submit_decision("dec_1")
    horizon.start()

    goal = horizon.state()[0].goals[0]
    feed.emit(
        OutcomeEvent(kind="run.evaluated", task_id=goal.task_id, goal_id=goal.id, passed=False)
    )

    after = horizon.state()[0].goals[0]
    assert after.health == "blocked"
    assert after.score == 1.0  # 0.9 + 0.25 -> clamp
    assert intake.priorities[goal.task_id] == "high"


def test_decompose_without_reasoner_raises(tmp_path):
    horizon = Horizon(
        goals=FakeGoalStore(),
        intake=FakeIntakePort(),
        outcomes=FakeOutcomeFeed(),
        decisions=DecisionStore(tmp_path / "decisions.json"),
        strategy=StrategyStore(tmp_path / "strategy.json"),
    )
    horizon.seed_decision(Decision(id="dec_1", statement="x"))
    with pytest.raises(HorizonError):
        horizon.decompose("dec_1")
