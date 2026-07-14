"""Full-spine live experiment — one run across all four repos.

The spine: horizon decides (Decision → Goals) → chorus intake (bridge, idempotent) → real
employee beats on the heartbeat (dream harness) → landed outcomes flow back (OutcomeFeed) →
goal health/score move and the chorus task is reprioritised → the CEO employee re-aims the
tree through ``GovernancePort`` (approve strong / reject weak / directive.md).

Every pairwise seam has its own probe; this is the ONE run that walks the whole loop and
self-verifies each hop. Writes ``reports/full-spine/data.json``. Exit 1 on any failed check;
skips cleanly (exit 0) when AZURE_OPENAI_* are unset.

    uv run python examples/full_spine_e2e.py

Deliberately out of scope (covered elsewhere): the lattice consolidation gate needs >=5
clustered beats (chorus 5beat probe) and the reviewed_build DoD needs a reviewer employee
(chorus reviewed-build e2e) — spine tasks carry an explicit command DoD instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import dream  # noqa: E402
from chorus.events import Event, EventKind  # noqa: E402
from chorus.facade import Chorus  # noqa: E402
from chorus.memory import EpisodicStore  # noqa: E402
from chorus.outcomes import AgentReview, Verifier  # noqa: E402
from chorus.roles import RoleRegistry, default_roles  # noqa: E402
from chorus.roles._plugin import RolePlugin  # noqa: E402
from chorus_employee import default_landers  # noqa: E402
from chorus_employee.ceo import ceo_plugin  # noqa: E402
from chorus_harness import EmployeeHarnessFactory  # noqa: E402

from examples.chorus_bridge import (  # noqa: E402
    ChorusGoalStore,
    ChorusIntakePort,
    ChorusOutcomeFeed,
)
from horizon import Horizon  # noqa: E402
from horizon.generation import CandidateGoal, DirectionBrief, ProposalStore  # noqa: E402
from horizon.governance import HorizonGovernance  # noqa: E402
from horizon.model import Decision  # noqa: E402
from horizon.model._strategy import StrategyRecord  # noqa: E402
from horizon.ports import GoalNode  # noqa: E402
from horizon.store import DecisionStore, StrategyStore  # noqa: E402

_BEAT_TIMEOUT_S = float(os.environ.get("SPINE_BEAT_TIMEOUT_S", "180"))
_MAX_TICKS = int(os.environ.get("SPINE_MAX_TICKS", "6"))

_GOALS: tuple[tuple[str, str, float, str], ...] = (
    # (goal_id, title/intent, strategy score, expected intake priority)
    (
        "goal_spine_api",
        "Create package src/noteapi/ with slug.py defining slugify(text: str) -> str "
        "(lowercase, hyphens, strip punctuation) and tests/test_slug.py with two pytests. "
        "Make the tests pass.",
        0.9,
        "high",
    ),
    (
        "goal_spine_docs",
        "Write docs/USAGE.md documenting the noteapi package: what slugify does, one "
        "example invocation, and how to run the tests. Keep it under 40 lines.",
        0.55,
        "medium",
    ),
)

_CEO_INTENT = (
    "You are the CEO. Review the company's direction and adjudicate its open proposals, then "
    "record your decisions in directive.md.\n\n"
    "Use governance_read to see the decisions, their goals, and the open proposals — that tool "
    "is your only source of truth about the company. Approve each well-evidenced proposal with "
    "proposal_approve and reject each low-evidence one with proposal_reject (short reason). "
    "Reprioritise a goal with goal_set_priority (bands: low, medium, high) if warranted.\n\n"
    "Your deliverable is directive.md — write it once: decisions up top; for EACH proposal you "
    "adjudicated give its id and a one-line reason; name the key risks with a guardrail each; "
    "list the ranked next actions. That file is the finished work."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _seed(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# noteapi seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-qm", "init"],
        check=True,
        capture_output=True,
    )


def _short_beat_plugins(timeout_s: float) -> list[RolePlugin]:
    plugins: list[RolePlugin] = []
    for plugin in default_roles():
        if plugin.name != "backend_engineer":
            plugins.append(plugin)
            continue
        manifest = replace(plugin.manifest, beat_timeout_s=timeout_s, lease_ttl_s=timeout_s + 90.0)
        plugins.append(
            RolePlugin(
                name=plugin.name,
                manifest=manifest,
                dod_generator=plugin.dod_generator,
                outcome_kind=plugin.outcome_kind,
                declared_routines=plugin.declared_routines,
                replace=True,
            )
        )
    return plugins


def _brief(recommendation: str, *, conf: float, evidence: int) -> DirectionBrief:
    return DirectionBrief(
        candidate_id="c",
        recommendation=recommendation,
        rationale="grounded in the numbers",
        confidence=conf,
        risks=["only three quarters of data"],
        candidate_goals=[
            CandidateGoal(
                title=f"Goal — {recommendation[:32]}",
                metric="incremental profit",
                target="+10% QoQ",
                rationale="measurable",
                score=0.8,
            )
        ],
        evidence_refs=[f"ev_{i}" for i in range(evidence)],
    )


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    stamp = datetime.now(UTC).strftime("%m%d-%H%M%S")
    company_id = f"spine-{stamp}"
    base = Path(tempfile.mkdtemp(prefix="full-spine-"))
    seed = base / "source"
    _seed(seed)

    plugins = _short_beat_plugins(_BEAT_TIMEOUT_S)
    registry = RoleRegistry.from_plugins(plugins)
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base_url, deployment=deployment,
        company_id=company_id, roles=registry, seed=seed, timeout_s=_BEAT_TIMEOUT_S,
    )
    org = Chorus.build(
        db_path=str(base / "ledger.db"),
        org_repo=str(base / "org"),
        memory_repo=str(factory.company_root / "memory"),
        dream=dream,
        beat_runner_for=factory,
        landers=default_landers(factory.company_root),
        roles=plugins,
        company_id=company_id,
    )
    ledger = org._ledger  # composition root: the one place allowed to reach the concretes

    # -- horizon over the real bridge ------------------------------------------
    decisions = DecisionStore(base / "decisions.json")
    strategy = StrategyStore(base / "strategy.json")
    horizon = Horizon(
        goals=ChorusGoalStore(org),
        intake=ChorusIntakePort(org),
        outcomes=ChorusOutcomeFeed(org),
        reasoner=None,
        decisions=decisions,
        strategy=strategy,
        proposals=ProposalStore(base / "proposals.json"),
        default_assignee="bex",
    )

    bex = org.hire(name="Bex", role="backend_engineer")
    _log(f"company_root : {factory.company_root}")
    _log(f"hired        : {bex.id} (backend_engineer)")

    # Decision → goals → strategy scores (the decomposer's LLM leg has its own live test;
    # the spine hand-seeds its output so every downstream hop is deterministic to check).
    decisions.put(
        Decision(id="dec_spine", statement="Ship the noteapi slice", goal_ids=[g for g, *_ in _GOALS])
    )
    goal_store = ChorusGoalStore(org)
    for goal_id, title, score, _prio in _GOALS:
        goal_store.upsert(GoalNode(id=goal_id, title=title, level="goal"))
        strategy.put(StrategyRecord(goal_id=goal_id, score=score, decision_id="dec_spine"))

    stop_listener = horizon.start()  # outcome feed → health/score → re-priority

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")

    # -- intake: horizon → chorus ----------------------------------------------
    task_ids: dict[str, str] = {}
    for goal_id, _title, _score, want_prio in _GOALS:
        view = horizon.goal_view(goal_id)
        task_id = horizon.submit_goal(view)
        task_ids[goal_id] = task_id
        task = ledger.tasks.get(task_id)
        check(
            f"intake {goal_id} → task at {want_prio}",
            task is not None
            and task.goal_id == goal_id
            and task.priority.value == want_prio
            and task.origin_kind.value == "horizon_intake",
            f"task={task_id}",
        )
        check(
            f"intake {goal_id} idempotent",
            horizon.submit_goal(view) == task_id,
        )
        # Spine scope: explicit command DoD (reviewed_build needs a reviewer — covered elsewhere).
        ledger.dod.create(task_id, Verifier.command("python -m pytest -q", artifact_class="pr"))

    # -- beats: the heartbeat runs the org --------------------------------------
    outcome_events: list[Event] = []
    org._event_bus.subscribe(
        lambda ev: outcome_events.append(ev) if ev.kind is EventKind.RUN_EVALUATED else None
    )
    _log(f"\nheartbeat: up to {_MAX_TICKS} ticks x {_BEAT_TIMEOUT_S}s beats")
    for tick in range(_MAX_TICKS):
        await org.tick()
        await org.drain()
        statuses = {
            g: (t.status.value if (t := ledger.tasks.get(tid)) is not None else "?")
            for g, tid in task_ids.items()
        }
        _log(f"  tick {tick + 1}: {statuses}")
        if all(s in {"done", "failed", "cancelled", "rejected"} for s in statuses.values()):
            break

    for goal_id, task_id in task_ids.items():
        task = ledger.tasks.get(task_id)
        check(f"beat {goal_id} done", task is not None and task.status.value == "done",
              f"status={task.status.value if task else '?'}")

    store = EpisodicStore(factory.company_root / "memory")
    episodic = store.count()
    check("episodic records captured", episodic >= len(_GOALS), f"count={episodic}")
    check("outcome events on the bus", len(outcome_events) >= len(_GOALS),
          f"run_evaluated={len(outcome_events)}")

    # -- feedback: outcomes moved the strategy layer ----------------------------
    api_after = horizon.goal_view("goal_spine_api")
    check("goal health moved on_track", api_after.health == "on_track",
          f"health={api_after.health}")
    check("goal score decayed after landing", api_after.score < 0.9,
          f"score={api_after.score}")
    api_task = ledger.tasks.get(task_ids["goal_spine_api"])
    api_prio = api_task.priority.value if api_task is not None else "?"
    check("chorus task reprioritised by feedback", api_prio not in {"high", "?"},
          f"priority={api_prio}")

    # -- governance: the CEO re-aims through the port ---------------------------
    strong = horizon.reconcile([_brief("Concentrate investment on Region A", conf=0.86, evidence=3)])[0]
    weak = horizon.reconcile([_brief("Rebrand the company logo next quarter", conf=0.5, evidence=1)])[0]
    gov = HorizonGovernance(horizon)
    ceo_factory = EmployeeHarnessFactory(
        api_key=key, base_url=base_url, deployment=deployment,
        company_id=company_id, roles=registry, ledger=ledger, governance=gov, timeout_s=600.0,
    )
    casey = org.hire(name="Casey", role="ceo")
    mat = ceo_factory.materialize(casey)
    verifier = ceo_plugin().dod_generator(_CEO_INTENT)
    rubric = verifier.spec.rubric if isinstance(verifier.spec, AgentReview) else ""
    _log("\nCEO governance beat…")
    outcome = await mat.runner.run_task(
        task_id="spine-gov", intent=_CEO_INTENT, run_id=f"run-gov-{stamp}", rubric=rubric
    )

    props = {p.id: p.status for p in horizon.list_proposals(status=None)}
    check("CEO approved the strong proposal", props.get(strong.id) == "approved",
          f"status={props.get(strong.id)}")
    check("CEO rejected the weak proposal", props.get(weak.id) == "rejected",
          f"status={props.get(weak.id)}")
    check("CEO wrote directive.md", (mat.working_dir / "directive.md").is_file())
    check("CEO beat passed its DoD", bool(outcome.passed),
          str(getattr(outcome, "summary", "")))
    decided = gov.read_direction().decided
    check("adjudications visible in decided[]", len(decided) >= 2, f"decided={len(decided)}")

    stop_listener()

    # -- report ------------------------------------------------------------------
    passed = sum(1 for _, ok, _ in checks if ok)
    report = {
        "ran_at": stamp,
        "company_id": company_id,
        "deployment": deployment,
        "beat_timeout_s": _BEAT_TIMEOUT_S,
        "episodic_records": episodic,
        "outcome_events": len(outcome_events),
        "proposal_statuses": props,
        "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
        "passed": passed,
        "total": len(checks),
        "all_pass": passed == len(checks),
    }
    out = _REPO_ROOT / "reports" / "full-spine" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log(f"\nreport → {out}")
    _log(f"RESULT: {'PASS' if report['all_pass'] else 'FAIL'} ({passed}/{len(checks)})")
    shutil.rmtree(base, ignore_errors=True)
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
