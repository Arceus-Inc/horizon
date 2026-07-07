"""The LoopReporter renders decomposition/intake/feedback insights; the offline loop is correct."""

from __future__ import annotations

import json

from horizon import Horizon, LoopReporter, render_direction
from horizon.model import Decision
from horizon.ports import OutcomeEvent
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed, FakeSubstrate


def _loop(tmp_path):
    text = json.dumps(
        {
            "goals": [
                {"title": "Build API", "score": 0.9, "metric": "endpoints", "target": "3"},
                {"title": "Build UI", "score": 0.6},
            ]
        }
    )
    intake = FakeIntakePort()
    feed = FakeOutcomeFeed()
    reporter = LoopReporter(title="Test loop")
    horizon = Horizon(
        goals=FakeGoalStore(),
        intake=intake,
        outcomes=feed,
        reasoner=FakeSubstrate(text),
        decisions=DecisionStore(tmp_path / "decisions.json"),
        strategy=StrategyStore(tmp_path / "strategy.json"),
        default_assignee="moe",
        outcome_observer=reporter.observe,
    )
    decision = Decision(id="dec_1", statement="Build a thing", owner="moe")
    horizon.seed_decision(decision)
    made = horizon.decompose("dec_1")
    reporter.record_decomposition(decision, made)
    horizon.start()
    for goal in made:
        task_id = horizon.submit_goal(goal)
        reporter.record_submission(goal, task_id, assignee=goal.owner)
    return horizon, feed, reporter, made


def _emit(horizon, feed, goal_id, passed):
    goal = horizon.goal_view(goal_id)
    feed.emit(
        OutcomeEvent(kind="run.evaluated", task_id=goal.task_id, goal_id=goal.id, passed=passed)
    )


def test_report_contains_every_phase_section(tmp_path):
    horizon, feed, reporter, made = _loop(tmp_path)
    _emit(horizon, feed, made[0].id, True)
    _emit(horizon, feed, made[1].id, False)

    report = reporter.render(horizon.state())

    assert "## Decomposition" in report
    assert "## Intake" in report
    assert "## Feedback" in report
    assert "## Current direction" in report
    assert "Build API" in report and "Build UI" in report
    assert "**Verdicts folded:** 2" in report
    assert len(reporter.transitions) == 2


def test_offline_loop_surfaces_the_failed_goal_above_the_passed_one(tmp_path):
    horizon, feed, _, made = _loop(tmp_path)
    _emit(horizon, feed, made[0].id, True)  # API 0.9 -> 0.45 on_track
    _emit(horizon, feed, made[1].id, False)  # UI 0.6 -> 0.85 blocked

    goals = {g.title: g for g in horizon.state()[0].goals}
    assert goals["Build UI"].health == "blocked"
    assert goals["Build API"].health == "on_track"
    # back-pressure: the failed goal is now scored above the passed one
    assert goals["Build UI"].score > goals["Build API"].score


def test_render_direction_handles_empty():
    assert "no decisions" in render_direction([])
