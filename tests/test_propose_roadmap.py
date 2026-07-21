"""Phase A2 — ``Horizon.propose_roadmap``: the deterministic, LLM-free accept-roadmap path.

TDD spec for the ledger's accept-path (one-mind-one-ledger refactor):

- ``propose_roadmap(statement, specs)`` seeds a *proposed* decision + authors its goals in one call,
  but does NOT submit them (submission stays with ``submit_decision`` / on approval).
- The ledger enforces STRUCTURAL invariants (defense in depth), independent of the chorus tool:
  non-empty title, metric + target present, score in [0, 1], acyclic ``depends_on`` when present, and
  no goal that duplicates already-done work. Profession/catalog checks are NOT here (they stay in chorus).
- No reasoner is required — the path is fully deterministic.
"""

from __future__ import annotations

import pytest

from horizon import Horizon
from horizon.errors import RoadmapError
from horizon.model import StrategyRecord
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed


def _horizon(tmp_path):
    """A reasoner-less Horizon (proves propose_roadmap is deterministic) with reachable stores."""
    goals = FakeGoalStore()
    intake = FakeIntakePort()
    feed = FakeOutcomeFeed()
    decisions = DecisionStore(tmp_path / "decisions.json")
    strategy = StrategyStore(tmp_path / "strategy.json")
    horizon = Horizon(
        goals=goals,
        intake=intake,
        outcomes=feed,
        decisions=decisions,
        strategy=strategy,
        default_assignee="moe",
    )
    return horizon, goals, intake, decisions, strategy


def _spec(title, *, score=0.5, **extra):
    base = {"title": title, "metric": "shipped", "target": "v1 live", "score": score}
    base.update(extra)
    return base


# -- happy path ---------------------------------------------------------------------------------

def test_propose_roadmap_seeds_decision_and_authors_goals(tmp_path):
    horizon, _goals, _intake, decisions, _strategy = _horizon(tmp_path)

    decision = horizon.propose_roadmap(
        "Ship the calm productivity suite",
        [_spec("Build the notes app", score=0.8), _spec("Build the timer", score=0.6)],
        owner="ceo",
    )

    # decision seeded as *proposed*, persisted, and linked to both goals
    assert decision.status == "proposed"
    assert decision.statement == "Ship the calm productivity suite"
    stored = decisions.get(decision.id)
    assert stored is not None
    assert len(stored.goal_ids) == 2

    # goals authored with their strategy fields (score/metric/target), readable via the facade
    views = [horizon.goal_view(gid) for gid in stored.goal_ids]
    titles = {v.title for v in views}
    assert titles == {"Build the notes app", "Build the timer"}
    for v in views:
        assert v.decision_id == decision.id
        assert v.metric == "shipped"
        assert v.target == "v1 live"
        assert 0.0 <= v.score <= 1.0


def test_propose_roadmap_mints_canonical_uuid_goal_ids(tmp_path):
    # Authored goal ids cross the strategy seam into chorus's Postgres ``goal`` table, whose ``id``
    # column is native ``uuid`` (spec 12 §6). A legacy ``goal_<hex>`` id is unparseable as a uuid and
    # is rejected by the column at insert time — so the ledger MUST mint canonical uuid text here.
    from uuid import UUID

    horizon, _goals, _intake, decisions, _strategy = _horizon(tmp_path)

    decision = horizon.propose_roadmap("Mission", [_spec("Build the notes app"), _spec("Build timer")])

    stored = decisions.get(decision.id)
    assert stored is not None
    for goal_id in stored.goal_ids:
        # round-trips through UUID canonical text unchanged -> a native uuid column accepts it
        assert str(UUID(goal_id)) == goal_id


def test_propose_roadmap_is_author_only_never_submits(tmp_path):
    horizon, _goals, intake, _decisions, _strategy = _horizon(tmp_path)

    horizon.propose_roadmap("Mission", [_spec("Build the notes app")])

    # author-only: nothing reaches the intake port until submit_decision / approval
    assert intake.submitted == []


def test_propose_roadmap_needs_no_reasoner(tmp_path):
    # _horizon builds Horizon without a reasoner; this must not raise the "no reasoner" error.
    horizon, *_ = _horizon(tmp_path)
    decision = horizon.propose_roadmap("Mission", [_spec("Build the notes app")])
    assert decision.status == "proposed"


# -- structural invariants (defense in depth) ---------------------------------------------------

def test_propose_roadmap_rejects_empty_specs(tmp_path):
    horizon, *_ = _horizon(tmp_path)
    with pytest.raises(RoadmapError):
        horizon.propose_roadmap("Mission", [])


def test_propose_roadmap_rejects_blank_title(tmp_path):
    horizon, *_ = _horizon(tmp_path)
    with pytest.raises(RoadmapError):
        horizon.propose_roadmap("Mission", [_spec("   ")])


def test_propose_roadmap_rejects_missing_metric(tmp_path):
    horizon, *_ = _horizon(tmp_path)
    bad = {"title": "Build the notes app", "target": "v1", "score": 0.5}  # no metric
    with pytest.raises(RoadmapError):
        horizon.propose_roadmap("Mission", [bad])


def test_propose_roadmap_rejects_missing_target(tmp_path):
    horizon, *_ = _horizon(tmp_path)
    bad = {"title": "Build the notes app", "metric": "shipped", "score": 0.5}  # no target
    with pytest.raises(RoadmapError):
        horizon.propose_roadmap("Mission", [bad])


@pytest.mark.parametrize("score", [-0.1, 1.5, "high", None, True])
def test_propose_roadmap_rejects_score_out_of_range(tmp_path, score):
    horizon, *_ = _horizon(tmp_path)
    with pytest.raises(RoadmapError):
        horizon.propose_roadmap("Mission", [_spec("Build the notes app", score=score)])


def test_propose_roadmap_rejects_nothing_persists_on_invalid(tmp_path):
    horizon, _goals, _intake, _decisions, strategy = _horizon(tmp_path)
    with pytest.raises(RoadmapError):
        horizon.propose_roadmap("Mission", [_spec("ok"), _spec("   ")])  # 2nd invalid
    # the whole roadmap is rejected atomically — no decision, no goals
    assert strategy.all() == []


# -- optional depends_on: validate acyclicity when present, don't require it ---------------------

def test_propose_roadmap_accepts_acyclic_depends_on(tmp_path):
    horizon, _goals, _intake, decisions, _strategy = _horizon(tmp_path)
    specs = [
        _spec("Design system", key="ds"),
        _spec("Notes app", key="notes", depends_on=["ds"]),
        _spec("Landing site", key="landing", depends_on=["ds", "notes"]),
    ]
    decision = horizon.propose_roadmap("Mission", specs)
    assert len(decisions.get(decision.id).goal_ids) == 3


def test_propose_roadmap_rejects_cyclic_depends_on(tmp_path):
    horizon, *_ = _horizon(tmp_path)
    specs = [
        _spec("A", key="a", depends_on=["b"]),
        _spec("B", key="b", depends_on=["a"]),
    ]
    with pytest.raises(RoadmapError):
        horizon.propose_roadmap("Mission", specs)


def test_propose_roadmap_rejects_unknown_depends_on(tmp_path):
    horizon, *_ = _horizon(tmp_path)
    specs = [_spec("A", key="a", depends_on=["ghost"])]
    with pytest.raises(RoadmapError):
        horizon.propose_roadmap("Mission", specs)


def test_propose_roadmap_flat_roadmap_needs_no_keys(tmp_path):
    # depends_on is optional; a flat v1 roadmap with no deps must not require keys.
    horizon, _g, _i, decisions, _s = _horizon(tmp_path)
    decision = horizon.propose_roadmap(
        "Mission", [_spec("A"), _spec("B"), _spec("C")]
    )
    assert len(decisions.get(decision.id).goal_ids) == 3


# -- no dup-of-done -----------------------------------------------------------------------------

def test_propose_roadmap_rejects_duplicate_of_done_goal(tmp_path):
    horizon, _goals, _intake, _decisions, strategy = _horizon(tmp_path)
    # a previously-completed goal lives in the strategy store
    strategy.put(StrategyRecord(goal_id="g_done", title="Build the notes app", done=True))

    with pytest.raises(RoadmapError):
        # same title (case/space-insensitive) as a done goal
        horizon.propose_roadmap("Mission", [_spec("  build the NOTES app ")])


def test_propose_roadmap_allows_reuse_of_title_that_is_not_done(tmp_path):
    horizon, _goals, _intake, decisions, strategy = _horizon(tmp_path)
    # an in-flight (not done) goal with the same title must NOT block a re-proposal
    strategy.put(StrategyRecord(goal_id="g_wip", title="Build the notes app", done=False))

    decision = horizon.propose_roadmap("Mission", [_spec("Build the notes app")])
    assert len(decisions.get(decision.id).goal_ids) == 1
