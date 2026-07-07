"""Slice 2 integration — the Submitter drives a REAL chorus through the composition-root bridge.

No LLM here (that is the decomposer's live test); this pins that a horizon submission becomes a real
chorus task, linked by ``goal_id``, stamped ``horizon_intake``, at the score-derived priority — and that
it is idempotent. Submits with no assignee so it needs no hired employee (the M3 demo runs a real beat).
"""

from __future__ import annotations

from datetime import UTC, datetime

import dream
import pytest
from chorus.events import Event, EventKind
from chorus.facade import Chorus
from examples.chorus_bridge import ChorusGoalStore, ChorusIntakePort, ChorusOutcomeFeed

from horizon import Horizon
from horizon.intake import Submitter
from horizon.model import Decision, Goal
from horizon.model._strategy import StrategyRecord
from horizon.ports import GoalNode
from horizon.store import DecisionStore, StrategyStore


@pytest.fixture
def chorus(tmp_path):
    return Chorus.build(
        db_path=str(tmp_path / "ledger.db"),
        org_repo=str(tmp_path / "org"),
        memory_repo=str(tmp_path / "memory"),
        dream=dream,
    )


def test_submitter_opens_a_linked_prioritised_task_in_chorus(tmp_path, chorus):
    strategy = StrategyStore(tmp_path / "strategy.json")
    strategy.put(StrategyRecord(goal_id="goal_x", score=0.9, decision_id="dec_1"))
    # the decomposer would have written the goal first; task.goal_id is a FK to goal(id)
    ChorusGoalStore(chorus).upsert(
        GoalNode(id="goal_x", title="Build the note-capture API", level="goal")
    )
    submitter = Submitter(intake=ChorusIntakePort(chorus), strategy=strategy)
    goal = Goal(id="goal_x", title="Build the note-capture API", decision_id="dec_1", score=0.9)

    task_id = submitter.submit(goal)

    task = chorus._ledger.tasks.get(task_id)
    assert task is not None
    assert task.goal_id == "goal_x"
    assert task.priority.value == "high"  # score 0.9 -> high
    assert task.origin_kind.value == "horizon_intake"

    # idempotent through the real dedup path
    assert submitter.submit(goal) == task_id
    assert strategy.get("goal_x").task_id == task_id


def test_full_loop_reprioritises_real_task_on_a_real_outcome(tmp_path, chorus):
    # Wire horizon over the real chorus bridge (no reasoner — we seed the goal by hand here).
    strategy = StrategyStore(tmp_path / "strategy.json")
    decisions = DecisionStore(tmp_path / "decisions.json")
    horizon = Horizon(
        goals=ChorusGoalStore(chorus),
        intake=ChorusIntakePort(chorus),
        outcomes=ChorusOutcomeFeed(chorus),
        decisions=decisions,
        strategy=strategy,
    )
    decisions.put(Decision(id="dec_1", statement="ship it", goal_ids=["g1"]))
    ChorusGoalStore(chorus).upsert(GoalNode(id="g1", title="Build the thing", level="goal"))
    strategy.put(StrategyRecord(goal_id="g1", score=0.9, decision_id="dec_1"))

    task_id = horizon.submit_goal(horizon.goal_view("g1"))
    assert chorus._ledger.tasks.get(task_id).priority.value == "high"  # score 0.9

    horizon.start()
    # A real chorus DoD verdict (passed) flows through the bridge -> listener -> re-priority.
    chorus._event_bus.emit(
        Event(
            kind=EventKind.RUN_EVALUATED,
            at=datetime.now(UTC),
            task_id=task_id,
            payload={"passed": True},
        )
    )

    after = horizon.goal_view("g1")
    assert after.health == "on_track"
    assert after.score == 0.45  # 0.9 * 0.5 decay
    # the real chorus task was re-prioritised high -> medium by horizon
    assert chorus._ledger.tasks.get(task_id).priority.value == "medium"


def test_bridge_maps_real_evaluator_outcome_to_passed(tmp_path, chorus):
    # A REAL chorus RUN_EVALUATED carries dream's verdict as ``outcome`` (pass/fail), not a boolean —
    # the bridge must map it, or real beats would never move health. Pins that mapping.
    strategy = StrategyStore(tmp_path / "strategy.json")
    decisions = DecisionStore(tmp_path / "decisions.json")
    horizon = Horizon(
        goals=ChorusGoalStore(chorus),
        intake=ChorusIntakePort(chorus),
        outcomes=ChorusOutcomeFeed(chorus),
        decisions=decisions,
        strategy=strategy,
    )
    decisions.put(Decision(id="dec_1", statement="investigate", goal_ids=["g1"]))
    ChorusGoalStore(chorus).upsert(GoalNode(id="g1", title="Investigate", level="goal"))
    strategy.put(StrategyRecord(goal_id="g1", score=0.8, decision_id="dec_1"))
    task_id = horizon.submit_goal(horizon.goal_view("g1"))
    horizon.start()

    chorus._event_bus.emit(
        Event(
            kind=EventKind.RUN_EVALUATED,
            at=datetime.now(UTC),
            task_id=task_id,
            payload={"outcome": "pass", "score": 1.0},  # no boolean "passed" — the real shape
        )
    )

    after = horizon.goal_view("g1")
    assert after.health == "on_track"  # outcome="pass" -> passed=True
    assert after.score == 0.4  # 0.8 * 0.5
