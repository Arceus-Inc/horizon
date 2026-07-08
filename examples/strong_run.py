"""Strong run — an instrumented live capstone that captures EXACTLY what horizon decides, and why.

Real LLM decomposition of a rich decision -> submit several goals -> run several REAL Analyst beats ->
horizon folds the real DoD verdicts and re-prioritises. Every decision is captured with its raw inputs
(the full prompt, the raw LLM completion, tokens), the rule applied (score->priority, health->score),
and the real outputs (task ids, DoD verdicts, and whatever artifacts the employee produced). Renders a
flow-report-style HTML to ``reports/strong-test/horizon-flow-report.html``.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/strong_run.py
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import os
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dream
from chorus.facade import Chorus
from chorus.ledger import SqliteLedger, TaskStatus
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_bridge import ChorusGoalStore, ChorusIntakePort, ChorusOutcomeFeed
from chorus_harness import EmployeeHarnessFactory
from dream.api.substrate import CompletionResult

from horizon import Horizon, LoopReporter
from horizon.feedback import HealthPolicy
from horizon.intake import ScorePolicy, fingerprint
from horizon.model import Decision

_EMPLOYEE = "vera"
_N_EXECUTE = 3  # how many top goals to run through REAL beats
_TERMINAL = (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.BLOCKED, TaskStatus.REJECTED)
_MAX_TICKS = 240

_DECISION = (
    "Decide where to concentrate our sales investment next quarter to grow profit the most, "
    "and back the recommendation with evidence a skeptical executive would accept."
)

# The employee's standing brief — its context, SEPARATE from the decision. This is horizon's generic
# lever: when a goal struggles, horizon improves the brief / tools, never the strategic decision itself.
_BRIEF = (
    "You are Vera, the company's data analyst.\n\n"
    "Your workspace contains the company sales warehouse at `warehouse.db` — a SQLite database with "
    "two tables:\n"
    "  - sales(region, quarter, revenue, units)\n"
    "  - costs(region, quarter, cost)\n"
    "covering quarters Q1-Q3 for regions A, B, and C.\n\n"
    "Ground every claim in this data with exact numbers. Produce whatever artifacts make your findings "
    "clear, defensible, and reproducible for an executive audience — the format is your call."
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
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales (region TEXT, quarter TEXT, revenue INTEGER, units INTEGER)")
    conn.execute("CREATE TABLE costs (region TEXT, quarter TEXT, cost INTEGER)")
    conn.executemany("INSERT INTO sales VALUES (?, ?, ?, ?)", _SALES)
    conn.executemany("INSERT INTO costs VALUES (?, ?, ?)", _COSTS)
    conn.commit()
    conn.close()


_SEEDED = {"warehouse.db", "BRIEF.md"}
_SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__", ".pytest_cache", ".chorus"}
_MAX_ARTIFACT_BYTES = 8000


def _snapshot(root: Path) -> dict[str, float]:
    """Map each worktree file (rel path) to its mtime, skipping noise dirs."""
    out: dict[str, float] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        with contextlib.suppress(OSError):
            out[rel.as_posix()] = path.stat().st_mtime
    return out


def _produced_files(
    root: Path, before: dict[str, float], after: dict[str, float]
) -> list[dict[str, Any]]:
    """The files the beat created or changed (the employee's OWN artifacts), with bounded content."""
    changed = sorted(
        rel for rel, mtime in after.items() if before.get(rel) != mtime and rel not in _SEEDED
    )
    files: list[dict[str, Any]] = []
    for rel in changed[:16]:
        raw = b""
        with contextlib.suppress(OSError):
            raw = (root / rel).read_bytes()
        try:
            content, binary = raw.decode("utf-8")[:_MAX_ARTIFACT_BYTES], False
        except UnicodeDecodeError:
            content, binary = "", True
        files.append({"path": rel, "bytes": len(raw), "binary": binary, "content": content})
    return files


class RecordingReasoner:
    """Wrap the real substrate and record every (prompt, params, completion, tokens) call."""

    name = "recording"

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, params: dict[str, Any] | None = None) -> CompletionResult:
        result = self._inner.complete(prompt, params)
        self.calls.append(
            {
                "prompt": prompt,
                "params": params or {},
                "text": result.text,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "finish_reason": result.finish_reason,
            }
        )
        return result


def _priority_rule(score: float, policy: ScorePolicy) -> str:
    if score >= policy.high:
        return f"score {score:.2f} ≥ {policy.high:.2f} (high threshold) → high"
    if score >= policy.medium:
        return f"{policy.medium:.2f} ≤ score {score:.2f} < {policy.high:.2f} → medium"
    return f"score {score:.2f} < {policy.medium:.2f} → low"


async def _run_to_terminal(chorus: Chorus, ledger: SqliteLedger, task_id: str) -> list[str]:
    trail: list[str] = []
    last = ""
    for _ in range(_MAX_TICKS):
        await chorus.tick()
        await chorus.drain()
        task = ledger.tasks.get(task_id)
        assert task is not None
        if task.status.value != last:
            last = task.status.value
            trail.append(last)
        if task.status in _TERMINAL:
            break
    return trail


async def run() -> dict[str, Any]:
    key = os.environ["AZURE_OPENAI_API_KEY"]
    base = os.environ["AZURE_OPENAI_BASE_URL"]
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    workdir = Path(__file__).resolve().parent.parent / ".horizon" / "strong-run"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    ledger = SqliteLedger.open(str(workdir / "ledger.db"))
    registry = RoleRegistry.from_plugins(default_roles())
    company_id = f"horizon-strong-{datetime.now(UTC).strftime('%m%d-%H%M%S')}"
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=deployment, company_id=company_id,
        roles=registry, ledger=ledger, timeout_s=600.0,
    )
    materialized = factory.materialize(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))
    _seed_warehouse(materialized.working_dir / "warehouse.db")
    (materialized.working_dir / "BRIEF.md").write_text(_BRIEF, encoding="utf-8")
    ledger.employees.create(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))

    chorus = Chorus.build(
        ledger=ledger, org_repo=str(workdir / "org"), memory_repo=str(workdir / "memory"),
        dream=dream, beat_runner_for=factory, landers=factory.landers, roles=default_roles(),
    )

    from dream.api.openai import OpenAIChatSubstrate

    from horizon.store import DecisionStore, StrategyStore

    reasoner = RecordingReasoner(
        OpenAIChatSubstrate(name="azure", api_key=key, model=deployment, base_url=base)
    )
    score_policy = ScorePolicy()
    health_policy = HealthPolicy()
    reporter = LoopReporter(title="Strong run", score_policy=score_policy)
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
        outcome_observer=reporter.observe,
    )

    # ---- Phase 1: decompose (real LLM) ----
    decision = Decision(id="dec_strong", statement=_DECISION, owner=None)
    horizon.seed_decision(decision)
    print("decomposing (real LLM)...")
    goals = horizon.decompose(decision.id)
    reporter.record_decomposition(decision, goals)
    call = reasoner.calls[0]
    print(f"  -> {len(goals)} goals ({call['input_tokens']} in / {call['output_tokens']} out tokens)")

    ordered = sorted(goals, key=lambda g: g.score, reverse=True)
    to_execute = ordered[:_N_EXECUTE]

    horizon.start()

    submissions: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    for goal in to_execute:
        assignee = goal.owner or _EMPLOYEE
        fp = fingerprint(goal.id, goal.title)
        transitions_before = len(reporter.transitions)
        task_id = horizon.submit_goal(goal)
        reporter.record_submission(goal, task_id, assignee=assignee)
        submissions.append(
            {
                "goal_id": goal.id,
                "title": goal.title,
                "score": goal.score,
                "priority": score_policy.priority_for(goal.score),
                "priority_rule": _priority_rule(goal.score, score_policy),
                "assignee": assignee,
                "assignee_rule": (
                    f"goal.owner unset → default_assignee '{_EMPLOYEE}'"
                    if goal.owner is None
                    else f"goal.owner '{goal.owner}'"
                ),
                "fingerprint": fp,
                "task_id": task_id,
            }
        )
        print(f"  submitted {goal.title!r} -> {task_id} ({score_policy.priority_for(goal.score)})")
        print("  running real beat...")
        before_files = _snapshot(materialized.working_dir)
        trail = await _run_to_terminal(chorus, ledger, task_id)
        after_files = _snapshot(materialized.working_dir)

        dod = ledger.dod.get_for_task(task_id)
        runs = ledger.runs.for_task(task_id)
        executions.append(
            {
                "goal_id": goal.id,
                "title": goal.title,
                "task_id": task_id,
                "status_trail": trail,
                "final_status": trail[-1] if trail else "unknown",
                "dod_status": dod.status.value if dod is not None else None,
                "dod_verdict": dod.verdict if dod is not None else None,
                "run_outcome": runs[-1].outcome if runs else None,
                "artifacts": _produced_files(materialized.working_dir, before_files, after_files),
                "folded": len(reporter.transitions) > transitions_before,
            }
        )
        print(f"    -> {trail[-1] if trail else '?'}  dod={dod.status.value if dod else '?'}")

    # ---- capture feedback transitions + final direction ----
    feedback: list[dict[str, Any]] = []
    for t in reporter.transitions:
        if t.passed:
            health_rule = "DoD passed → on_track (the work landed)"
            score_rule = (
                f"{t.score_before:.2f} × {health_policy.pass_decay} = {t.score_after:.2f} "
                "(decay — handled, deprioritise)"
            )
        else:
            health_rule = f"DoD failed → {t.health_after} (pass-rate rule)"
            score_rule = (
                f"{t.score_before:.2f} + {health_policy.fail_bump} = {t.score_after:.2f} "
                "(bump — surface it)"
            )
        feedback.append(
            {
                "goal_id": t.goal_id,
                "title": t.title,
                "verdict": "PASS" if t.passed else "FAIL",
                "health_before": t.health_before,
                "health_after": t.health_after,
                "health_rule": health_rule,
                "score_before": t.score_before,
                "score_after": t.score_after,
                "score_rule": score_rule,
                "priority_before": t.priority_before,
                "priority_after": t.priority_after,
            }
        )

    direction: list[dict[str, Any]] = []
    for state in horizon.state():
        for goal in sorted(state.goals, key=lambda g: g.score, reverse=True):
            direction.append(
                {
                    "title": goal.title,
                    "score": goal.score,
                    "priority": score_policy.priority_for(goal.score),
                    "health": goal.health,
                    "task_id": goal.task_id,
                    "executed": goal.task_id is not None,
                }
            )

    ledger.close()
    return {
        "meta": {
            "decision": _DECISION,
            "brief": _BRIEF,
            "model": deployment,
            "employee": _EMPLOYEE,
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "goals_produced": len(goals),
            "goals_executed": len(executions),
            "llm_calls": len(reasoner.calls),
        },
        "decomposition": {
            "prompt": call["prompt"],
            "raw_completion": call["text"],
            "input_tokens": call["input_tokens"],
            "output_tokens": call["output_tokens"],
            "goals": [
                {
                    "id": g.id,
                    "title": g.title,
                    "score": g.score,
                    "metric": g.metric,
                    "target": g.target,
                    "rationale": g.evidence[0] if g.evidence else "",
                }
                for g in ordered
            ],
        },
        "submissions": submissions,
        "executions": executions,
        "feedback": feedback,
        "direction": direction,
    }


# --------------------------------------------------------------------------- HTML renderer

_CSS = """
:root{--bg:#f6f8fa;--card:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--accent:#0d9488;--accent-soft:#ecfeff;}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:1000px;margin:0 auto;padding:32px 20px 80px;}
header.top{background:linear-gradient(135deg,#ecfeff,#f6f8fa);border:1px solid var(--line);border-radius:16px;padding:28px 28px 22px;margin-bottom:22px;}
header.top .eyebrow{color:var(--accent);font-weight:700;letter-spacing:.06em;text-transform:uppercase;font-size:12px;}
header.top h1{margin:.2em 0 .3em;font-size:26px;}
header.top .intent{color:var(--muted);margin:0;}
header.top .intent b{color:var(--ink);}
.badge{font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;}
.badge.ok{background:#dcfce7;color:#166534;}
.badge.warn{background:#fef9c3;color:#854d0e;}
.badge.fail{background:#fee2e2;color:#b91c1c;}
.badge.info{background:var(--accent-soft);color:#0e7490;}
.reverify{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 20px 18px;margin:22px 0;}
.reverify h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:16px 0 6px;}
.overall{display:flex;align-items:center;gap:14px;margin-top:14px;padding:14px 16px;border-radius:12px;background:#f0fdf4;border:1px solid #bbf7d0;}
.overall .big{font-size:18px;font-weight:800;letter-spacing:.02em;color:#166534;}
.overall p{margin:0;color:var(--muted);font-size:13px;}
.chips{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0;}
.chip{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;color:var(--muted);font-size:12.5px;}
.chip span{display:block;font-size:24px;font-weight:750;color:var(--ink);line-height:1.1;}
h2.sec{font-size:15px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:34px 0 12px;}
.phase{background:var(--card);border:1px solid var(--line);border-radius:14px;margin-bottom:16px;overflow:hidden;}
.phase-head{display:flex;gap:14px;align-items:flex-start;padding:18px 20px 14px;border-bottom:1px solid var(--line);background:#fbfcfe;}
.pnum{flex:0 0 auto;width:30px;height:30px;border-radius:50%;background:var(--accent);color:#fff;font-weight:750;display:grid;place-items:center;}
.phase-head h3{margin:2px 0 3px;font-size:17px;}
.phase-head p{margin:0;color:var(--muted);font-size:13.5px;}
.phase-body{padding:14px 18px 18px;}
table{width:100%;border-collapse:collapse;font-size:13.5px;}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;}
th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em;}
td.num{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;}
.why{color:var(--muted);font-size:12.5px;font-style:italic;}
.mono{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#0e7490;}
.decision-row{padding:12px 0;border-bottom:1px dashed var(--line);}
.decision-row:last-child{border-bottom:none;}
.decision-row .head{display:flex;align-items:center;gap:10px;}
.decision-row .head b{font-size:14.5px;}
.arrow{color:var(--accent);font-weight:750;}
details.art{background:#fbfcfe;border:1px solid var(--line);border-radius:12px;margin:10px 0;}
details.art>summary{cursor:pointer;padding:12px 16px;font-weight:650;font-size:13.5px;}
details.art pre{margin:0;padding:0 16px 16px;white-space:pre-wrap;word-wrap:break-word;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#24292f;}
.transition{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:6px;font-size:13px;}
.transition .kv{color:var(--muted);}
.transition .kv b{color:var(--ink);}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:40px;}
"""


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def render_html(data: dict[str, Any]) -> str:
    meta = data["meta"]
    dec = data["decomposition"]
    passes = sum(1 for f in data["feedback"] if f["verdict"] == "PASS")
    fails = sum(1 for f in data["feedback"] if f["verdict"] == "FAIL")

    parts: list[str] = []
    parts.append(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Horizon — Strong Run Decision Report</title><style>{_CSS}</style></head><body><div class="wrap">
<header class="top"><div class="eyebrow">Horizon · strategy layer · model {_esc(meta['model'])}</div>
<h1>Strong Run — every decision horizon took, and why</h1>
<p class="intent"><b>Decision:</b> {_esc(meta['decision'])}</p></header>
<div class="reverify"><h2>Decision vs execution &mdash; who owns what</h2>
<p style="color:var(--muted);font-size:13.5px;margin:8px 0 0">The <b>Decision</b> is horizon's strategic anchor (above). horizon decomposes it into goals and submits them; the employee owns the <b>how</b> &mdash; which data to use, what artifacts to produce &mdash; guided by its standing <b>brief</b>. When a goal struggles, horizon's lever is improving the brief or tools, never rewriting the decision.</p>
<details class="art"><summary>Employee brief &mdash; the context horizon set up (its generic lever)</summary><pre>{_esc(meta['brief'])}</pre></details>
<div class="overall"><span class="big">LOOP CLOSED</span><p>real LLM decomposition &rarr; {meta['goals_executed']} real Analyst beats &rarr;
horizon folded {passes + fails} real DoD verdict(s) ({passes} pass / {fails} fail) and re-prioritised every one.</p></div></div>
<div class="chips">
<div class="chip"><span>{meta['goals_produced']}</span>Goals produced (LLM)</div>
<div class="chip"><span>{meta['goals_executed']}</span>Real beats run</div>
<div class="chip"><span>{passes}/{fails}</span>Verdicts pass/fail</div>
<div class="chip"><span>{dec['input_tokens']}&#8202;/&#8202;{dec['output_tokens']}</span>Decompose tokens (in/out)</div>
<div class="chip"><span>{meta['llm_calls']}</span>LLM calls</div>
</div>"""
    )

    # Phase 1 — decompose
    parts.append(
        """<h2 class="sec">The decisions, phase by phase</h2>
<section class="phase"><div class="phase-head"><span class="pnum">1</span><div>
<h3>Decompose — Decision → Goals (LLM reasoning)</h3>
<p>horizon asks the model to break the decision into concrete, executable goals with a metric, target, rationale, and a priority score. This is the one non-deterministic decision — the raw prompt + raw completion are below.</p></div></div><div class="phase-body">"""
    )
    parts.append('<table><tr><th>#</th><th>score</th><th>goal</th><th>why (LLM rationale)</th></tr>')
    for i, g in enumerate(dec["goals"], 1):
        parts.append(
            f'<tr><td class="num">{i}</td><td class="num">{g["score"]:.2f}</td>'
            f'<td><b>{_esc(g["title"])}</b><br><span class="why">metric: {_esc(g["metric"])} · target: {_esc(g["target"])}</span></td>'
            f'<td class="why">{_esc(g["rationale"])}</td></tr>'
        )
    parts.append("</table>")
    parts.append(
        f'<details class="art"><summary>Raw LLM completion (verbatim) — {dec["output_tokens"]} output tokens</summary><pre>{_esc(dec["raw_completion"])}</pre></details>'
    )
    parts.append(
        f'<details class="art"><summary>Raw prompt sent to the model</summary><pre>{_esc(dec["prompt"])}</pre></details>'
    )
    parts.append("</div></section>")

    # Phase 2 — prioritise + submit
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">2</span><div>
<h3>Prioritise + Submit — Goals → chorus tasks</h3>
<p>For each goal horizon makes three deterministic decisions: the priority (score → bucket), the assignee, and an idempotency fingerprint. Then it opens exactly one chorus task.</p></div></div><div class="phase-body">"""
    )
    for s in data["submissions"]:
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(s["title"])}</b>'
            f'<span class="badge info">{_esc(s["priority"])}</span></div>'
            f'<div class="transition"><span class="kv">priority: <b>{_esc(s["priority_rule"])}</b></span>'
            f'<span class="kv">assignee: <b>{_esc(s["assignee_rule"])}</b></span></div>'
            f'<div class="transition"><span class="kv">fingerprint: <span class="mono">{_esc(s["fingerprint"])}</span></span>'
            f'<span class="kv">task: <span class="mono">{_esc(s["task_id"])}</span></span></div></div>'
        )
    parts.append("</div></section>")

    # Phase 3 — execute (real beats)
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">3</span><div>
<h3>Execute — real Analyst beats (chorus, not horizon)</h3>
<p>chorus runs each task as a real beat and renders a DoD verdict. horizon does not execute — it only observes the outcome. The employee owns the <em>how</em> and the artifacts; the raw verdict + whatever the Analyst chose to produce are below.</p></div></div><div class="phase-body">"""
    )
    for e in data["executions"]:
        ok = e["final_status"] == "done"
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(e["title"])}</b>'
            f'<span class="badge {"ok" if ok else "fail"}">{_esc(e["final_status"])}</span>'
            f'<span class="badge {"ok" if e["dod_status"]=="passed" else "warn"}">DoD {_esc(e["dod_status"])}</span></div>'
            f'<div class="transition"><span class="kv">status trail: <span class="mono">{_esc(" → ".join(e["status_trail"]))}</span></span></div>'
            f'<details class="art"><summary>Raw DoD verdict</summary><pre>{_esc(json.dumps(e["dod_verdict"], indent=2))}</pre></details>'
        )
        artifacts = e.get("artifacts", [])
        if artifacts:
            parts.append(
                f'<div class="why">Artifacts the Analyst chose to produce ({len(artifacts)}) — horizon prescribed none:</div>'
            )
            for a in artifacts:
                if a["binary"]:
                    parts.append(
                        f'<details class="art"><summary>{_esc(a["path"])} — binary, {a["bytes"]} bytes</summary></details>'
                    )
                else:
                    parts.append(
                        f'<details class="art"><summary>{_esc(a["path"])} — {a["bytes"]} bytes</summary><pre>{_esc(a["content"])}</pre></details>'
                    )
        else:
            parts.append('<div class="why">(no new artifacts detected in the worktree)</div>')
        parts.append("</div>")
    parts.append("</div></section>")

    # Phase 4 — feedback
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">4</span><div>
<h3>Feedback — landed verdict → health → re-priority</h3>
<p>The exact arithmetic horizon applied to each real outcome: health rule, score decay/bump, and the resulting priority change written back to chorus.</p></div></div><div class="phase-body">"""
    )
    if not data["feedback"]:
        parts.append('<p class="why">(no verdicts folded)</p>')
    for f in data["feedback"]:
        parts.append(
            f'<div class="decision-row"><div class="head"><b>{_esc(f["title"])}</b>'
            f'<span class="badge {"ok" if f["verdict"]=="PASS" else "fail"}">{_esc(f["verdict"])}</span></div>'
            f'<div class="transition"><span class="kv">health: <b>{_esc(f["health_before"])} <span class="arrow">→</span> {_esc(f["health_after"])}</b> <span class="why">({_esc(f["health_rule"])})</span></span></div>'
            f'<div class="transition"><span class="kv">score: <b>{f["score_before"]:.2f} <span class="arrow">→</span> {f["score_after"]:.2f}</b> <span class="why">({_esc(f["score_rule"])})</span></span></div>'
            f'<div class="transition"><span class="kv">priority: <b>{_esc(f["priority_before"])} <span class="arrow">→</span> {_esc(f["priority_after"])}</b></span></div></div>'
        )
    parts.append("</div></section>")

    # Phase 5 — final direction
    parts.append(
        """<section class="phase"><div class="phase-head"><span class="pnum">5</span><div>
<h3>Final direction (the read model)</h3>
<p>The whole decision after the loop — every goal with its current score, priority, health, and realizing task.</p></div></div><div class="phase-body">"""
    )
    parts.append('<table><tr><th>score</th><th>priority</th><th>health</th><th>goal</th><th>task</th></tr>')
    for d in data["direction"]:
        parts.append(
            f'<tr><td class="num">{d["score"]:.2f}</td><td>{_esc(d["priority"])}</td>'
            f'<td>{_esc(d["health"])}</td><td>{_esc(d["title"])}</td>'
            f'<td class="mono">{_esc(d["task_id"]) if d["task_id"] else "—"}</td></tr>'
        )
    parts.append("</table></div></section>")

    parts.append(
        f'<footer>Generated {_esc(meta["generated"])} from a live horizon run · model {_esc(meta["model"])} (Azure) · Press E to expand all.</footer>'
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
    out_dir = Path(__file__).resolve().parent.parent / "reports" / "strong-test"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    html_path = out_dir / "horizon-flow-report.html"
    html_path.write_text(render_html(data), encoding="utf-8")
    print(f"\nreport: {html_path}")
    print(f"data:   {out_dir / 'data.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
