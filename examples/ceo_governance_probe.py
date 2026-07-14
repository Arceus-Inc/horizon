"""Fast, self-verifying live probe of the CEO governance seam — ONE beat, every action monitored.

Isolates the governance-tool path (no decompose, no analyst beats): builds a tiny Horizon over the
in-memory fakes, seeds one live decision + goals + two open proposals, wires ``HorizonGovernance`` as
the CEO employee's ``GovernancePort``, runs ONE real governance beat, and PRINTS + CHECKS every tool
call. Fails loudly (exit 1) if any governance tool errors, if the CEO never reads the tree, or if the
tree does not actually re-aim (strong approved, weak rejected).

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/ceo_governance_probe.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root -> the ``tests`` package

from chorus.events import Event, EventKind  # noqa: E402
from chorus.ledger import SqliteLedger  # noqa: E402
from chorus.outcomes import AgentReview  # noqa: E402
from chorus.roles import RoleRegistry, default_roles  # noqa: E402
from chorus.workforce import Employee  # noqa: E402
from chorus_employee.ceo import ceo_plugin  # noqa: E402
from chorus_harness import EmployeeHarnessFactory  # noqa: E402
from tests.fakes import FakeGoalStore, FakeIntakePort, FakeOutcomeFeed  # noqa: E402

from horizon import Horizon  # noqa: E402
from horizon.generation import CandidateGoal, DirectionBrief, ProposalStore  # noqa: E402
from horizon.governance import HorizonGovernance  # noqa: E402
from horizon.store import DecisionStore, StrategyStore  # noqa: E402

_INTENT = (
    "You are the CEO. Review the company's direction and adjudicate its open proposals, then record "
    "your decisions in directive.md.\n\n"
    "Use governance_read to see the decisions, their goals, and the open proposals — that tool is your "
    "only source of truth about the company; do not search the repository or read log/telemetry files. "
    "Approve each well-evidenced growth proposal with proposal_approve and reject each low-evidence one "
    "with proposal_reject (short reason). Reprioritise a goal with goal_set_priority (bands: low, "
    "medium, high) if warranted. Your actions are recorded automatically in governance-ledger.md.\n\n"
    "Your deliverable is directive.md — write it once: state your decision(s) up top; for EACH proposal "
    "you approved or rejected give its id and your one-line reason in the text; name the key risks with "
    "a guardrail each; and list the ranked next actions. That file is the finished work — do not "
    "re-verify by re-reading or searching."
)


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
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    workdir = Path(__file__).resolve().parent.parent / ".horizon" / "ceo-probe"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    horizon = Horizon(
        goals=FakeGoalStore(), intake=FakeIntakePort(), outcomes=FakeOutcomeFeed(), reasoner=None,
        decisions=DecisionStore(workdir / "d.json"), strategy=StrategyStore(workdir / "s.json"),
        proposals=ProposalStore(workdir / "p.json"), default_assignee="vera",
    )
    # Two OPEN proposals for the CEO to adjudicate — nothing pre-decided, so RECENTLY DECIDED starts
    # empty and, after the beat, shows EXACTLY the CEO's two actions (no phantom to confuse a reviewer).
    strong = horizon.reconcile([_brief("Concentrate investment on Region A", conf=0.86, evidence=3)])[0]
    weak = horizon.reconcile([_brief("Rebrand the company logo next quarter", conf=0.5, evidence=1)])[0]

    gov = HorizonGovernance(horizon)
    # A unique company id per run: the CEO's worktree lives under .chorus/work/{company_id}/ (NOT the
    # .horizon workdir above), so a fixed id would reuse a completed worktree and the beat would
    # short-circuit with zero tool calls. Fresh id ⇒ a genuinely fresh beat every run.
    company_id = f"ceo-probe-{datetime.now(UTC).strftime('%m%d-%H%M%S')}"
    ledger = SqliteLedger.open(str(workdir / "ledger.db"))
    ledger.employees.create(Employee(id="ceo", name="Casey (CEO)", role="ceo"))
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=dep, company_id=company_id,
        roles=RoleRegistry.from_plugins(default_roles()), ledger=ledger, governance=gov,
        timeout_s=600.0,
    )
    mat = factory.materialize(Employee(id="ceo", name="Casey (CEO)", role="ceo"))

    tool_calls: list[str] = []
    tool_errors: list[tuple[str, str]] = []
    tool_results: list[tuple[str, bool]] = []  # (tool, is_error) in call order

    def obs(ev: Event) -> None:
        p = ev.payload
        if ev.kind is EventKind.RUN_TOOL_USE:
            tool_calls.append(str(p.get("tool")))
            print(f"  [tool ->] {p.get('tool')}  {str(p.get('input'))[:120]}")
        elif ev.kind is EventKind.RUN_TOOL_RESULT:
            err = bool(p.get("is_error"))
            content = str(p.get("content_preview"))[:160]
            print(f"  [tool <-] {p.get('tool')}{' (ERROR)' if err else ''}  {content}")
            tool_results.append((str(p.get("tool")), err))
            if err:
                tool_errors.append((str(p.get("tool")), content))
        elif ev.kind is EventKind.RUN_TEXT:
            text = str(p.get("text", "")).strip()
            if text:
                print(f"  [think]   {text[:160]}")

    print(f"seeded : strong={strong.id}  weak={weak.id}")
    print(f"tools  : {mat.config.tools}")
    print("intent : governance beat\n")
    # The CEO's OWN DoD rubric drives dream's in-beat evaluator (spec 16) — the real scheduler threads
    # this into run_task; a direct call must too, or the evaluator falls back to a generic bar that
    # mis-reads the post-adjudication tree ("no open proposals ⇒ nothing was done").
    verifier = ceo_plugin().dod_generator(_INTENT)
    rubric = verifier.spec.rubric if isinstance(verifier.spec, AgentReview) else ""
    outcome = await mat.runner.run_task(
        task_id="probe-1", intent=_INTENT, run_id="run-probe-1", rubric=rubric, observer=obs
    )

    props = {p.id: p.status for p in horizon.list_proposals(status=None)}
    gov_names = {"governance_read", "proposal_approve", "proposal_reject", "goal_set_priority", "goal_archive"}
    gov_calls = [t for t in tool_calls if t in gov_names]
    # Three kinds of tool error are very different:
    #  - GUARDRAIL refusals ("tool-not-in-role-manifest"): dream's read-only planner/evaluator phases
    #    correctly refusing a MUTATION during planning. Recoverable by design — the generator phase does
    #    the real work — and it happens for every role, not just the CEO. Not a bug.
    #  - RECOVERED refusals ("refused: …" the tool declined with a hint, and a LATER call of the SAME
    #    tool succeeded): the error contract working — a model miscall (wrong id, bad vocab) that the
    #    seam turned into a corrective hint. The end-state checks below stay authoritative.
    #  - HARD errors: a port exception, an unknown tool, or a refusal the agent never recovered from.
    #    THOSE are real defects in the seam and must fail the probe.
    def _is_guardrail(msg: str) -> bool:
        return "tool-not-in-role-manifest" in msg

    def _recovered(tool: str, msg: str) -> bool:
        if not msg.startswith("refused:"):
            return False
        last_err = max(i for i, (t, e) in enumerate(tool_results) if t == tool and e)
        return any(t == tool and not e for t, e in tool_results[last_err + 1 :])

    guardrail = [(t, c) for t, c in tool_errors if _is_guardrail(c)]
    recovered = [(t, c) for t, c in tool_errors if not _is_guardrail(c) and _recovered(t, c)]
    hard_errors = [
        (t, c) for t, c in tool_errors if not _is_guardrail(c) and not _recovered(t, c)
    ]
    gov_hard = [(t, c) for t, c in hard_errors if t in gov_names]

    print("\n=== VERIFY ===")
    print(f"passed              = {outcome.passed}")
    print(f"summary             = {getattr(outcome, 'summary', '')}")
    print(f"tool calls (all)    = {tool_calls}")
    print(f"governance calls    = {gov_calls}")
    print(f"proposal statuses   = {props}")
    print(f"directive written   = {(mat.working_dir / 'directive.md').is_file()}")
    print(f"guardrail refusals  = {len(guardrail)} (read-only planning phases; recovered)")
    print(f"recovered refusals  = {len(recovered)} (tool declined with a hint; agent recovered)")
    print(f"HARD tool errors    = {len(hard_errors)}")

    failures: list[str] = []
    if gov_hard:
        failures.append(f"{len(gov_hard)} HARD governance tool error(s): {gov_hard}")
    if "governance_read" not in gov_calls:
        failures.append("CEO never called governance_read")
    if props.get(strong.id) != "approved":
        failures.append(f"strong proposal not approved (status={props.get(strong.id)})")
    if props.get(weak.id) != "rejected":
        failures.append(f"weak proposal not rejected (status={props.get(weak.id)})")
    if not (mat.working_dir / "directive.md").is_file():
        failures.append("no directive.md written")
    if not outcome.passed:
        failures.append(f"beat did not pass its DoD: {getattr(outcome, 'summary', '')}")

    if failures:
        print("\nRESULT: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nRESULT: PASS — governance seam clean end to end")
    print(f"  (adjudication correct, DoD passed, {len(guardrail)} recovered planning-phase guardrail(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
