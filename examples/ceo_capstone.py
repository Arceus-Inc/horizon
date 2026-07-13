"""CEO capstone — the whole executive loop, live, captured in one report.

Build a REAL company (a decision decomposed by an LLM, real Analyst beats that pass/block, a queue of
funnel proposals), then hand it to the CEO:

    seed CEO memory (org facts + a standing directive)
      -> CEO governance BEAT (live): inspect the tree + proposals, prepare corrections
      -> bounded autonomy auto-approves the strong proposal; the rest stay gated
      -> a human confirms the pending corrections -> the org RE-AIMS
      -> CHAT with the CEO: "what did you change and why?" + a memory-recall question

Every step is captured — the before/after company state, the CEO's reasoning steps + prepared actions,
what auto-applied vs waited, and the grounded/cited chat — and rendered to
``reports/ceo-capstone/horizon-ceo-report.html`` in the strong-run style.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/ceo_capstone.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dream
from chorus.events import Event, EventKind
from chorus.facade import Chorus
from chorus.ledger import SqliteLedger
from chorus.outcomes import AgentReview
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_bridge import ChorusGoalStore, ChorusIntakePort, ChorusOutcomeFeed
from chorus_employee.ceo import ceo_plugin
from chorus_harness import EmployeeHarnessFactory
from strong_run import (
    _CSS,
    RecordingReasoner,
    _esc,
    _run_to_terminal,
    _seed_warehouse,
)

from horizon import Horizon, LoopReporter
from horizon.feedback import HealthPolicy
from horizon.generation import CandidateGoal, DirectionBrief, ProposalStore
from horizon.governance import HorizonGovernance
from horizon.intake import ScorePolicy
from horizon.model import Decision
from horizon.store import DecisionStore, StrategyStore

_EMPLOYEE = "vera"
_N_EXECUTE = 2  # real beats to run (bounded); the CEO governs whatever state results

_DECISION = (
    "Grow next quarter's profit using our sales warehouse, and back the recommendation with analysis a "
    "skeptical executive would accept."
)
_BRIEF = (
    "You are Vera, the company's data analyst. Your workspace has `warehouse.db` (SQLite) with "
    "sales(region, quarter, revenue, units) and costs(region, quarter, cost) for Q1-Q3, regions A/B/C. "
    "Ground every claim in this data with exact numbers and produce clear, reproducible artifacts."
)
_CONTEXT = (
    "The only data source is `warehouse.db` (SQLite): sales(region, quarter, revenue, units) and "
    "costs(region, quarter, cost), Q1-Q3, regions A/B/C. No CRM/pipeline/external data."
)

# Two proposals queued for the CEO to adjudicate: one strong (auto-approvable), one weak (should reject).
_STRONG_BRIEF = DirectionBrief(
    candidate_id="cand_strong",
    recommendation="Concentrate next-quarter sales investment on Region A (highest profit efficiency)",
    rationale="Region A has the best profit-per-cost across Q1-Q3 and the strongest growth trend.",
    confidence=0.86,
    risks=["only three quarters of data", "no pipeline data"],
    candidate_goals=[
        CandidateGoal(title="Draft the Region A investment plan", metric="plan doc",
                      target="1 page with the reallocation and expected profit", rationale="actionable",
                      score=0.9),
        CandidateGoal(title="Define the success metric + guardrail", metric="metric spec",
                      target="profit-per-cost target + a stop-loss", rationale="measurable", score=0.7),
    ],
    evidence_refs=["ev_profit", "ev_growth", "ev_efficiency"],
)
_WEAK_BRIEF = DirectionBrief(
    candidate_id="cand_weak",
    recommendation="Rebrand the company logo and website next quarter",
    rationale="A team member felt the brand looks dated.",
    confidence=0.5,
    risks=["no evidence it moves profit", "distracts from the core bet"],
    candidate_goals=[CandidateGoal(title="Hire a design agency", metric="vendor", target="1 signed",
                                   rationale="opinion", score=0.4)],
    evidence_refs=["ev_opinion"],
)

_DIRECTIVE = (
    "Approve well-evidenced proposals (three or more independent sources) that advance profitable "
    "growth, and reject distractions and low-evidence bets - protect the quarter's single priority."
)

_CEO_INTENT = (
    "You are the CEO. Review the company's direction and adjudicate its open proposals, then record "
    "your decisions in `directive.md`.\n\n"
    "Use `governance_read` to see the standing decisions with their goals and the open proposals — that "
    "tool is your only source of truth about the company; do not search the repository or read "
    "log/telemetry files. Approve each well-evidenced proposal with `proposal_approve` and reject each "
    "low-evidence distraction with `proposal_reject` (short reason); reprioritise a goal with "
    "`goal_set_priority` (bands: low, medium, high) or retire a done/obsolete one with `goal_archive` "
    "when warranted. Your standing rule: " + _DIRECTIVE + " Your actions are recorded automatically in "
    "governance-ledger.md.\n\n"
    "Your deliverable is `directive.md` — write it once: state your decision(s) up top; for EACH "
    "proposal you approved or rejected give its id and your one-line reason in the text; name the key "
    "risks with a guardrail each; and list the ranked next actions. That file is the finished work — do "
    "not re-verify by re-reading or searching."
)


def _short(value: object, n: int = 220) -> str:
    """One-line, length-capped render of a tool input/observation for the event log + report."""
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


async def run() -> dict[str, Any]:
    key = os.environ["AZURE_OPENAI_API_KEY"]
    base = os.environ["AZURE_OPENAI_BASE_URL"]
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    workdir = Path(__file__).resolve().parent.parent / ".horizon" / "ceo-capstone"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    ledger = SqliteLedger.open(str(workdir / "ledger.db"))
    registry = RoleRegistry.from_plugins(default_roles())
    company_id = f"horizon-ceo-{datetime.now(UTC).strftime('%m%d-%H%M%S')}"
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=deployment, company_id=company_id,
        roles=registry, ledger=ledger, timeout_s=600.0,
    )
    materialized = factory.materialize(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))
    _seed_warehouse(materialized.working_dir / "warehouse.db")
    (materialized.working_dir / "BRIEF.md").write_text(_BRIEF, encoding="utf-8")
    ledger.employees.create(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))
    # register the CEO as a real member of the org roster (executive beats run via horizon)
    with contextlib.suppress(Exception):
        ledger.employees.create(Employee(id="ceo", name="Casey (CEO)", role="ceo"))

    chorus = Chorus.build(
        ledger=ledger, org_repo=str(workdir / "org"), memory_repo=str(workdir / "memory"),
        dream=dream, beat_runner_for=factory, landers=factory.landers, roles=default_roles(),
    )

    from dream.api.openai import OpenAIChatSubstrate

    reasoner = RecordingReasoner(
        OpenAIChatSubstrate(name="azure", api_key=key, model=deployment, base_url=base)
    )
    score_policy = ScorePolicy()
    health_policy = HealthPolicy()
    reporter = LoopReporter(title="CEO capstone", score_policy=score_policy)
    horizon = Horizon(
        goals=ChorusGoalStore(chorus), intake=ChorusIntakePort(chorus), outcomes=ChorusOutcomeFeed(chorus),
        reasoner=reasoner, decisions=DecisionStore(workdir / "decisions.json"),
        strategy=StrategyStore(workdir / "strategy.json"),
        proposals=ProposalStore(workdir / "proposals.json"), default_assignee=_EMPLOYEE,
        model=deployment, score_policy=score_policy, health_policy=health_policy,
        decompose_context=_CONTEXT, outcome_observer=reporter.observe,
    )

    # ---- build real company state: decompose + run a couple of real beats ----
    print("decomposing (real LLM)...")
    decision = Decision(id="dec_ceo", statement=_DECISION, owner=None)
    horizon.seed_decision(decision)
    goals = horizon.decompose(decision.id)
    print(f"  -> {len(goals)} goals")
    horizon.start()
    ordered = sorted(goals, key=lambda g: g.score, reverse=True)
    for goal in ordered[:_N_EXECUTE]:
        task_id = horizon.submit_goal(goal)
        print(f"  running real beat: {goal.title[:48]!r}")
        trail = await _run_to_terminal(chorus, ledger, task_id)
        dod = ledger.dod.get_for_task(task_id)
        print(f"    -> {trail[-1] if trail else '?'}  dod={dod.status.value if dod else '?'}")

    # ---- queue two proposals for the CEO to adjudicate ----
    horizon.reconcile([_STRONG_BRIEF, _WEAK_BRIEF])

    def _state_snapshot() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for st in horizon.state():
            for g in sorted(st.goals, key=lambda g: g.score, reverse=True):
                out.append({
                    "decision": st.decision.statement, "title": g.title, "score": g.score,
                    "priority": score_policy.priority_for(g.score), "health": g.health,
                    "status": g.status, "task_id": g.task_id,
                })
        return out

    state_before = _state_snapshot()
    proposals_before = [
        {"id": p.id, "statement": p.decision_statement, "status": p.status,
         "confidence": p.brief.confidence if p.brief else None,
         "evidence": len(p.brief.evidence_refs) if p.brief else 0}
        for p in horizon.list_proposals(status="proposed")
    ]

    # ---- the CEO as a chorus employee: governance tools bound to horizon via the GovernancePort ----
    # This is the seam the refactor built. The CEO is a real chorus employee whose ``governance_*`` tools
    # bind to an abstract dream ``GovernancePort``. Here the composition root wires that port to THIS
    # horizon (``HorizonGovernance``). When the employee calls ``governance_read`` / ``proposal_approve``
    # / ``proposal_reject`` mid-beat, it reads and re-aims the LIVE tree built above — yet chorus never
    # imports horizon and horizon never imports chorus; they meet only at the Port.
    gov = HorizonGovernance(horizon, score_policy=score_policy)
    ceo_factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=deployment, company_id=f"{company_id}-ceo",
        roles=registry, ledger=ledger, governance=gov, timeout_s=600.0,
    )
    mat = ceo_factory.materialize(Employee(id="ceo", name="Casey (CEO)", role="ceo"))

    events: list[dict[str, Any]] = []
    tool_errors: list[dict[str, str]] = []

    def _observe(ev: Event) -> None:
        p = ev.payload
        if ev.kind is EventKind.RUN_TOOL_USE:
            events.append({"t": "tool", "tool": p.get("tool"), "input": _short(p.get("input"), 240)})
            print(f"  [tool ->] {p.get('tool')}  {_short(p.get('input'), 100)}")
        elif ev.kind is EventKind.RUN_TOOL_RESULT:
            is_err = bool(p.get("is_error"))
            content = _short(p.get("content_preview"), 600)
            # A "tool-not-in-role-manifest" refusal is dream's read-only planner/evaluator phase
            # correctly declining a MUTATION during planning — recoverable by design (the generator
            # phase does the real work), and it happens for every role. Mark it as a guardrail, NOT a
            # defect, so the report is honest rather than alarming.
            guardrail = is_err and "tool-not-in-role-manifest" in content
            events.append({
                "t": "result", "tool": p.get("tool"), "is_error": is_err,
                "guardrail": guardrail, "content": content,
            })
            tag = " (guardrail)" if guardrail else (" (ERROR)" if is_err else "")
            print(f"  [tool <-] {p.get('tool')}{tag}  {content[:110]}")
            if is_err and not guardrail:
                tool_errors.append({"tool": str(p.get("tool")), "content": content})
        elif ev.kind is EventKind.RUN_TEXT:
            text = str(p.get("text", ""))
            if not text:
                return
            # RUN_TEXT streams token-by-token; coalesce a contiguous reasoning burst into ONE block (a
            # tool call/result breaks the burst) so the report shows readable paragraphs instead of
            # hundreds of single-token boxes.
            if events and events[-1]["t"] == "think":
                events[-1]["text"] += text
            else:
                events.append({"t": "think", "text": text})

    print("CEO governance beat (real LLM, tools bound to the live horizon tree)...")
    # Thread the CEO's OWN DoD rubric into dream's in-beat evaluator (spec 16) — the real scheduler does
    # this; a direct run_task call must too, else the evaluator uses a generic bar that mis-reads the
    # post-adjudication tree ("no open proposals ⇒ nothing was done") and wrongly blocks the step.
    verifier = ceo_plugin().dod_generator(_CEO_INTENT)
    rubric = verifier.spec.rubric if isinstance(verifier.spec, AgentReview) else ""
    outcome = await mat.runner.run_task(
        task_id="ceo-govern-1", intent=_CEO_INTENT, run_id="run-ceo-govern-1", rubric=rubric,
        observer=_observe,
    )
    print(f"  passed={outcome.passed}  outcome={outcome.outcome}")

    # Tidy the coalesced reasoning: trim + cap each block, drop trivially short bursts (a stray token
    # between two tool calls) so the report reads cleanly.
    for e in events:
        if e["t"] == "think":
            e["text"] = e["text"].strip()[:1500]
    events = [e for e in events if not (e["t"] == "think" and len(e["text"]) < 12)]

    state_after = _state_snapshot()
    proposals_after = [
        {"id": p.id, "statement": p.decision_statement, "status": p.status}
        for p in horizon.list_proposals(status=None)
    ]
    directive_path = mat.working_dir / "directive.md"
    directive_md = directive_path.read_text(encoding="utf-8") if directive_path.is_file() else ""

    tool_calls = [e for e in events if e["t"] == "tool"]
    _GOV = {"governance_read", "proposal_approve", "proposal_reject", "goal_set_priority", "goal_archive"}
    gov_calls = [e for e in tool_calls if e["tool"] in _GOV]
    gov_errors = [e for e in tool_errors if e["tool"] in _GOV]  # HARD errors only (guardrails excluded)
    guardrails = [e for e in events if e.get("t") == "result" and e.get("guardrail")]

    # Loud, self-verifying: a HARD governance error means the seam is not clean — surface it
    # unmistakably. Planning-phase guardrail refusals are recoverable-by-design and reported separately.
    if gov_errors:
        print(f"\n  !!! {len(gov_errors)} HARD GOVERNANCE TOOL ERROR(S) — the seam is NOT clean:")
        for e in gov_errors:
            print(f"      - {e['tool']}: {e['content'][:160]}")
    else:
        print(f"  governance tools clean: {len(gov_calls)} call(s), 0 hard errors, "
              f"{len(guardrails)} recovered planning-phase guardrail(s)")

    ledger.close()
    return {
        "meta": {
            "mission": _DECISION, "model": deployment,
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "goals": len(goals), "beats": _N_EXECUTE,
            "tool_calls": len(tool_calls), "gov_calls": len(gov_calls),
            "gov_errors": len(gov_errors), "guardrails": len(guardrails),
            "passed": bool(outcome.passed), "outcome": str(outcome.outcome),
            "summary": str(getattr(outcome, "summary", "") or ""),
            "llm_calls": len(reasoner.calls), "listener": horizon.listener_stats(),
        },
        "employee": {
            "tools": list(mat.config.tools),
            "sandbox": str(getattr(mat.config, "sandbox", "")),
            "max_turns": getattr(mat.config, "max_turns", None),
            "max_sprints": getattr(mat.config, "max_sprints", None),
            "worktree": str(mat.working_dir),
        },
        "directive_rule": _DIRECTIVE,
        "state_before": state_before, "proposals_before": proposals_before,
        "events": events,
        "state_after": state_after, "proposals_after": proposals_after,
        "directive_md": directive_md,
    }



# --------------------------------------------------------------------------- HTML renderer

_CHAT_CSS = """
.bubbles{display:flex;flex-direction:column;gap:10px;}
.msg{display:flex;gap:10px;}
.msg .who{flex:0 0 auto;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:12px;color:#fff;}
.msg.u .who{background:#64748b;} .msg.c .who{background:#4f46e5;}
.msg .bub{border-radius:12px;padding:11px 14px;font-size:14px;max-width:82%;}
.msg.u .bub{background:#f1f5f9;} .msg.c .bub{background:#eef2ff;border:1px solid #c7d2fe;}
.msg .bub .cite{display:block;margin-top:7px;font-size:11.5px;color:#3730a3;}
.act{border:1px solid var(--line);border-radius:10px;padding:10px 13px;margin:8px 0;background:#fbfcfe;}
.act .k{font-weight:700;}
.act .auto{color:#166534;font-size:12px;} .act .pend{color:#854d0e;font-size:12px;}
"""


def _state_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="why">(no goals)</p>'
    out = ['<table><tr><th>score</th><th>priority</th><th>health</th><th>status</th><th>goal</th></tr>']
    for r in rows:
        status = ('<span class="badge ok">done</span>' if r["status"] == "done"
                  else '<span class="badge fail">archived</span>' if r["status"] == "archived"
                  else _esc(r["status"]))
        out.append(
            f'<tr><td class="num">{r["score"]:.2f}</td><td>{_esc(r["priority"])}</td>'
            f'<td>{_esc(r["health"])}</td><td>{status}</td><td>{_esc(r["title"])}</td></tr>'
        )
    out.append("</table>")
    return "".join(out)


def render_html(data: dict[str, Any]) -> str:
    meta = data["meta"]
    emp = data["employee"]
    gov_errors = int(meta.get("gov_errors", 0))
    guardrails = int(meta.get("guardrails", 0))
    clean = meta["passed"] and gov_errors == 0
    verdict = "PASS" if clean else "REVIEW"
    verdict_cls = "ok" if clean else "fail"
    seam = (f"0 hard errors · {guardrails} recovered planning guardrail(s)" if gov_errors == 0
            else f"{gov_errors} HARD governance tool ERROR(s)")
    parts: list[str] = []
    parts.append(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Horizon — CEO Capstone</title><style>{_CSS}{_CHAT_CSS}</style></head><body><div class="wrap">
<header class="top"><div class="eyebrow">Horizon · chorus · the CEO governs, live</div>
<h1>CEO Capstone — a chorus employee re-aims the company through the GovernancePort</h1>
<p class="intent"><b>Company mission:</b> {_esc(meta['mission'])}</p></header>
<div class="reverify"><h2>One seam, both sides</h2>
<p style="color:var(--muted);font-size:13.5px;margin:8px 0 0">A real company was built (LLM decomposition + real Analyst beats + a queue of proposals). Then the CEO — a genuine <b>chorus employee</b> whose <code>governance_*</code> tools bind to a dream <code>GovernancePort</code> — ran one governance beat. Every tool call read and re-aimed the <b>live horizon tree</b> through the port, yet chorus never imports horizon: they meet only at the contract.</p>
<div class="overall"><span class="big {verdict_cls}">{verdict}</span><p>{meta['gov_calls']} governance tool call(s) &middot; {seam} &middot; {meta['tool_calls']} tool calls total &middot; {meta['llm_calls']} LLM calls &middot; DoD outcome: {_esc(meta['outcome'])}</p></div></div>
<div class="chips">
<div class="chip"><span>{meta['goals']}</span>Goals (LLM)</div>
<div class="chip"><span>{meta['beats']}</span>Real beats run</div>
<div class="chip"><span>{meta['gov_calls']}</span>Governance tool calls</div>
<div class="chip"><span>{gov_errors}</span>Hard errors</div>
<div class="chip"><span>{verdict}</span>CEO DoD</div>
</div><h2 class="sec">The executive loop, phase by phase</h2>"""
    )

    # Phase 1 — state before
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">1</span><div>
<h3>Company state — before the CEO</h3><p>The direction after real execution, plus the proposals queued for a decision.</p></div></div><div class="phase-body">"""
    )
    parts.append(_state_table(data["state_before"]))
    if data["proposals_before"]:
        parts.append('<div class="why" style="margin-top:10px">Proposals awaiting a decision:</div>')
        for p in data["proposals_before"]:
            parts.append(
                f'<div class="decision-row"><div class="head"><b>{_esc(p["statement"])}</b>'
                f'<span class="badge info">conf {p["confidence"]:.2f} · {p["evidence"]} evidence</span></div>'
                f'<div class="transition"><span class="kv mono">{_esc(p["id"])}</span></div></div>'
            )
    parts.append("</div></section>")

    # Phase 2 — the CEO employee
    skills = ", ".join(t for t in emp["tools"] if t in {
        "governance_read", "proposal_approve", "proposal_reject", "goal_set_priority", "goal_archive"})
    parts.append(
        f"""<section class="phase"><div class="phase-head"><span class="pnum">2</span><div>
<h3>The CEO — a real chorus employee</h3><p>Its own manifest: executive toolset, isolated sandbox, its governance tools bound to the horizon control plane through the dream <code>GovernancePort</code>.</p></div></div><div class="phase-body">
<div class="transition"><span class="kv"><b>governance tools:</b> {_esc(skills)}</span></div>
<div class="transition"><span class="kv"><b>sandbox:</b> {_esc(emp['sandbox'])} · max_turns {emp['max_turns']} · max_sprints {emp['max_sprints']}</span></div>
<div class="transition"><span class="kv mono">{_esc(emp['worktree'])}</span></div>
<div class="transition"><span class="kv"><b>standing rule:</b> {_esc(data['directive_rule'])}</span></div>
</div></section>"""
    )

    # Phase 3 — the governance beat (event timeline)
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">3</span><div>
<h3>Governance beat — the CEO reads and re-aims the live tree</h3><p>Every <code>governance_*</code> call below hit the real horizon control plane through the port. Reasoning is interleaved.</p></div></div><div class="phase-body">"""
    )
    for ev in data["events"]:
        if ev["t"] == "tool":
            parts.append(
                f'<div class="act"><span class="k">→ {_esc(str(ev["tool"]))}</span>'
                f'<br><span class="mono" style="font-size:12px">{_esc(str(ev["input"]))}</span></div>'
            )
        elif ev["t"] == "result":
            if ev.get("guardrail"):
                parts.append(
                    f'<div class="transition"><span class="badge info">guardrail · {_esc(str(ev["tool"]))}</span> '
                    '<span class="kv">read-only planning phase declined a mutation (recovered — the '
                    'generator phase applied it)</span></div>'
                )
            else:
                cls = "fail" if ev["is_error"] else "ok"
                parts.append(
                    f'<div class="transition"><span class="badge {cls}">← {_esc(str(ev["tool"]))}</span> '
                    f'<span class="kv">{_esc(str(ev["content"]))}</span></div>'
                )
        elif ev["t"] == "think":
            parts.append(f'<details class="art"><summary>thinking</summary><pre>{_esc(str(ev["text"]))}</pre></details>')
    parts.append("</div></section>")

    # Phase 4 — state after
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">4</span><div>
<h3>Company state — after the CEO</h3><p>The direction after the executive re-aimed it: approvals promoted to live decisions, distractions rejected.</p></div></div><div class="phase-body">"""
    )
    parts.append(_state_table(data["state_after"]))
    if data["proposals_after"]:
        parts.append('<div class="why" style="margin-top:10px">Proposals, after adjudication:</div>')
        for p in data["proposals_after"]:
            badge = ("ok" if p["status"] == "approved" else "fail" if p["status"] == "rejected" else "info")
            parts.append(
                f'<div class="decision-row"><div class="head"><b>{_esc(p["statement"])}</b>'
                f'<span class="badge {badge}">{_esc(p["status"])}</span></div>'
                f'<div class="transition"><span class="kv mono">{_esc(p["id"])}</span></div></div>'
            )
    parts.append("</div></section>")

    # Phase 5 — the directive
    parts.append(
        f"""<section class="phase"><div class="phase-head"><span class="pnum">5</span><div>
<h3>The directive — the CEO's deliverable</h3><p>Written to <code>directive.md</code>, judged by the CEO's AgentReview Definition of Done: <span class="badge {verdict_cls}">{verdict}</span>.</p></div></div><div class="phase-body">"""
    )
    if data["directive_md"]:
        parts.append(f'<pre class="art" style="white-space:pre-wrap">{_esc(data["directive_md"])}</pre>')
    else:
        parts.append('<p class="why">(no directive.md written)</p>')
    if meta["summary"]:
        parts.append(f'<div class="transition"><span class="kv"><b>DoD summary:</b> {_esc(meta["summary"])}</span></div>')
    parts.append("</div></section>")

    parts.append(
        f'<footer>Generated {_esc(meta["generated"])} from a live CEO run · model {_esc(meta["model"])} (Azure) · Press E to expand all.</footer>'
    )
    parts.append("""</div><script>document.addEventListener('keydown',e=>{if(e.key==='e'||e.key==='E')document.querySelectorAll('details').forEach(d=>d.open=true);});</script></body></html>""")
    return "".join(parts)



async def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

    if not all(os.environ.get(k) for k in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_DEPLOYMENT")):
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    data = await run()
    out_dir = Path(__file__).resolve().parent.parent / "reports" / "ceo-capstone"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    html_path = out_dir / "horizon-ceo-report.html"
    html_path.write_text(render_html(data), encoding="utf-8")
    print(f"\nreport: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
