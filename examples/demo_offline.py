"""Offline demo — the full Decision -> Goal -> Task loop against a REAL chorus, deterministically.

No creds needed: a canned reasoner stands in for the LLM and synthetic DoD verdicts stand in for real
beats, but everything else is the real path — real chorus goal table, real intake door, real event bus,
the real Submitter / Prioritiser / OutcomeListener. Proves the wiring end-to-end and writes a full
insight report to ``reports/offline-demo-report.md``.

    uv run python examples/demo_offline.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dream
from chorus.events import Event, EventKind
from chorus.facade import Chorus
from chorus_bridge import ChorusGoalStore, ChorusIntakePort, ChorusOutcomeFeed
from dream.api.substrate import CompletionResult

from horizon import Horizon, LoopReporter
from horizon.model import Decision

_DECISION = "Build an AI note-taker for working professionals"

_CANNED = {
    "goals": [
        {
            "title": "Build the note-capture REST API",
            "metric": "endpoints live + integration tests green",
            "target": "3 endpoints, 100% of contract tests passing",
            "rationale": "the core capability everything else depends on",
            "score": 0.9,
        },
        {
            "title": "Design the mobile capture UI",
            "metric": "usability pass rate in review",
            "target": ">=2 screens, >=80% reviewers rate 'usable'",
            "rationale": "the primary entry point for professionals on the go",
            "score": 0.7,
        },
        {
            "title": "Add full-text search over saved notes",
            "metric": "top-5 retrieval success on a test set",
            "target": ">=90% success, p95 < 500ms on 1k notes",
            "rationale": "notes are worthless if you cannot find them again",
            "score": 0.5,
        },
    ]
}

# Simulated DoD verdicts, by goal index: API passes, UI fails (needs rework), search passes.
_VERDICTS = {0: True, 1: False, 2: True}


class CannedReasoner:
    """A ``Reasoner`` that returns a fixed decomposition — stands in for the LLM offline."""

    name = "canned"

    def __init__(self, text: str) -> None:
        self._text = text

    def complete(self, prompt: str, params: dict[str, Any] | None = None) -> CompletionResult:
        return CompletionResult(text=self._text)


def _report_path() -> Path:
    return Path(__file__).resolve().parent.parent / "reports" / "offline-demo-report.md"


def main() -> int:
    workdir = Path(__file__).resolve().parent.parent / ".horizon" / "offline-demo"
    workdir.mkdir(parents=True, exist_ok=True)
    chorus = Chorus.build(
        db_path=str(workdir / "ledger.db"),
        org_repo=str(workdir / "org"),
        memory_repo=str(workdir / "memory"),
        dream=dream,
    )

    from horizon.store import DecisionStore, StrategyStore

    reporter = LoopReporter(title="Offline demo — AI note-taker for working professionals")
    horizon = Horizon(
        goals=ChorusGoalStore(chorus),
        intake=ChorusIntakePort(chorus),
        outcomes=ChorusOutcomeFeed(chorus),
        reasoner=CannedReasoner(json.dumps(_CANNED)),
        decisions=DecisionStore(workdir / "decisions.json"),
        strategy=StrategyStore(workdir / "strategy.json"),
        outcome_observer=reporter.observe,
    )

    # 1) seed the decision, 2) decompose (canned LLM)
    decision = Decision(id="dec_offline", statement=_DECISION, owner=None)
    horizon.seed_decision(decision)
    goals = horizon.decompose(decision.id)
    reporter.record_decomposition(decision, goals)
    print(f"decomposed into {len(goals)} goals")

    # 3) start listening, 4) submit each leaf goal to chorus
    horizon.start()
    for goal in goals:
        task_id = horizon.submit_goal(goal)
        reporter.record_submission(goal, task_id, assignee=goal.owner)
        print(f"  submitted {goal.title!r} -> {task_id} @ score {goal.score:.2f}")

    # 5) simulate landed DoD verdicts on the REAL bus -> listener folds them -> re-priority
    for index, passed in _VERDICTS.items():
        goal = horizon.goal_view(goals[index].id)
        assert goal is not None and goal.task_id is not None
        chorus._event_bus.emit(
            Event(
                kind=EventKind.RUN_EVALUATED,
                at=datetime.now(UTC),
                task_id=goal.task_id,
                payload={"passed": passed},
            )
        )
        print(f"  verdict {'PASS' if passed else 'FAIL'} on {goal.title!r} -> health now recomputed")

    # 6) render the report
    states = horizon.state()
    report = reporter.render(states)
    path = _report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(f"\nreport written to {path}")
    print("\n--- direction after the loop ---")
    for state in states:
        for goal in sorted(state.goals, key=lambda g: g.score, reverse=True):
            print(f"  [{goal.score:.2f} {goal.health:>9}] {goal.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
