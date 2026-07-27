"""Phase E — the re-plan detector: a deterministic signal to wake the CEO to re-plan (no LLM).

TDD spec (one-mind-one-ledger refactor):

- ``detect_replan(digest)`` is a pure predicate over the reality digest (A1). It fires when the pipeline
  has slack the CEO should fill or fix: **no in-flight goals** (the roadmap is exhausted/unstarted),
  **free capacity** beyond the in-flight pipeline, or **blocked goals** that need re-scoping. Each firing
  carries human-readable reasons. When the pipeline is healthy and fully occupied, it stays quiet.
- ``Horizon.detect_replan()`` runs it over the live digest; the consumer (conductor/operator) turns a
  firing signal into a CEO wake, deduping so it does not re-wake while a re-plan is already pending.
"""

from __future__ import annotations

from dream.contracts import ProfessionCapacity

from horizon import Horizon
from horizon.feedback import ReplanSignal, detect_replan
from horizon.model import DecisionDigest, GoalDigest, RealityDigest
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed


def _goal(title, *, status="active", health="on_track"):
    return GoalDigest(
        id=f"g_{title}",
        title=title,
        decision_id="d1",
        status=status,
        health=health,
        score=0.5,
        effective_priority="medium",
        metric="shipped",
        target="v1",
    )


def _cap(profession, *, eligible, assigned):
    return ProfessionCapacity(
        profession=profession,
        eligible=eligible,
        running=0,
        assigned_nonterminal=assigned,
        queued_wakes=0,
        budget_blocked=0,
        budget_headroom_cents=None,
    )


def _digest(*, in_flight=(), blocked=(), done=(), capacity=(), capacity_available=False):
    return RealityDigest(
        decisions=(DecisionDigest(id="d1", statement="ship", status="active", goal_count=1),),
        goals_total=len(in_flight) + len(blocked) + len(done),
        done=tuple(done),
        blocked=tuple(blocked),
        in_flight=tuple(in_flight),
        by_health={},
        capacity=tuple(capacity),
        capacity_available=capacity_available,
    )


# -- pure predicate -----------------------------------------------------------------------------

def test_replan_fires_when_no_in_flight_goals():
    signal = detect_replan(_digest(done=(_goal("Notes", status="done"),)))
    assert isinstance(signal, ReplanSignal)
    assert signal.should_replan is True
    assert any("in-flight" in r for r in signal.reasons)


def test_replan_quiet_when_pipeline_full_and_no_slack():
    # work in flight, no capacity port, nothing blocked -> nothing to do
    signal = detect_replan(_digest(in_flight=(_goal("Notes"), _goal("Timer"))))
    assert signal.should_replan is False
    assert signal.reasons == ()


def test_replan_fires_on_free_capacity_beyond_the_pipeline():
    signal = detect_replan(
        _digest(
            in_flight=(_goal("Notes"),),
            capacity=(_cap("frontend_engineer", eligible=5, assigned=1),),
            capacity_available=True,
        )
    )
    assert signal.should_replan is True
    assert any("capacity" in r for r in signal.reasons)


def test_replan_no_free_capacity_when_fully_assigned():
    # eligible == assigned -> zero free slots; a single in-flight goal keeps it quiet
    signal = detect_replan(
        _digest(
            in_flight=(_goal("Notes"),),
            capacity=(_cap("frontend_engineer", eligible=2, assigned=2),),
            capacity_available=True,
        )
    )
    assert signal.should_replan is False


def test_replan_fires_on_blocked_goals():
    signal = detect_replan(
        _digest(in_flight=(_goal("Notes"),), blocked=(_goal("Timer", health="blocked"),))
    )
    assert signal.should_replan is True
    assert any("blocked" in r for r in signal.reasons)


def test_replan_no_capacity_port_gives_no_capacity_reason():
    signal = detect_replan(_digest(in_flight=(_goal("Notes"),)))  # no capacity
    assert signal.should_replan is False


# -- facade over the live digest ----------------------------------------------------------------

def _horizon(tmp_path):
    return Horizon(
        goals=FakeGoalStore(),
        intake=FakeIntakePort(),
        outcomes=FakeOutcomeFeed(),
        decisions=DecisionStore(tmp_path / "d.json"),
        strategy=StrategyStore(tmp_path / "s.json"),
        default_assignee="moe",
    )


def test_facade_detect_replan_fires_on_a_fresh_company(tmp_path):
    # nothing authored yet -> no in-flight goals -> the CEO should be woken to plan
    signal = _horizon(tmp_path).detect_replan()
    assert isinstance(signal, ReplanSignal)
    assert signal.should_replan is True


def test_facade_detect_replan_reflects_live_state(tmp_path):
    horizon = _horizon(tmp_path)
    # a proposed roadmap authors goals; they are active (in flight from the digest's view) -> quiet
    horizon.propose_roadmap("Ship", [{"title": "Notes", "metric": "m", "target": "t", "score": 0.5}])
    assert horizon.detect_replan().should_replan is False
