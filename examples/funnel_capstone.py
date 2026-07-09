"""Funnel capstone — the ENTIRE Theme C flow, live, captured in one report.

horizon *originates* a decision from real evidence instead of being handed one:

    real evidence (human seeds + live Tavily web search, governed)
      -> Scout beat (LLM)      -> candidate opportunities
      -> Analyst beat (LLM)    -> DirectionBriefs (strict json_schema) -> evidence gate
      -> Reconcile             -> proposed decisions (proposal-only)
      -> human APPROVE         -> a live decision + goals + submitted tasks
      -> real Analyst beats    -> DoD verdicts + deliverables (grounded in the gathered evidence)
      -> feedback              -> health + re-priority

Every stage is captured — the raw web results, the scout/analyst prompts + completions + tokens, the
gate verdicts, the proposals, the approval, and the real per-employee tools/operations log — and rendered
to ``reports/funnel-capstone/horizon-funnel-report.html`` in the same style as the strong-run report.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... TAVILY_API_KEY=...
    uv run python examples/funnel_capstone.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
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

# reuse the strong-run instrumentation (importing does not run it — it is __main__-guarded)
from strong_run import (
    _CSS,
    RecordingReasoner,
    _beat_ops,
    _diagnostic_for,
    _esc,
    _landed,
    _ops_html,
    _priority_rule,
    _produced_files,
    _run_to_terminal,
    _snapshot,
)

from horizon import Horizon, LoopReporter
from horizon.feedback import HealthPolicy
from horizon.generation import (
    Analyst,
    EvidenceBus,
    GovernanceGate,
    Scout,
    SeedSource,
    WebMarketSource,
    passes_evidence_gate,
)
from horizon.intake import ScorePolicy
from horizon.store import DecisionStore, StrategyStore

_EMPLOYEE = "vera"
_N_EXECUTE = 3  # cap on how many of the approved decision's goals we run through REAL beats

_MISSION = (
    "Originate next quarter's go-to-market focus for our AI coding assistant — from real market "
    "evidence, not a hand-picked decision."
)

# Human-seeded signals (internal knowledge) — real evidence, no egress.
_SEEDS: list[tuple[str, str, str]] = [
    (
        "Our product is an AI coding assistant (IDE + CLI) for professional software teams. We have "
        "budget for exactly ONE focused go-to-market bet next quarter.",
        "cofounder",
        "note",
    ),
    (
        "Sales reports the strongest inbound interest from mid-market engineering orgs (roughly "
        "100-500 developers) and from platform / developer-experience teams.",
        "head of sales",
        "signal",
    ),
]

# Live web/market queries — answered by a real Tavily search, governed by the egress gate.
_QUERIES: list[str] = [
    "enterprise AI coding assistant market size growth forecast 2026",
    "AI code assistant adoption mid-market vs enterprise developers 2026",
    "AI coding assistant go-to-market strategy competitors differentiation 2026",
]

# The executing employee's standing brief — it grounds its work in the gathered evidence (evidence.md).
_EXEC_BRIEF = (
    "You are Vera, the company's market & strategy analyst.\n\n"
    "Your workspace contains `evidence.md` — real research gathered for this decision (live web-search "
    "excerpts with source URLs, plus internal notes). It is your ONLY data source.\n\n"
    "Ground every claim in `evidence.md` and cite the specific source (URL or note) it came from. Where "
    "the evidence is insufficient for a goal, state that limitation explicitly rather than inventing "
    "numbers. Produce clear, defensible, executive-ready artifacts (e.g., a findings.md) — the format is "
    "your call."
)


def _make_tavily_fetch(api_key: str) -> Any:
    """A real Fetcher: given a Tavily search URL, run the search and return the results as text."""

    def fetch(url: str) -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", [""])[0]
        payload = json.dumps(
            {"query": query, "max_results": 5, "include_answer": True, "search_depth": "advanced"}
        ).encode()
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        lines: list[str] = [f"QUERY: {query}"]
        if data.get("answer"):
            lines.append(f"SUMMARY: {data['answer']}")
        for r in data.get("results", []):
            snippet = str(r.get("content", "")).strip().replace("\n", " ")
            lines.append(f"- {r.get('title', '')} <{r.get('url', '')}>: {snippet}")
        return "\n".join(lines)

    return fetch


def _gather_evidence() -> tuple[list[dict[str, Any]], str]:
    """Collect real evidence through the seed + governed web sources; return packets + an evidence.md."""
    bus = EvidenceBus()
    sources: list[Any] = []

    seed = SeedSource()
    for body, provenance, kind in _SEEDS:
        seed.add(body, kind=kind, provenance=provenance, reliability=0.7)
    sources.append(seed)

    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        gate = GovernanceGate(allowed_hosts=["tavily.com"], require_credential=True, max_bytes=400_000)
        web = WebMarketSource(
            gate=gate,
            fetch=_make_tavily_fetch(tavily_key),
            urls=[f"https://api.tavily.com/search?q={urllib.parse.quote(q)}" for q in _QUERIES],
            credential=tavily_key,
        )
        sources.append(web)
    else:
        print("  (no TAVILY_API_KEY — running with human-seeded evidence only)")

    packets = bus.collect(sources)
    rows = [
        {
            "id": p.id,
            "source": p.source,
            "kind": p.kind,
            "reliability": p.reliability,
            "provenance": p.provenance,
            "body": p.body,
        }
        for p in packets
    ]
    evidence_md = "# Evidence gathered for this decision\n\n" + "\n\n".join(
        f"## [{p.id}] {p.source} · reliability {p.reliability:.2f}\n"
        f"Provenance: {p.provenance}\n\n{p.body}"
        for p in packets
    )
    return rows, evidence_md


async def run() -> dict[str, Any]:
    key = os.environ["AZURE_OPENAI_API_KEY"]
    base = os.environ["AZURE_OPENAI_BASE_URL"]
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    workdir = Path(__file__).resolve().parent.parent / ".horizon" / "funnel-capstone"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    # ---- Phase 1: gather real evidence (seeds + live Tavily, governed) ----
    print("gathering evidence (seeds + live Tavily web search)...")
    evidence_rows, evidence_md = _gather_evidence()
    print(f"  -> {len(evidence_rows)} evidence packets")

    ledger = SqliteLedger.open(str(workdir / "ledger.db"))
    registry = RoleRegistry.from_plugins(default_roles())
    company_id = f"horizon-funnel-{datetime.now(UTC).strftime('%m%d-%H%M%S')}"
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=deployment, company_id=company_id,
        roles=registry, ledger=ledger, timeout_s=600.0,
    )
    materialized = factory.materialize(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))
    (materialized.working_dir / "evidence.md").write_text(evidence_md, encoding="utf-8")
    (materialized.working_dir / "BRIEF.md").write_text(_EXEC_BRIEF, encoding="utf-8")
    ledger.employees.create(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))

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
    reporter = LoopReporter(title="Funnel capstone", score_policy=score_policy)
    horizon = Horizon(
        goals=ChorusGoalStore(chorus),
        intake=ChorusIntakePort(chorus),
        outcomes=ChorusOutcomeFeed(chorus),
        reasoner=reasoner,
        decisions=DecisionStore(workdir / "decisions.json"),
        strategy=StrategyStore(workdir / "strategy.json"),
        default_assignee=_EMPLOYEE,
        model=deployment,
        score_policy=score_policy,
        health_policy=health_policy,
        proposals=None,
        outcome_observer=reporter.observe,
    )

    # rebuild the evidence packets as objects for the scout/analyst (drive stages explicitly to capture)
    from horizon.generation import EvidencePacket

    packets = [
        EvidencePacket(
            id=r["id"], source=r["source"], kind=r["kind"], body=r["body"],
            provenance=r["provenance"], reliability=r["reliability"],
        )
        for r in evidence_rows
    ]

    # ---- Phase 2: Scout — evidence -> candidate opportunities (LLM) ----
    print("scouting (real LLM)...")
    scout = Scout(reasoner=reasoner, model=deployment)
    candidates = scout.survey(packets)
    scout_call = reasoner.calls[-1] if reasoner.calls else {}
    print(f"  -> {len(candidates)} candidate opportunities")

    # ---- Phase 3: Analyst — each candidate -> a DirectionBrief (LLM) -> evidence gate ----
    print("analysing candidates (real LLM)...")
    analyst = Analyst(reasoner=reasoner, model=deployment)
    by_id = {p.id: p for p in packets}
    briefs_data: list[dict[str, Any]] = []
    gated_briefs = []
    for cand in candidates:
        support = [by_id[i] for i in cand.evidence_ids if i in by_id] or packets
        brief = analyst.analyze(cand, support)
        call = reasoner.calls[-1]
        ok = passes_evidence_gate(brief)
        if ok:
            gated_briefs.append(brief)
        briefs_data.append(
            {
                "candidate_id": cand.id,
                "candidate_title": cand.title,
                "recommendation": brief.recommendation,
                "rationale": brief.rationale,
                "confidence": brief.confidence,
                "risks": brief.risks,
                "evidence_refs": brief.evidence_refs,
                "goals": [
                    {"title": g.title, "metric": g.metric, "target": g.target,
                     "score": g.score, "rationale": g.rationale}
                    for g in brief.candidate_goals
                ],
                "gated": ok,
                "prompt": call.get("prompt", ""),
                "raw_completion": call.get("text", ""),
                "input_tokens": call.get("input_tokens"),
                "output_tokens": call.get("output_tokens"),
            }
        )
        print(f"  -> brief for {cand.title[:40]!r}: confidence {brief.confidence:.2f}, gate {'PASS' if ok else 'DROP'}")

    # ---- Phase 4: Reconcile -> proposed decisions (proposal-only) ----
    proposals = horizon.reconcile(gated_briefs)
    print(f"  -> {len(proposals)} proposal(s)")

    # ---- Phase 5: human APPROVE the top proposal -> a live decision + goals + submitted tasks ----
    horizon.start()
    approved_id: str | None = None
    decision_info: dict[str, Any] = {}
    if proposals:
        top = proposals[0]
        approved_id = top.id
        decision_id = horizon.approve_proposal(top.id, by="cofounder")
        decision = horizon._decisions.get(decision_id)  # read model for the report
        decision_info = {
            "id": decision_id,
            "statement": decision.statement if decision else top.decision_statement,
            "rationale": decision.rationale if decision else top.decision_rationale,
            "owner": decision.owner if decision else _EMPLOYEE,
        }
        print(f"  APPROVED -> live decision {decision_id}: {decision_info['statement'][:60]!r}")

    proposals_data = [
        {
            "id": p.id,
            "statement": p.decision_statement,
            "rationale": p.decision_rationale,
            "approved": p.id == approved_id,
        }
        for p in proposals
    ]

    # ---- Phase 6+7: submit + run REAL beats for the approved decision's goals ----
    submissions: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    goals_all = []
    if approved_id and decision_info:
        for st in horizon.state():
            if st.decision.id == decision_info["id"]:
                goals_all = sorted(st.goals, key=lambda g: g.score, reverse=True)
    to_execute = goals_all[:_N_EXECUTE]
    for goal in to_execute:
        submissions.append(
            {
                "title": goal.title,
                "score": goal.score,
                "priority": score_policy.priority_for(goal.score),
                "priority_rule": _priority_rule(goal.score, score_policy),
                "assignee": goal.owner or _EMPLOYEE,
                "metric": goal.metric,
                "target": goal.target,
                "task_id": goal.task_id,
            }
        )
        if goal.task_id is None:
            continue
        print(f"  running real beat: {goal.title[:48]!r} ({score_policy.priority_for(goal.score)})")
        beat_t0 = time.time()
        before_files = _snapshot(materialized.working_dir)
        trail = await _run_to_terminal(chorus, ledger, goal.task_id)
        after_files = _snapshot(materialized.working_dir)
        dod = ledger.dod.get_for_task(goal.task_id)
        executions.append(
            {
                "title": goal.title,
                "task_id": goal.task_id,
                "status_trail": trail,
                "final_status": trail[-1] if trail else "unknown",
                "dod_status": dod.status.value if dod is not None else None,
                "dod_verdict": dod.verdict if dod is not None else None,
                "artifacts": _produced_files(materialized.working_dir, before_files, after_files),
                "artifacts_landed": _landed(ledger, goal.task_id),
                "ops": _beat_ops(materialized.working_dir, beat_t0),
                "diagnostic": "" if (dod and dod.status.value == "passed") else _diagnostic_for(ledger, goal.task_id),
            }
        )
        print(f"    -> {trail[-1] if trail else '?'}  dod={dod.status.value if dod else '?'}")

    # ---- feedback + final direction ----
    feedback: list[dict[str, Any]] = []
    for t in reporter.transitions:
        if t.passed:
            health_rule = "DoD passed → on_track (the work landed)"
            score_rule = f"{t.score_before:.2f} * {health_policy.pass_decay} = {t.score_after:.2f} (decay)"
        else:
            health_rule = f"DoD failed → {t.health_after} (pass-rate rule)"
            score_rule = f"{t.score_before:.2f} + {health_policy.fail_bump} = {t.score_after:.2f} (bump)"
        feedback.append(
            {
                "title": t.title, "verdict": "PASS" if t.passed else "FAIL",
                "health_before": t.health_before, "health_after": t.health_after,
                "health_rule": health_rule, "score_before": t.score_before,
                "score_after": t.score_after, "score_rule": score_rule,
                "priority_before": t.priority_before, "priority_after": t.priority_after,
            }
        )

    direction: list[dict[str, Any]] = []
    for st in horizon.state():
        for goal in sorted(st.goals, key=lambda g: g.score, reverse=True):
            direction.append(
                {
                    "title": goal.title, "score": goal.score,
                    "priority": score_policy.priority_for(goal.score),
                    "health": goal.health, "status": goal.status, "task_id": goal.task_id,
                }
            )

    ledger.close()
    passes = sum(1 for f in feedback if f["verdict"] == "PASS")
    fails = sum(1 for f in feedback if f["verdict"] == "FAIL")
    return {
        "meta": {
            "mission": _MISSION,
            "model": deployment,
            "employee": _EMPLOYEE,
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "n_evidence": len(evidence_rows),
            "n_candidates": len(candidates),
            "n_briefs": len(briefs_data),
            "n_gated": len(gated_briefs),
            "n_proposals": len(proposals_data),
            "beats": len(executions),
            "passes": passes,
            "fails": fails,
            "web": any(r["source"] == "web.market" for r in evidence_rows),
            "listener": horizon.listener_stats(),
        },
        "decision": decision_info,
        "evidence": evidence_rows,
        "scout": {
            "prompt": scout_call.get("prompt", ""),
            "raw_completion": scout_call.get("text", ""),
            "input_tokens": scout_call.get("input_tokens"),
            "output_tokens": scout_call.get("output_tokens"),
            "candidates": [
                {"title": c.title, "thesis": c.thesis, "confidence": c.confidence,
                 "evidence_ids": c.evidence_ids}
                for c in candidates
            ],
        },
        "briefs": briefs_data,
        "proposals": proposals_data,
        "submissions": submissions,
        "executions": executions,
        "feedback": feedback,
        "direction": direction,
    }


# --------------------------------------------------------------------------- HTML renderer


def render_html(data: dict[str, Any]) -> str:
    meta = data["meta"]
    dec = data["decision"]
    parts: list[str] = []
    parts.append(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Horizon — Generation Funnel Capstone</title><style>{_CSS}</style></head><body><div class="wrap">
<header class="top"><div class="eyebrow">Horizon · generation funnel · model {_esc(meta['model'])}</div>
<h1>Funnel Capstone — horizon originates the decision from real evidence</h1>
<p class="intent"><b>Mission:</b> {_esc(meta['mission'])}</p></header>
<div class="reverify"><h2>The originated decision</h2>
<p style="color:var(--muted);font-size:13.5px;margin:8px 0 12px">No decision was handed to horizon. It gathered real evidence (human seeds + live web search), scouted opportunities, had an analyst write evidence-gated briefs, and proposed decisions. A human approved one — and only then did it become a live decision that drove real work.</p>"""
    )
    if dec.get("statement"):
        parts.append(
            f'<div class="overall"><span class="big">DECISION ORIGINATED</span>'
            f'<p><b>{_esc(dec["statement"])}</b><br>{_esc(dec.get("rationale", ""))}</p></div>'
        )
    else:
        parts.append('<div class="overall"><span class="big">NO PROPOSAL CLEARED THE GATE</span><p>The evidence did not yield a gate-clearing brief this run.</p></div>')
    parts.append(
        f"""<p style="color:var(--muted);font-size:12.5px;margin:10px 0 0"><b>Event listeners</b>: handled {meta['listener']['handled']} &middot; dropped {meta['listener']['dropped']} &middot; deferred {meta['listener']['deferred']}.</p></div>
<div class="chips">
<div class="chip"><span>{meta['n_evidence']}</span>Evidence packets{' · web live' if meta['web'] else ''}</div>
<div class="chip"><span>{meta['n_candidates']}</span>Scout candidates</div>
<div class="chip"><span>{meta['n_gated']}/{meta['n_briefs']}</span>Briefs past the gate</div>
<div class="chip"><span>{meta['n_proposals']}</span>Proposals</div>
<div class="chip"><span>{meta['beats']}</span>Real beats run</div>
<div class="chip"><span>{meta['passes']}/{meta['fails']}</span>Verdicts pass/fail</div>
</div><h2 class="sec">The funnel, phase by phase</h2>"""
    )

    # Phase 1 — evidence
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">1</span><div>
<h3>Evidence — real signals gathered (human seeds + live web, governed)</h3>
<p>Every source is normalized into a typed, attributable evidence packet. The web/market source reaches the network only through the governance gate (allow-list + credential + size cap).</p></div></div><div class="phase-body">"""
    )
    parts.append('<table><tr><th>id</th><th>source</th><th>reliab.</th><th>provenance</th><th>signal</th></tr>')
    for e in data["evidence"]:
        body = e["body"]
        short = body if len(body) <= 300 else body[:300] + " …"
        parts.append(
            f'<tr><td class="mono">{_esc(e["id"])}</td><td>{_esc(e["source"])}</td>'
            f'<td class="num">{e["reliability"]:.2f}</td><td class="why">{_esc(e["provenance"])}</td>'
            f'<td>{_esc(short)}</td></tr>'
        )
    parts.append("</table>")
    for e in data["evidence"]:
        if e["source"] == "web.market":
            parts.append(
                f'<details class="art"><summary>Raw web result — {_esc(e["provenance"])}</summary><pre>{_esc(e["body"])}</pre></details>'
            )
    parts.append("</div></section>")

    # Phase 2 — scout
    sc = data["scout"]
    parts.append(
        f"""<section class="phase"><div class="phase-head"><span class="pnum">2</span><div>
<h3>Scout — cluster evidence into candidate opportunities (LLM)</h3>
<p>A bounded reasoner pass clusters the evidence into candidate theses, each grounded in the packets that support it. Strict json_schema output — {_esc(sc.get('output_tokens'))} output tokens.</p></div></div><div class="phase-body">"""
    )
    for c in sc["candidates"]:
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(c["title"])}</b>'
            f'<span class="badge info">confidence {c["confidence"]:.2f}</span></div>'
            f'<p class="why">{_esc(c["thesis"])}</p>'
            f'<div class="transition"><span class="kv">grounded in: <span class="mono">{_esc(", ".join(c["evidence_ids"]) or "—")}</span></span></div></div>'
        )
    if not sc["candidates"]:
        parts.append('<p class="why">(the scout surfaced no candidates)</p>')
    parts.append(
        f'<details class="art"><summary>Raw scout completion (verbatim)</summary><pre>{_esc(sc["raw_completion"])}</pre></details>'
        f'<details class="art"><summary>Raw scout prompt</summary><pre>{_esc(sc["prompt"])}</pre></details>'
    )
    parts.append("</div></section>")

    # Phase 3 — analyst
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">3</span><div>
<h3>Analyst — each candidate → an evidence-gated DirectionBrief (LLM)</h3>
<p>The analyst turns a candidate into a recommendation with concrete goals, risks, confidence, and evidence refs. A brief must clear the evidence gate (confidence ≥ 0.60, real goals, ≥ 1 evidence ref) to become a proposal.</p></div></div><div class="phase-body">"""
    )
    for b in data["briefs"]:
        badge = '<span class="badge ok">gate PASS</span>' if b["gated"] else '<span class="badge fail">gate DROP</span>'
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(b["recommendation"])}</b>'
            f'<span class="badge info">conf {b["confidence"]:.2f}</span>{badge}</div>'
            f'<p class="why">{_esc(b["rationale"])}</p>'
        )
        if b["goals"]:
            parts.append('<table><tr><th>score</th><th>goal</th><th>metric → target</th></tr>')
            for g in b["goals"]:
                parts.append(
                    f'<tr><td class="num">{g["score"]:.2f}</td><td><b>{_esc(g["title"])}</b></td>'
                    f'<td class="why">{_esc(g["metric"])} → {_esc(g["target"])}</td></tr>'
                )
            parts.append("</table>")
        if b["risks"]:
            parts.append('<div class="why">risks: ' + _esc("; ".join(b["risks"])) + "</div>")
        parts.append(
            f'<div class="transition"><span class="kv">evidence: <span class="mono">{_esc(", ".join(b["evidence_refs"]) or "—")}</span></span></div>'
            f'<details class="art"><summary>Raw analyst completion — {_esc(b["output_tokens"])} output tokens</summary><pre>{_esc(b["raw_completion"])}</pre></details></div>'
        )
    parts.append("</div></section>")

    # Phase 4 — reconcile / proposals
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">4</span><div>
<h3>Reconcile → Proposals (proposal-only)</h3>
<p>Gate-clearing briefs become proposed decisions, deduped against live decisions and each other. Nothing here has touched the live tree yet.</p></div></div><div class="phase-body">"""
    )
    for p in data["proposals"]:
        badge = '<span class="badge ok">APPROVED</span>' if p["approved"] else '<span class="badge warn">proposed</span>'
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(p["statement"])}</b>{badge}</div>'
            f'<p class="why">{_esc(p["rationale"])}</p><div class="transition"><span class="kv">id: <span class="mono">{_esc(p["id"])}</span></span></div></div>'
        )
    if not data["proposals"]:
        parts.append('<p class="why">(no proposals — nothing cleared the gate)</p>')
    parts.append("</div></section>")

    # Phase 5 — approval -> decision
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">5</span><div>
<h3>Approve — the only path from proposal to the live tree</h3>
<p>A human approves one proposal. Horizon seeds a live decision from the brief, authors its goals directly (the analyst already produced them), and submits them — no second LLM pass.</p></div></div><div class="phase-body">"""
    )
    if dec.get("statement"):
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(dec["statement"])}</b><span class="badge ok">live decision</span></div>'
            f'<div class="transition"><span class="kv">id: <span class="mono">{_esc(dec["id"])}</span></span>'
            f'<span class="kv">owner: <b>{_esc(dec["owner"])}</b></span><span class="kv">approved by: <b>cofounder</b></span></div></div>'
        )
    else:
        parts.append('<p class="why">(no proposal was approved)</p>')
    parts.append("</div></section>")

    # Phase 6 — submit
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">6</span><div>
<h3>Submit — goals → chorus tasks (priority from score)</h3>
<p>Each authored goal is opened as exactly one chorus task at a score-derived priority.</p></div></div><div class="phase-body">"""
    )
    for s in data["submissions"]:
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(s["title"])}</b>'
            f'<span class="badge info">{_esc(s["priority"])}</span></div>'
            f'<div class="transition"><span class="kv">priority: <b>{_esc(s["priority_rule"])}</b></span>'
            f'<span class="kv">assignee: <b>{_esc(s["assignee"])}</b></span></div>'
            f'<div class="transition"><span class="kv">metric → target: <span class="why">{_esc(s["metric"])} → {_esc(s["target"])}</span></span>'
            f'<span class="kv">task: <span class="mono">{_esc(s["task_id"]) if s["task_id"] else "—"}</span></span></div></div>'
        )
    if not data["submissions"]:
        parts.append('<p class="why">(no goals submitted)</p>')
    parts.append("</div></section>")

    # Phase 7 — execute (real beats) — reuse the strong-run style
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">7</span><div>
<h3>Execute — real Analyst beats (chorus), grounded in the gathered evidence</h3>
<p>chorus runs each task as a real beat over <code>evidence.md</code>. horizon only observes. The raw DoD verdict, the per-employee tools/operations log, and the deliverables are below.</p></div></div><div class="phase-body">"""
    )
    for e in data["executions"]:
        ok = e["dod_status"] == "passed"
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(e["title"])}</b>'
            f'<span class="badge {"ok" if e["final_status"]=="done" else "fail"}">{_esc(e["final_status"])}</span>'
            f'<span class="badge {"ok" if ok else "warn"}">DoD {_esc(e["dod_status"])}</span></div>'
            f'<details class="art"><summary>Raw DoD verdict</summary><pre>{_esc(json.dumps(e["dod_verdict"], indent=2))}</pre></details>'
        )
        parts.append(_ops_html(e.get("ops"), meta["employee"]))
        arts = e.get("artifacts", [])
        if arts:
            parts.append(f'<div class="why">Deliverables the Analyst produced ({len(arts)}):</div>')
            for a in arts:
                name = a["path"].rsplit("/", 1)[-1].lower()
                is_primary = name in {"findings.md", "summary.md", "report.md", "readme.md"}
                openattr = " open" if is_primary else ""
                star = " ★ deliverable" if is_primary else ""
                if a["binary"]:
                    parts.append(f'<details class="art"><summary>{_esc(a["path"])} — binary, {a["bytes"]} bytes</summary></details>')
                else:
                    parts.append(
                        f'<details class="art"{openattr}><summary>{_esc(a["path"])}{star} — {a["bytes"]} bytes</summary><pre>{_esc(a["content"])}</pre></details>'
                    )
        else:
            parts.append('<div class="why">(no new artifacts detected)</div>')
        parts.append("</div>")
    if not data["executions"]:
        parts.append('<p class="why">(no beats run)</p>')
    parts.append("</div></section>")

    # Phase 8 — feedback + direction
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">8</span><div>
<h3>Feedback + final direction</h3>
<p>Horizon folds each real verdict into health + re-priority, then the read model shows the whole originated decision.</p></div></div><div class="phase-body">"""
    )
    for f in data["feedback"]:
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(f["title"])}</b>'
            f'<span class="badge {"ok" if f["verdict"]=="PASS" else "fail"}">{_esc(f["verdict"])}</span></div>'
            f'<div class="transition"><span class="kv">health: <b>{_esc(f["health_before"])} <span class="arrow">→</span> {_esc(f["health_after"])}</b> <span class="why">({_esc(f["health_rule"])})</span></span></div>'
            f'<div class="transition"><span class="kv">score: <b>{f["score_before"]:.2f} <span class="arrow">→</span> {f["score_after"]:.2f}</b> <span class="why">({_esc(f["score_rule"])})</span></span></div></div>'
        )
    if not data["feedback"]:
        parts.append('<p class="why">(no verdicts folded)</p>')
    parts.append('<table style="margin-top:14px"><tr><th>score</th><th>priority</th><th>health</th><th>status</th><th>goal</th><th>task</th></tr>')
    for d in data["direction"]:
        status_cell = '<span class="badge ok">done</span>' if d["status"] == "done" else _esc(d["status"])
        parts.append(
            f'<tr><td class="num">{d["score"]:.2f}</td><td>{_esc(d["priority"])}</td>'
            f'<td>{_esc(d["health"])}</td><td>{status_cell}</td><td>{_esc(d["title"])}</td>'
            f'<td class="mono">{_esc(d["task_id"]) if d["task_id"] else "—"}</td></tr>'
        )
    parts.append("</table></div></section>")

    parts.append(
        f'<footer>Generated {_esc(meta["generated"])} from a live horizon funnel run · model {_esc(meta["model"])} (Azure) + Tavily web · Press E to expand all.</footer>'
    )
    parts.append(
        """</div><script>document.addEventListener('keydown',e=>{if(e.key==='e'||e.key==='E')document.querySelectorAll('details').forEach(d=>d.open=true);});</script></body></html>"""
    )
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
    out_dir = Path(__file__).resolve().parent.parent / "reports" / "funnel-capstone"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    html_path = out_dir / "horizon-funnel-report.html"
    html_path.write_text(render_html(data), encoding="utf-8")
    print(f"\nreport: {html_path}")
    print(f"data:   {out_dir / 'data.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
