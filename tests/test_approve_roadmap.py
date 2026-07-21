"""Phase D — ``Horizon.approve_roadmap``: turn a CEO-proposed roadmap into running work.

TDD spec (one-mind-one-ledger refactor):

- A roadmap authored by ``propose_roadmap`` is a *proposed* decision with authored-but-unsubmitted
  goals. ``approve_roadmap(decision_id)`` is the approval door's verb: it submits every goal to the
  intake port and flips the decision ``proposed -> active``. It is idempotent (the submitter/intake are
  fingerprinted) and refuses a decision that is already ``done``/``archived``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from horizon import Horizon
from horizon.errors import RoadmapError, UnknownDecision
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed


def _horizon(tmp_path):
    goals = FakeGoalStore()
    intake = FakeIntakePort()
    decisions = DecisionStore(tmp_path / "decisions.json")
    strategy = StrategyStore(tmp_path / "strategy.json")
    horizon = Horizon(
        goals=goals,
        intake=intake,
        outcomes=FakeOutcomeFeed(),
        decisions=decisions,
        strategy=strategy,
        default_assignee="moe",
    )
    return horizon, intake, decisions, strategy


def _spec(title, *, score=0.5):
    return {"title": title, "metric": "shipped", "target": "v1", "score": score}


def test_approve_roadmap_submits_goals_and_activates(tmp_path):
    horizon, intake, decisions, _s = _horizon(tmp_path)
    decision = horizon.propose_roadmap("Ship the suite", [_spec("Notes"), _spec("Timer")])
    assert intake.submitted == []  # author-only until approval

    task_ids = horizon.approve_roadmap(decision.id)

    assert len(task_ids) == 2  # both goals reached the workforce
    assert len(intake.submitted) == 2
    assert decisions.get(decision.id).status == "active"  # promoted out of "proposed"


def test_approve_roadmap_unknown_decision_raises(tmp_path):
    horizon, *_ = _horizon(tmp_path)
    with pytest.raises(UnknownDecision):
        horizon.approve_roadmap("dec_nope")


def test_approve_roadmap_is_idempotent(tmp_path):
    horizon, intake, decisions, _s = _horizon(tmp_path)
    decision = horizon.propose_roadmap("Ship", [_spec("Notes")])

    horizon.approve_roadmap(decision.id)
    horizon.approve_roadmap(decision.id)  # a re-approve must not raise or double-submit

    assert decisions.get(decision.id).status == "active"
    assert len(intake.submitted) == 1  # the fingerprinted goal is submitted exactly once


def test_approve_roadmap_refuses_a_terminal_decision(tmp_path):
    horizon, _i, decisions, _s = _horizon(tmp_path)
    decision = horizon.propose_roadmap("Ship", [_spec("Notes")])
    decisions.put(replace(decisions.get(decision.id), status="archived"))

    with pytest.raises(RoadmapError):
        horizon.approve_roadmap(decision.id)
