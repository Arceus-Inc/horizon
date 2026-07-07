"""Live capstone — the WHOLE loop with real components: LLM + a real one-employee chorus beat.

Real LLM decomposes an analytical decision into goals, horizon submits the top goal to a real Analyst
employee, the REAL chorus kernel runs the beat + renders the DoD verdict, that verdict flows back through
the bridge into horizon's OutcomeListener, and the goal's health + priority are updated live. Writes a
full insight report to ``reports/live-demo-report.md``.

Skips cleanly (exit 0) without ``AZURE_OPENAI_*``. Costs a few LLM calls + one Analyst beat.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/demo_live.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
import sys
from pathlib import Path

import dream
from chorus.facade import Chorus
from chorus.ledger import SqliteLedger, TaskStatus
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_bridge import ChorusGoalStore, ChorusIntakePort, ChorusOutcomeFeed
from chorus_harness import EmployeeHarnessFactory
from dream.api.openai import OpenAIChatSubstrate

from horizon import Horizon, LoopReporter
from horizon.model import Decision
from horizon.store import DecisionStore, StrategyStore

_EMPLOYEE = "vera"
_TERMINAL = (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.BLOCKED, TaskStatus.REJECTED)
_MAX_TICKS = 300

# A decision whose data lives in the workspace, so the LLM's goals are self-contained + beat-ready.
_DECISION = (
    "Analyze the sales warehouse `warehouse.db` in your workspace (tables "
    "sales(region, quarter, revenue, units) and costs(region, quarter, cost)) and decide which region "
    "to invest in next quarter, with exact numbers and a written recommendation in findings.md."
)

_SALES = [
    ("A", "Q1", 1000, 100), ("A", "Q2", 1200, 110), ("A", "Q3", 1500, 130),
    ("B", "Q1", 800, 90), ("B", "Q2", 900, 95), ("B", "Q3", 1100, 105),
    ("C", "Q1", 600, 70), ("C", "Q2", 700, 72), ("C", "Q3", 650, 68),
]
_COSTS = [
    ("A", "Q1", 700), ("A", "Q2", 800), ("A", "Q3", 900),
    ("B", "Q1", 650), ("B", "Q2", 700), ("B", "Q3", 800),
    ("C", "Q1", 500), ("C", "Q2", 520), ("C", "Q3", 560),
]


def _seed_warehouse(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales (region TEXT, quarter TEXT, revenue INTEGER, units INTEGER)")
    conn.execute("CREATE TABLE costs (region TEXT, quarter TEXT, cost INTEGER)")
    conn.executemany("INSERT INTO sales VALUES (?, ?, ?, ?)", _SALES)
    conn.executemany("INSERT INTO costs VALUES (?, ?, ?)", _COSTS)
    conn.commit()
    conn.close()


def _report_path() -> Path:
    return Path(__file__).resolve().parent.parent / "reports" / "live-demo-report.md"


async def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    workdir = Path(__file__).resolve().parent.parent / ".horizon" / "live-demo"
    workdir.mkdir(parents=True, exist_ok=True)

    ledger = SqliteLedger.open(str(workdir / "ledger.db"))
    registry = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key,
        base_url=base,
        deployment=deployment,
        company_id="horizon-live",
        roles=registry,
        ledger=ledger,
        timeout_s=900.0,
    )
    materialized = factory.materialize(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))
    _seed_warehouse(materialized.working_dir / "warehouse.db")
    ledger.employees.create(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))

    chorus = Chorus.build(
        ledger=ledger,
        org_repo=str(workdir / "org"),
        memory_repo=str(workdir / "memory"),
        dream=dream,
        beat_runner_for=factory,
        landers=factory.landers,
        roles=default_roles(),
    )

    reporter = LoopReporter(title="Live demo — real LLM + a real Analyst beat")
    horizon = Horizon(
        goals=ChorusGoalStore(chorus),
        intake=ChorusIntakePort(chorus),
        outcomes=ChorusOutcomeFeed(chorus),
        reasoner=OpenAIChatSubstrate(name="azure", api_key=key, model=deployment, base_url=base),
        decisions=DecisionStore(workdir / "decisions.json"),
        strategy=StrategyStore(workdir / "strategy.json"),
        default_assignee=_EMPLOYEE,
        model=deployment,
        outcome_observer=reporter.observe,
    )

    # Part A — real LLM decomposition
    decision = Decision(id="dec_live", statement=_DECISION, owner=_EMPLOYEE)
    horizon.seed_decision(decision)
    print("decomposing (real LLM)...")
    goals = horizon.decompose(decision.id)
    reporter.record_decomposition(decision, goals)
    print(f"  -> {len(goals)} goals")
    for goal in goals:
        print(f"     [{goal.score:.2f}] {goal.title}")

    # Part B — submit the top goal + run a REAL beat; the DoD verdict closes the loop live
    horizon.start()
    top = max(goals, key=lambda g: g.score)
    task_id = horizon.submit_goal(top)
    reporter.record_submission(top, task_id, assignee=_EMPLOYEE)
    print(f"\nsubmitted top goal -> task {task_id} (assignee {_EMPLOYEE})")
    print("running the real kernel (Analyst beat + DoD verdict)...")

    last = ""
    for _ in range(_MAX_TICKS):
        await chorus.tick()
        await chorus.drain()
        task = ledger.tasks.get(task_id)
        assert task is not None
        if task.status.value != last:
            last = task.status.value
            print(f"  task {task_id}: {last}")
        if task.status in _TERMINAL:
            break

    dod = ledger.dod.get_for_task(task_id)
    verdict = dod.verdict if dod is not None else None
    print(f"\nfinal task status: {last}  |  dod verdict: {verdict}")

    after = horizon.goal_view(top.id)
    if after is not None:
        print(f"goal after loop: health={after.health} score={after.score:.2f}")

    report = reporter.render(horizon.state())
    report += (
        f"\n\n## Live execution\n\n- task `{task_id}` final status: **{last}**\n"
        f"- dod verdict: **{verdict}**\n"
        f"- verdicts folded by the listener: **{len(reporter.transitions)}**\n"
    )
    path = _report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(f"\nreport written to {path}")
    ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
