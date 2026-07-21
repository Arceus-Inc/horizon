"""Slice 3 (feedback): the health + drift model."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from horizon.feedback import HealthPolicy, apply_outcome, staleness_health
from horizon.model._strategy import StrategyRecord


def test_pass_sets_on_track_and_decays_score():
    record = StrategyRecord(goal_id="g", score=0.8)
    apply_outcome(record, passed=True)
    assert record.health == "on_track"
    assert (record.passes, record.fails) == (1, 0)
    assert record.score == 0.4  # 0.8 * 0.5
    assert record.last_outcome_at is not None


def test_fail_with_prior_pass_is_drifting_and_bumps_score():
    record = StrategyRecord(
        goal_id="g", score=0.5, passes=1
    )  # pass-rate after fail = 0.5 -> drifting
    apply_outcome(record, passed=False)
    assert record.health == "drifting"
    assert record.fails == 1
    assert record.score == 0.75  # 0.5 + 0.25


def test_fail_with_poor_pass_rate_is_blocked():
    record = StrategyRecord(goal_id="g", score=0.5)  # no prior pass -> pass-rate 0 -> blocked
    apply_outcome(record, passed=False)
    assert record.health == "blocked"


def test_score_is_clamped_to_unit_range():
    high = StrategyRecord(goal_id="g", score=0.9)
    apply_outcome(high, passed=False)  # 0.9 + 0.25 -> clamp 1.0
    assert high.score == 1.0
    low = StrategyRecord(goal_id="g", score=0.05)
    apply_outcome(low, passed=True)  # 0.05 * 0.5
    assert low.score == 0.025


def test_custom_policy_knobs_are_honored():
    policy = HealthPolicy(fail_bump=0.1, pass_decay=0.9, block_pass_rate=0.8)
    record = StrategyRecord(
        goal_id="g", score=0.5, passes=3
    )  # pass-rate 3/4 = 0.75 < 0.8 -> blocked
    apply_outcome(record, passed=False, policy=policy)
    assert record.health == "blocked"
    assert record.score == 0.6  # 0.5 + 0.1


def test_staleness_drifts_only_on_track_goals():
    now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    stale = StrategyRecord(
        goal_id="g", health="on_track", last_outcome_at=(now - timedelta(days=2)).isoformat()
    )
    assert staleness_health(stale, now=now) == "drifting"

    fresh = StrategyRecord(
        goal_id="g", health="on_track", last_outcome_at=(now - timedelta(minutes=5)).isoformat()
    )
    assert staleness_health(fresh, now=now) == "on_track"

    blocked = StrategyRecord(
        goal_id="g", health="blocked", last_outcome_at=(now - timedelta(days=5)).isoformat()
    )
    assert staleness_health(blocked, now=now) == "blocked"


def test_staleness_with_no_outcome_returns_current_health():
    record = StrategyRecord(goal_id="g", health="unknown")
    assert staleness_health(record) == "unknown"
