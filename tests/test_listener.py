"""Slice 3 (feedback): the OutcomeListener folds landed verdicts into health + re-priority."""

from __future__ import annotations

from horizon.feedback import OutcomeListener
from horizon.intake import Prioritiser
from horizon.model._strategy import StrategyRecord
from horizon.ports import OutcomeEvent
from horizon.store import StrategyStore
from tests.fakes import FakeIntakePort, FakeOutcomeFeed


def _wire(tmp_path, record):
    strategy = StrategyStore(tmp_path / "strategy.json")
    strategy.put(record)
    feed = FakeOutcomeFeed()
    intake = FakeIntakePort()
    listener = OutcomeListener(outcomes=feed, strategy=strategy, prioritiser=Prioritiser(intake))
    return listener, feed, strategy, intake


def test_pass_verdict_updates_health_and_reprioritises(tmp_path):
    listener, feed, strategy, intake = _wire(
        tmp_path, StrategyRecord(goal_id="g1", score=0.8, task_id="task_1")
    )
    listener.start()

    feed.emit(OutcomeEvent(kind="run.evaluated", task_id="task_1", goal_id="g1", passed=True))

    updated = strategy.get("g1")
    assert updated.health == "on_track"
    assert updated.score == 0.4
    assert intake.priorities["task_1"] == "medium"  # 0.4 -> medium
    assert listener.handled == 1


def test_fail_verdict_bumps_score_and_reprioritises(tmp_path):
    listener, feed, strategy, intake = _wire(
        tmp_path, StrategyRecord(goal_id="g1", score=0.6, task_id="task_1")
    )
    listener.start()

    feed.emit(OutcomeEvent(kind="run.evaluated", task_id="task_1", goal_id="g1", passed=False))

    updated = strategy.get("g1")
    assert updated.health == "blocked"  # no prior pass
    assert updated.score == 0.85  # 0.6 + 0.25
    assert intake.priorities["task_1"] == "high"


def test_non_verdict_events_are_ignored(tmp_path):
    listener, feed, strategy, _ = _wire(
        tmp_path, StrategyRecord(goal_id="g1", score=0.8, task_id="task_1")
    )
    listener.start()

    feed.emit(OutcomeEvent(kind="run.done", task_id="task_1", goal_id="g1", passed=True))
    feed.emit(OutcomeEvent(kind="run.evaluated", task_id="task_1", goal_id="g1", passed=None))

    assert strategy.get("g1").health == "unknown"
    assert listener.handled == 0


def test_outcome_for_unknown_goal_is_ignored(tmp_path):
    listener, feed, _, _ = _wire(
        tmp_path, StrategyRecord(goal_id="g1", score=0.8, task_id="task_1")
    )
    listener.start()

    feed.emit(OutcomeEvent(kind="run.evaluated", task_id="task_x", goal_id="other", passed=True))

    assert listener.handled == 0


def test_stop_unsubscribes(tmp_path):
    listener, feed, strategy, _ = _wire(
        tmp_path, StrategyRecord(goal_id="g1", score=0.8, task_id="task_1")
    )
    listener.start()
    listener.stop()

    feed.emit(OutcomeEvent(kind="run.evaluated", task_id="task_1", goal_id="g1", passed=True))

    assert listener.handled == 0
    assert strategy.get("g1").health == "unknown"
