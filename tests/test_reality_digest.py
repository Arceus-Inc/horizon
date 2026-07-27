"""Phase A1 — ``Horizon.digest``: the deterministic reality digest the CEO plans against.

TDD spec (one-mind-one-ledger refactor):

- ``digest()`` returns a bounded, deterministic ``RealityDigest`` — no LLM — assembled from the existing
  read model (``state()``) plus the optional ``CapacityPort`` snapshot.
- Goals are grouped by execution state: **done** (goal is done), **blocked** (health == "blocked", not
  done), **in_flight** (everything else not done). A per-decision summary and a health histogram are
  included, plus capacity by profession (degrading to "unavailable" when no CapacityPort is wired).
- Archived decisions are excluded; every other decision (proposed / active / paused / done) is digested.
"""

from __future__ import annotations

from dataclasses import replace

from horizon import Horizon
from horizon.model import DecisionDigest, RealityDigest
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed


class FakeCapacityPort:
    """Minimal ``CapacityPort`` — returns a fixed snapshot."""

    def __init__(self, snapshot):
        self._snapshot = tuple(snapshot)

    def snapshot(self):
        return self._snapshot


def _horizon(tmp_path, *, capacity=None):
    decisions = DecisionStore(tmp_path / "decisions.json")
    strategy = StrategyStore(tmp_path / "strategy.json")
    horizon = Horizon(
        goals=FakeGoalStore(),
        intake=FakeIntakePort(),
        outcomes=FakeOutcomeFeed(),
        capacity=capacity,
        decisions=decisions,
        strategy=strategy,
        default_assignee="moe",
    )
    return horizon, decisions, strategy


def _spec(title, *, score=0.5, **extra):
    base = {"title": title, "metric": "shipped", "target": "v1", "score": score}
    base.update(extra)
    return base


def _set(strategy, goal_id, **fields):
    """Mutate a goal's strategy record in place (preserving title/decision link)."""
    record = strategy.get(goal_id)
    strategy.put(replace(record, **fields))


# -- shape + empty ------------------------------------------------------------------------------

def test_digest_on_empty_horizon_is_empty(tmp_path):
    horizon, _d, _s = _horizon(tmp_path)
    digest = horizon.digest()

    assert isinstance(digest, RealityDigest)
    assert digest.decisions == ()
    assert digest.goals_total == 0
    assert digest.done == ()
    assert digest.blocked == ()
    assert digest.in_flight == ()
    assert digest.by_health == {}
    assert digest.capacity == ()
    assert digest.capacity_available is False


def test_digest_needs_no_reasoner(tmp_path):
    # built without a reasoner; digest must be fully deterministic.
    horizon, _d, _s = _horizon(tmp_path)
    horizon.propose_roadmap("Mission", [_spec("A")])
    assert isinstance(horizon.digest(), RealityDigest)


# -- grouping done / blocked / in_flight --------------------------------------------------------

def test_digest_groups_goals_by_execution_state(tmp_path):
    horizon, decisions, strategy = _horizon(tmp_path)
    decision = horizon.propose_roadmap(
        "Ship the suite", [_spec("Notes"), _spec("Timer"), _spec("Habit")]
    )
    gid_notes, gid_timer, _gid_habit = decisions.get(decision.id).goal_ids
    _set(strategy, gid_notes, done=True)             # done
    _set(strategy, gid_timer, health="blocked")      # blocked
    # habit left as-is (health "unknown", not done) -> in_flight

    digest = horizon.digest()

    assert digest.goals_total == 3
    assert {g.title for g in digest.done} == {"Notes"}
    assert {g.title for g in digest.blocked} == {"Timer"}
    assert {g.title for g in digest.in_flight} == {"Habit"}
    # done goal reports status "done"; the GoalDigest carries the rich fields
    (done,) = digest.done
    assert done.status == "done"
    assert done.metric == "shipped"
    assert done.decision_id == decision.id


def test_digest_blocked_requires_not_done(tmp_path):
    # a goal that is both done and health=="blocked" counts as done, never blocked.
    horizon, decisions, strategy = _horizon(tmp_path)
    decision = horizon.propose_roadmap("M", [_spec("A")])
    (gid,) = decisions.get(decision.id).goal_ids
    _set(strategy, gid, done=True, health="blocked")

    digest = horizon.digest()
    assert {g.title for g in digest.done} == {"A"}
    assert digest.blocked == ()


def test_digest_health_histogram_counts_all_goals(tmp_path):
    horizon, decisions, strategy = _horizon(tmp_path)
    decision = horizon.propose_roadmap("M", [_spec("A"), _spec("B"), _spec("C")])
    a, b, c = decisions.get(decision.id).goal_ids
    _set(strategy, a, health="on_track")
    _set(strategy, b, health="blocked")
    _set(strategy, c, health="on_track")

    digest = horizon.digest()
    assert digest.by_health == {"on_track": 2, "blocked": 1}


# -- decision summary + archived exclusion ------------------------------------------------------

def test_digest_summarizes_decisions(tmp_path):
    horizon, _decisions, _s = _horizon(tmp_path)
    decision = horizon.propose_roadmap("Ship the suite", [_spec("A"), _spec("B")])

    digest = horizon.digest()
    assert len(digest.decisions) == 1
    (summary,) = digest.decisions
    assert isinstance(summary, DecisionDigest)
    assert summary.id == decision.id
    assert summary.statement == "Ship the suite"
    assert summary.status == "proposed"
    assert summary.goal_count == 2


def test_digest_excludes_archived_decisions(tmp_path):
    horizon, decisions, _strategy = _horizon(tmp_path)
    live = horizon.propose_roadmap("Live", [_spec("Keep")])
    gone = horizon.propose_roadmap("Old", [_spec("Drop")])
    # archive the second decision
    archived = replace(decisions.get(gone.id), status="archived")
    decisions.put(archived)

    digest = horizon.digest()
    assert {d.id for d in digest.decisions} == {live.id}
    assert {g.title for g in digest.in_flight} == {"Keep"}
    assert digest.goals_total == 1


# -- capacity (with graceful fallback) ----------------------------------------------------------

def test_digest_without_capacity_port_marks_unavailable(tmp_path):
    horizon, _d, _s = _horizon(tmp_path)  # no capacity port
    horizon.propose_roadmap("M", [_spec("A")])
    digest = horizon.digest()
    assert digest.capacity == ()
    assert digest.capacity_available is False


def test_digest_includes_capacity_snapshot_when_wired(tmp_path):
    from dream.contracts import ProfessionCapacity

    snap = (
        ProfessionCapacity(
            profession="frontend_engineer",
            eligible=3,
            running=1,
            assigned_nonterminal=2,
            queued_wakes=0,
            budget_blocked=0,
            budget_headroom_cents=100_000,
        ),
    )
    horizon, _d, _s = _horizon(tmp_path, capacity=FakeCapacityPort(snap))
    horizon.propose_roadmap("M", [_spec("A")])

    digest = horizon.digest()
    assert digest.capacity_available is True
    assert digest.capacity == snap
