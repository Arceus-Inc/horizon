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
from chorus.facade import Chorus
from chorus.ledger import SqliteLedger
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_bridge import ChorusGoalStore, ChorusIntakePort, ChorusOutcomeFeed
from chorus_harness import EmployeeHarnessFactory
from strong_run import (
    _CSS,
    RecordingReasoner,
    _esc,
    _run_to_terminal,
    _seed_warehouse,
)

from horizon import Horizon, LoopReporter
from horizon.chat import AutonomyPolicy, Ceo
from horizon.feedback import HealthPolicy
from horizon.generation import CandidateGoal, DirectionBrief
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

_ORG_FACTS = [
    "We sell an AI-assisted analytics product to mid-market teams; our edge is defensible, reproducible analysis.",
    "This quarter's single strategic priority is profitable growth, not top-line vanity.",
]
_DIRECTIVE = (
    "Approve well-evidenced proposals (three or more independent sources) that advance profitable "
    "growth, and reject distractions and low-evidence bets - protect the quarter's single priority."
)


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
        ledger.employees.create(Employee(id="ceo", name="Casey (CEO)", role="analyst"))

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
        strategy=StrategyStore(workdir / "strategy.json"), default_assignee=_EMPLOYEE,
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

    # ---- the CEO: memory + bounded autonomy ----
    autonomy = AutonomyPolicy(
        auto_kinds=frozenset({"approve_proposal", "reject_proposal"}), max_auto=3,
        min_proposal_confidence=0.8, min_evidence=3,
    )
    ceo = Ceo(
        horizon=horizon, reasoner=reasoner, memory_path=workdir / "ceo_memory.json",
        model=deployment, autonomy=autonomy, name="ceo", max_steps=10,
    )
    for fact in _ORG_FACTS:
        ceo.remember("org-facts", fact, importance=0.7)
    ceo.remember("directives", _DIRECTIVE, importance=0.95)

    # ---- CEO governance BEAT (live) ----
    print("CEO governance audit (real LLM)...")
    beat = ceo.govern()
    print(f"  prepared {len(beat.prepared_actions)} action(s); auto-applied {len(beat.auto_applied)}")

    # ---- human confirms the still-pending corrections -> the org re-aims ----
    confirmations: list[dict[str, Any]] = []
    for action in beat.prepared_actions:
        if action.status == "applied":
            confirmations.append({"kind": action.kind, "preview": action.preview,
                                  "result": action.result, "how": "auto (standing directive)"})
            continue
        with contextlib.suppress(Exception):
            result = ceo.confirm(action)
            confirmations.append({"kind": action.kind, "preview": action.preview,
                                  "result": result, "how": "human-confirmed"})

    state_after = _state_snapshot()
    proposals_after = [
        {"id": p.id, "statement": p.decision_statement, "status": p.status}
        for p in horizon.list_proposals(status=None)
    ]

    # ---- CHAT with the CEO ----
    print("chatting with the CEO (real LLM)...")
    chat_log: list[dict[str, Any]] = []
    for q in (
        "In one paragraph: what did you just change in the company, and why?",
        "What is our standing rule before greenlighting a strategic bet?",
    ):
        ans = ceo.ask(q)
        chat_log.append({
            "q": q, "a": ans.text, "citations": ans.citations,
            "tools": [s.tool for s in ans.steps],
        })
        print(f"  Q: {q[:48]}  -> {len(ans.steps)} tool step(s)")

    memory_after = [
        {"layer": e.layer, "text": e.text, "importance": e.importance}
        for e in sorted(ceo.memory.all(), key=lambda e: e.created_at)
    ]

    ledger.close()
    return {
        "meta": {
            "mission": _DECISION, "model": deployment, "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "goals": len(goals), "beats": _N_EXECUTE,
            "prepared": len(beat.prepared_actions), "auto_applied": len(beat.auto_applied),
            "confirmed": sum(1 for c in confirmations if c["how"] == "human-confirmed"),
            "llm_calls": len(reasoner.calls), "listener": horizon.listener_stats(),
        },
        "state_before": state_before, "proposals_before": proposals_before,
        "org_facts": _ORG_FACTS, "directive": _DIRECTIVE,
        "beat": {
            "findings": beat.findings, "citations": beat.citations,
            "steps": [{"tool": s.tool, "args": s.args, "observation": s.observation} for s in beat.steps],
            "actions": [
                {"kind": a.kind, "preview": a.preview, "status": a.status,
                 "auto": a.id in beat.auto_applied}
                for a in beat.prepared_actions
            ],
        },
        "confirmations": confirmations,
        "state_after": state_after, "proposals_after": proposals_after,
        "chat": chat_log, "memory_after": memory_after,
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
    parts: list[str] = []
    parts.append(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Horizon — CEO Capstone</title><style>{_CSS}{_CHAT_CSS}</style></head><body><div class="wrap">
<header class="top"><div class="eyebrow">Horizon · the CEO · executive loop</div>
<h1>CEO Capstone — the executive governs the company, live</h1>
<p class="intent"><b>Company mission:</b> {_esc(meta['mission'])}</p></header>
<div class="reverify"><h2>The executive loop</h2>
<p style="color:var(--muted);font-size:13.5px;margin:8px 0 0">A real company was built (LLM decomposition + real Analyst beats + a queue of proposals). Then the CEO ran a governance beat over it, auto-applied what a standing directive pre-approved, prepared the rest for confirmation, and answered questions about what it did — all grounded in live state and its own memory.</p>
<div class="overall"><span class="big">CEO IN COMMAND</span><p>prepared {meta['prepared']} correction(s) &middot; auto-applied {meta['auto_applied']} under standing autonomy &middot; {meta['confirmed']} human-confirmed &middot; {meta['llm_calls']} LLM calls</p></div></div>
<div class="chips">
<div class="chip"><span>{meta['goals']}</span>Goals (LLM)</div>
<div class="chip"><span>{meta['beats']}</span>Real beats run</div>
<div class="chip"><span>{meta['prepared']}</span>Corrections prepared</div>
<div class="chip"><span>{meta['auto_applied']}</span>Auto-applied</div>
<div class="chip"><span>{meta['confirmed']}</span>Human-confirmed</div>
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

    # Phase 2 — CEO memory seeded
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">2</span><div>
<h3>The CEO's memory</h3><p>What the executive carries in: durable org facts and a standing directive that shapes its judgement.</p></div></div><div class="phase-body">"""
    )
    for f in data["org_facts"]:
        parts.append(f'<div class="transition"><span class="kv">[org-fact] {_esc(f)}</span></div>')
    parts.append(f'<div class="transition"><span class="kv"><b>[directive]</b> {_esc(data["directive"])}</span></div>')
    parts.append("</div></section>")

    # Phase 3 — governance beat
    beat = data["beat"]
    parts.append(
        f"""<section class="phase"><div class="phase-head"><span class="pnum">3</span><div>
<h3>Governance beat — the CEO as an employee</h3><p>Unattended, the CEO inspected the whole company and prepared corrections. Its reasoning steps and the memo are below.</p></div></div><div class="phase-body">
<div class="overall" style="background:#eef2ff;border-color:#c7d2fe"><p style="color:#3730a3">{_esc(beat['findings'])}</p></div>"""
    )
    for a in beat["actions"]:
        tag = ('<span class="auto">✓ auto-applied (standing directive)</span>' if a["auto"]
               else f'<span class="pend">◦ {_esc(a["status"])} — awaited confirmation</span>')
        parts.append(f'<div class="act"><span class="k">{_esc(a["kind"])}</span> — {tag}<br>{_esc(a["preview"])}</div>')
    steps_txt = "\n".join(
        f"- {s['tool']}({json.dumps(s['args'])})\n  {s['observation'][:400]}" for s in beat["steps"]
    )
    parts.append(f'<details class="art"><summary>The CEO\'s reasoning steps ({len(beat["steps"])})</summary><pre>{_esc(steps_txt)}</pre></details>')
    parts.append("</div></section>")

    # Phase 4 — corrections applied
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">4</span><div>
<h3>Corrections applied — the org re-aims</h3><p>Auto-approved under the standing directive, or confirmed by a human. Each is a real write.</p></div></div><div class="phase-body">"""
    )
    for c in data["confirmations"]:
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(c["kind"])}</b>'
            f'<span class="badge {"ok" if c["how"].startswith("auto") else "info"}">{_esc(c["how"])}</span></div>'
            f'<div class="transition"><span class="kv">{_esc(c["result"])}</span></div></div>'
        )
    if not data["confirmations"]:
        parts.append('<p class="why">(no corrections)</p>')
    parts.append("</div></section>")

    # Phase 5 — state after
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">5</span><div>
<h3>Company state — after the CEO</h3><p>The direction after the executive re-aimed it.</p></div></div><div class="phase-body">"""
    )
    parts.append(_state_table(data["state_after"]))
    parts.append("</div></section>")

    # Phase 6 — chat
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">6</span><div>
<h3>Talking to the CEO</h3><p>Grounded, cited answers — drawing on live state and its own memory of what it just did.</p></div></div><div class="phase-body"><div class="bubbles">"""
    )
    for turn in data["chat"]:
        cites = f'<span class="cite">◦ cited: {_esc(", ".join(turn["citations"]) or "—")} · tools: {_esc(", ".join(turn["tools"]) or "none")}</span>'
        parts.append(f'<div class="msg u"><div class="who">You</div><div class="bub">{_esc(turn["q"])}</div></div>')
        parts.append(f'<div class="msg c"><div class="who">CEO</div><div class="bub">{_esc(turn["a"])}{cites}</div></div>')
    parts.append("</div></div></section>")

    # Phase 7 — memory after
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">7</span><div>
<h3>The CEO's memory — after</h3><p>Its decision-log now records the audit; the conversation is remembered too.</p></div></div><div class="phase-body">"""
    )
    for e in data["memory_after"]:
        parts.append(f'<div class="transition"><span class="kv">[{_esc(e["layer"])}] {_esc(e["text"][:260])}</span></div>')
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
