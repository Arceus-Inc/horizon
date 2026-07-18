"""Slice 2 (intake): fingerprint, ScorePolicy/Prioritiser, and the Submitter."""

from __future__ import annotations

import pytest

from horizon.intake import (
    Prioritiser,
    ScorePolicy,
    Submitter,
    fingerprint,
    normalize_intent,
)
from horizon.model import Goal
from horizon.model._strategy import StrategyRecord
from horizon.store import StrategyStore
from tests.fakes import FakeIntakePort

# --- fingerprint ---------------------------------------------------------------


def test_normalize_lowercases_and_collapses_whitespace():
    assert normalize_intent("  Build   the\tNOTE\napi ") == "build the note api"


def test_fingerprint_is_deterministic_goal_scoped_and_intent_sensitive():
    base = fingerprint("goal_1", "Build the API")
    assert base == fingerprint("goal_1", "build   the api")  # normalized-equal -> same
    assert base.startswith("goal_1:")
    assert base != fingerprint("goal_2", "Build the API")  # different goal
    assert base != fingerprint("goal_1", "Build the UI")  # different intent


# --- ScorePolicy / Prioritiser -------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (1.0, "high"),
        (0.75, "high"),
        (0.74, "medium"),
        (0.40, "medium"),
        (0.39, "low"),
        (0.0, "low"),
    ],
)
def test_default_policy_buckets(score, expected):
    assert ScorePolicy().priority_for(score) == expected


def test_custom_thresholds_are_honored():
    policy = ScorePolicy(high=0.9, medium=0.5)
    assert policy.priority_for(0.95) == "high"
    assert policy.priority_for(0.85) == "medium"
    assert policy.priority_for(0.30) == "low"


def test_prioritiser_apply_writes_priority_and_returns_it():
    intake = FakeIntakePort()
    task_id = intake.submit("x", goal_id="goal_1", origin_fingerprint="fp")
    chosen = Prioritiser(intake).apply(task_id, 0.8)
    assert chosen == "high"
    assert intake.priorities[task_id] == "high"


# --- Submitter -----------------------------------------------------------------


def _goal(**overrides) -> Goal:
    base: dict[str, object] = {
        "id": "goal_1",
        "title": "Build the note-capture API",
        "decision_id": "dec_1",
        "score": 0.9,
        "owner": "moe",
    }
    base.update(overrides)
    return Goal(**base)


def _submitter(tmp_path, *, default_assignee=None, record=None):
    strategy = StrategyStore(tmp_path / "strategy.json")
    if record is not None:
        strategy.put(record)
    intake = FakeIntakePort()
    return (
        Submitter(intake=intake, strategy=strategy, default_assignee=default_assignee),
        intake,
        strategy,
    )


def test_submit_creates_one_task_linked_and_prioritised(tmp_path):
    record = StrategyRecord(goal_id="goal_1", score=0.9, decision_id="dec_1")
    submitter, intake, strategy = _submitter(tmp_path, default_assignee="moe", record=record)

    task_id = submitter.submit(_goal())

    assert len(intake.submitted) == 1
    sub = intake.submitted[0]
    assert sub["intent"] == "Build the note-capture API"
    assert sub["goal_id"] == "goal_1"
    assert sub["assignee"] == "moe"
    assert sub["priority"] == "high"  # score 0.9
    assert sub["fingerprint"].startswith("goal_1:")
    assert strategy.get("goal_1").task_id == task_id


def test_submit_is_idempotent(tmp_path):
    record = StrategyRecord(goal_id="goal_1", score=0.9, decision_id="dec_1")
    submitter, intake, _ = _submitter(tmp_path, default_assignee="moe", record=record)

    first = submitter.submit(_goal())
    second = submitter.submit(_goal())

    assert first == second
    assert len(intake.submitted) == 1


def test_owner_overrides_default_assignee(tmp_path):
    record = StrategyRecord(goal_id="goal_1", score=0.5, decision_id="dec_1")
    submitter, intake, _ = _submitter(tmp_path, default_assignee="fallback", record=record)

    submitter.submit(_goal(owner="vera"))
    assert intake.submitted[0]["assignee"] == "vera"


def test_default_assignee_used_when_owner_unset(tmp_path):
    record = StrategyRecord(goal_id="goal_1", score=0.5, decision_id="dec_1")
    submitter, intake, _ = _submitter(tmp_path, default_assignee="fallback", record=record)

    submitter.submit(_goal(owner=None))
    assert intake.submitted[0]["assignee"] == "fallback"


def test_priority_comes_from_strategy_record_not_goal(tmp_path):
    # the record's score (0.3 -> low) is authoritative over the passed goal's score (0.9)
    record = StrategyRecord(goal_id="goal_1", score=0.3, decision_id="dec_1")
    submitter, intake, _ = _submitter(tmp_path, record=record)

    submitter.submit(_goal(score=0.9))
    assert intake.submitted[0]["priority"] == "low"
