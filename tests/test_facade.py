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


def test_passing_outcome_marks_goal_done_in_state(tmp_path):
    text = json.dumps({"goals": [{"title": "Build API", "score": 0.9}]})
    horizon, _, _, feed = _horizon(tmp_path, text)
    horizon.seed_decision(Decision(id="dec_1", statement="x", owner="moe"))
    horizon.decompose("dec_1")
    horizon.submit_decision("dec_1")
    horizon.start()

    goal = horizon.state()[0].goals[0]
    feed.emit(OutcomeEvent(kind="run.evaluated", task_id=goal.task_id, goal_id=goal.id, passed=True))

    assert horizon.state()[0].goals[0].status == "done"


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


def test_sweep_staleness_drifts_and_resurfaces_aged_goals(tmp_path):
    from datetime import UTC, datetime, timedelta

    from horizon.model._strategy import StrategyRecord

    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
    intake = FakeIntakePort()
    strategy = StrategyStore(tmp_path / "strategy.json")
    # a goal verified 2 days ago (on_track + done) with a live task -> should drift
    strategy.put(
        StrategyRecord(
            goal_id="g1", title="Old goal", score=0.30, health="on_track", done=True,
            task_id="task_1", last_outcome_at=(now - timedelta(days=2)).isoformat(),
        )
    )
    # a goal verified 5 minutes ago -> should NOT drift
    strategy.put(
        StrategyRecord(
            goal_id="g2", title="Fresh goal", score=0.30, health="on_track", done=True,
            task_id="task_2", last_outcome_at=(now - timedelta(minutes=5)).isoformat(),
        )
    )
    intake.priorities["task_1"] = "low"
    intake.priorities["task_2"] = "low"
    horizon = Horizon(
        goals=FakeGoalStore(),
        intake=intake,
        outcomes=FakeOutcomeFeed(),
        decisions=DecisionStore(tmp_path / "decisions.json"),
        strategy=strategy,
    )

    drifted = horizon.sweep_staleness(now=now)

    assert drifted == ["g1"]
    aged = strategy.get("g1")
    assert aged.health == "drifting"
    assert aged.done is False  # re-opened for re-verification
    assert aged.score == 0.45  # 0.30 + 0.15 stale_bump
    assert intake.priorities["task_1"] == "medium"  # 0.45 crosses the low->medium threshold
    assert strategy.get("g2").health == "on_track"  # fresh goal untouched
