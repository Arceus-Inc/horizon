"""Slice 2 integration — the Submitter drives a REAL chorus through the composition-root bridge.

No LLM here (that is the decomposer's live test); this pins that a horizon submission becomes a real
chorus task, linked by ``goal_id``, stamped ``horizon_intake``, at the score-derived priority — and that
it is idempotent. Submits with no assignee so it needs no hired employee (the M3 demo runs a real beat).
"""

from __future__ import annotations

import dream
import pytest
from chorus.facade import Chorus
from examples.chorus_bridge import ChorusGoalStore, ChorusIntakePort

from horizon.intake import Submitter
from horizon.model import Goal
from horizon.model._strategy import StrategyRecord
from horizon.ports import GoalNode
from horizon.store import StrategyStore


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
