"""M1 seam proof — the composition-root adapters satisfy horizon's ports and round-trip through a chorus.

Builds a real (one-employee-capable) chorus, wraps it in the ``examples/chorus_bridge.py`` adapters, and
proves horizon can, through the ``dream.contracts`` ports alone: author + read the OKR tree, open an
idempotent intake task linked to a goal, and receive translated landed outcomes. No beat is run here —
the full submit -> assign -> beat -> outcome loop is the M3 ``examples/`` demo.
"""

from __future__ import annotations

from datetime import UTC, datetime

import dream
import pytest
from chorus.events import Event, EventKind
from chorus.facade import Chorus
from chorus.ledger import ExecutionMode, Task, TaskStatus
from chorus.observability import EventBus
from dream.contracts import GoalNode, GoalStore, IntakePort, OutcomeEvent, OutcomeFeed
from examples.chorus_bridge import ChorusGoalStore, ChorusIntakePort, ChorusOutcomeFeed


@pytest.fixture
def chorus(tmp_path):
    return Chorus.build(
        db_path=str(tmp_path / "ledger.db"),
        org_repo=str(tmp_path / "org"),
        memory_repo=str(tmp_path / "memory"),
        dream=dream,
    )


def test_adapters_satisfy_the_ports(chorus):
    # runtime_checkable structural conformance — the seam contract holds.
    assert isinstance(ChorusGoalStore(chorus), GoalStore)
    assert isinstance(ChorusIntakePort(chorus), IntakePort)
    assert isinstance(ChorusOutcomeFeed(chorus), OutcomeFeed)


def test_goal_tree_round_trip(chorus):
    store = ChorusGoalStore(chorus)
    store.upsert(GoalNode(id="g_root", title="Ship budget tracker", level="goal"))
    store.upsert(
        GoalNode(id="g_leaf", title="build the app", level="goal", parent_id="g_root")
    )

    root = store.get("g_root")
    assert root is not None and root.title == "Ship budget tracker"
    assert [c.id for c in store.children("g_root")] == ["g_leaf"]
    assert [c.id for c in store.children(None)] == ["g_root"]

    # update path (upsert on an existing id)
    store.upsert(
        GoalNode(id="g_root", title="Ship budget tracker v2", level="goal", status="paused")
    )
    updated = store.get("g_root")
    assert updated is not None
    assert updated.title == "Ship budget tracker v2"
    assert updated.status == "paused"


def test_intake_is_idempotent_and_linked(chorus):
    store = ChorusGoalStore(chorus)
    store.upsert(GoalNode(id="g_leaf", title="build the app", level="goal"))
    intake = ChorusIntakePort(chorus)

    first = intake.submit("build the app", goal_id="g_leaf", origin_fingerprint="fp-1")
    again = intake.submit("build the app", goal_id="g_leaf", origin_fingerprint="fp-1")
    assert first == again  # idempotent on (horizon_intake, fingerprint)

    other = intake.submit("write the tests", goal_id="g_leaf", origin_fingerprint="fp-2")
    assert other != first

    task = chorus._ledger.tasks.get(first)
    assert task is not None
    assert task.goal_id == "g_leaf"
    assert task.origin_kind.value == "horizon_intake"


def test_outcome_feed_translates_events(chorus):
    store = ChorusGoalStore(chorus)
    store.upsert(GoalNode(id="g_leaf", title="build", level="goal"))
    intake = ChorusIntakePort(chorus)
    task_id = intake.submit("build", goal_id="g_leaf", origin_fingerprint="fp-x")

    feed = ChorusOutcomeFeed(chorus)
    seen: list[OutcomeEvent] = []
    unsubscribe = feed.subscribe(seen.append)

    # a non-outcome kind is dropped by the translator
    chorus._event_bus.emit(
        Event(kind=EventKind.WAKE_ENQUEUED, at=datetime.now(UTC), task_id=task_id)
    )
    # an outcome kind is translated and its goal_id resolved from the task
    chorus._event_bus.emit(
        Event(
            kind=EventKind.RUN_EVALUATED,
            at=datetime.now(UTC),
            task_id=task_id,
            payload={"status": "done", "passed": True},
        )
    )
    unsubscribe()
    # after unsubscribe, further events are not delivered
    chorus._event_bus.emit(
        Event(kind=EventKind.RUN_DONE, at=datetime.now(UTC), task_id=task_id)
    )

    assert len(seen) == 1
    outcome = seen[0]
    assert outcome.kind == "run.evaluated"
    assert outcome.task_id == task_id
    assert outcome.goal_id == "g_leaf"
    assert outcome.status == "done"
    assert outcome.passed is True


def test_outcome_feed_preserves_hierarchy_and_replay_identity(chorus, tmp_path):
    chorus._event_bus = EventBus(log_path=tmp_path / "events.jsonl")
    store = ChorusGoalStore(chorus)
    store.upsert(GoalNode(id="g_team", title="ship together", level="goal"))
    chorus._ledger.tasks.submit(
        Task(
            id="root-team",
            intent="ship together",
            goal_id="g_team",
            status=TaskStatus.TODO,
            execution_mode=ExecutionMode.DELEGATION,
            team_id="team-1",
        )
    )
    chorus._ledger.tasks.submit(
        Task(
            id="child-team",
            intent="build one area",
            goal_id="g_team",
            parent_id="root-team",
            depth=1,
            status=TaskStatus.DONE,
            execution_mode=ExecutionMode.DELIVERY,
            team_id="team-1",
        )
    )
    at = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    chorus._event_bus.emit(
        Event(
            kind=EventKind.RUN_EVALUATED,
            at=at,
            trace_id="trace-1",
            task_id="child-team",
            run_id="run-1",
            payload={"passed": True},
        )
    )

    replayed = list(ChorusOutcomeFeed(chorus).replay())[-1]

    assert replayed.parent_task_id == "root-team"
    assert replayed.root_task_id == "root-team"
    assert replayed.team_id == "team-1"
    assert replayed.execution_mode == "delivery"
    assert replayed.is_root_outcome is False
    assert replayed.event_id is not None
    assert replayed.task_revision == int(at.timestamp() * 1_000_000)
    assert list(ChorusOutcomeFeed(chorus).replay())[-1].event_id == replayed.event_id
