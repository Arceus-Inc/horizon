"""Company loop e2e — the flat org runs "Latch" for N cycles, watched live in a browser.

The continuous loop from the architecture: each cycle the CEO governance beat adjudicates
proposals (approve → decision + goals + intake tasks, all inside horizon's promote path),
the composition root routes each new task to a worker by tag (API:→Bex, Web:→Fay,
Brief:→Ada) with an explicit pytest DoD (no reviewer in this org), the chorus heartbeat
runs the worker beats in parallel, outcomes move goal health/score and reprioritise tasks,
and the next cycle's proposals cite this cycle's real artifacts as evidence.

Every event is appended to ``reports/company-loop/events.jsonl`` as it happens and a tiny
HTTP server serves ``dashboard.html`` next to it — open the printed URL and watch the run
live, one lane per repo (horizon / chorus / dream / lattice).

    uv run python examples/company_loop_e2e.py       # needs AZURE_OPENAI_* (skips cleanly)

Knobs: COMPANY_CYCLES (3) · COMPANY_BEAT_TIMEOUT_S (240) · COMPANY_MAX_TICKS (6 per cycle)
· COMPANY_PORT (8321) · COMPANY_HOLD_S (900, keep serving after the run).
"""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import dream  # noqa: E402
from chorus.events import Event, EventKind  # noqa: E402
from chorus.facade import Caps, Chorus  # noqa: E402
from chorus.memory import EpisodicStore  # noqa: E402
from chorus.observability import EventBus  # noqa: E402
from chorus.outcomes import AgentReview, Verifier  # noqa: E402
from chorus.roles import RoleRegistry, default_roles  # noqa: E402
from chorus.roles._plugin import RolePlugin  # noqa: E402
from chorus_employee import default_landers  # noqa: E402
from chorus_employee.ceo import ceo_plugin  # noqa: E402
from chorus_harness import EmployeeHarnessFactory  # noqa: E402
from chorus_tools._lattice_bridge import build_lattice_for_chorus  # noqa: E402
from lattice.directive import DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_NEW_EPISODES  # noqa: E402

from examples.chorus_bridge import (  # noqa: E402
    ChorusGoalStore,
    ChorusIntakePort,
    ChorusOutcomeFeed,
)
from horizon import Horizon  # noqa: E402
from horizon.generation import CandidateGoal, DirectionBrief, ProposalStore  # noqa: E402
from horizon.governance import HorizonGovernance  # noqa: E402
from horizon.store import DecisionStore, StrategyStore  # noqa: E402

_CYCLES = int(os.environ.get("COMPANY_CYCLES", "3"))
_BEAT_TIMEOUT_S = float(os.environ.get("COMPANY_BEAT_TIMEOUT_S", "240"))
_MAX_TICKS = int(os.environ.get("COMPANY_MAX_TICKS", "6"))
_PORT = int(os.environ.get("COMPANY_PORT", "8321"))
_HOLD_S = float(os.environ.get("COMPANY_HOLD_S", "900"))

_REPORT_DIR = _REPO_ROOT / "reports" / "company-loop"
_WORKER_ROLES = ("backend_engineer", "frontend_engineer", "analyst")
_TAG_TO_WORKER = {"API:": "bex", "Web:": "fay", "Brief:": "ada"}
_PYTEST_DOD = "python -m pytest -q"

# -- the company: Latch, a URL shortener for indie creators -----------------------------------

_CEO_INTENT = (
    "You are the CEO of Latch, a URL-shortener product for indie creators. Review the "
    "company's direction and adjudicate its open proposals, then record your decisions in "
    "directive.md.\n\n"
    "Use governance_read to see decisions, their goals (with health and priority), and the "
    "open proposals — that tool is your only source of truth; do not search the repository. "
    "Approve each well-evidenced proposal with proposal_approve; reject each weak or "
    "off-strategy one with proposal_reject (short reason). If a goal's health or priority "
    "looks wrong, adjust it with goal_set_priority (low, medium, high); archive goals that "
    "are clearly finished with goal_archive.\n\n"
    "Your deliverable is directive.md — overwrite it: current decisions up top; for each "
    "proposal you adjudicated IN THIS BEAT its id and a one-line reason (earlier beats' "
    "decisions need only a brief standing-direction summary, not per-id coverage); the key "
    "risks with one guardrail each; and ranked next actions. That file is the finished work."
)


def _goal(title: str, score: float) -> CandidateGoal:
    return CandidateGoal(
        title=title, metric="shipped increment", target="done this cycle",
        rationale="smallest useful slice", score=score,
    )


def _brief(recommendation: str, *, conf: float, evidence: list[str],
           goals: list[CandidateGoal]) -> DirectionBrief:
    return DirectionBrief(
        candidate_id="c", recommendation=recommendation,
        rationale="grounded in what the company has actually shipped so far",
        confidence=conf, risks=["small team, one cycle of runway per bet"],
        candidate_goals=goals, evidence_refs=evidence,
    )


def _cycle_briefs(cycle: int, evidence: list[str]) -> tuple[DirectionBrief, DirectionBrief]:
    """(strong, weak) proposals per cycle — later cycles cite earlier cycles' real artifacts."""
    if cycle == 1:
        strong = _brief(
            "Ship the Latch MVP: shorten + resolve, a landing page, and a launch price",
            conf=0.85, evidence=["market:indie-creators", "prior-art:dub.co", "team:ready"],
            goals=[
                _goal(
                    "API: Create package src/latch/ with shortener.py — a Shortener class "
                    "where shorten(url: str) returns a stable 8-char slug and resolve(slug) "
                    "returns the original url (unknown slug raises KeyError). Add "
                    "tests/test_shortener.py with 3 pytests. Make the tests pass.", 0.9),
                _goal(
                    "Web: Create site/index.html — a clean landing page for Latch, the URL "
                    "shortener for indie creators: hero headline, 3 feature bullets, and a "
                    "pricing teaser. Add tests/test_site.py with a pytest asserting the file "
                    "exists and mentions Latch. Make the tests pass.", 0.75),
                _goal(
                    "Brief: Write research/pricing-brief.md comparing the pricing of three "
                    "URL-shortener competitors from your own knowledge (e.g. Bitly, Dub, "
                    "TinyURL) and recommend a launch price for Latch Pro. Add "
                    "tests/test_brief.py with a pytest asserting the file exists and names "
                    "3 competitors. Make the tests pass.", 0.6),
            ],
        )
        weak = _brief(
            "Rebrand the company logo before we have a product", conf=0.45,
            evidence=["opinion:one-tweet"], goals=[_goal("Web: redesign the logo", 0.4)],
        )
    elif cycle == 2:
        strong = _brief(
            "Add click analytics to Latch — creators want to see what their links do",
            conf=0.8, evidence=evidence or ["cycle1:landed"],
            goals=[
                _goal(
                    "API: Extend src/latch/shortener.py with click tracking — record(slug) "
                    "increments a per-slug counter and stats(slug) returns it (0 for a fresh "
                    "slug). Extend the tests. Keep all prior tests passing.", 0.85),
                _goal(
                    "Brief: Write research/analytics-kpis.md defining 5 launch KPIs for "
                    "Latch, each with a target number. Add a pytest asserting the file "
                    "lists 5 KPIs. Make the tests pass.", 0.55),
            ],
        )
        weak = _brief(
            "Sponsor a developer-conference booth this quarter", conf=0.4,
            evidence=["opinion:sales-deck"], goals=[_goal("Brief: booth plan", 0.3)],
        )
    else:
        strong = _brief(
            "Prepare the public launch of Latch", conf=0.78, evidence=evidence or ["cycle2:landed"],
            goals=[
                _goal(
                    "Web: Add a pricing section to site/index.html — a Free tier and a "
                    "Latch Pro tier at $5/mo with 3 benefits. Update tests/test_site.py to "
                    "assert the pricing section exists. Make the tests pass.", 0.8),
                _goal(
                    "Brief: Write research/launch-post.md — a ~300-word launch announcement "
                    "for Latch. Add a pytest asserting the file has more than 200 words. "
                    "Make the tests pass.", 0.5),
            ],
        )
        weak = _brief(
            "Acquire a smaller competitor instead of launching", conf=0.35,
            evidence=["rumor"], goals=[_goal("Brief: acquisition memo", 0.3)],
        )
    return strong, weak


# -- live event log + dashboard ----------------------------------------------------------------

class EventLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.write_text("", encoding="utf-8")

    def emit(self, component: str, kind: str, title: str, *, cycle: int = 0,
             detail: str = "", employee: str = "", task: str = "") -> None:
        row = {
            "ts": datetime.now(UTC).strftime("%H:%M:%S"),
            "cycle": cycle, "component": component, "kind": kind, "title": title[:200],
            "detail": detail[:900], "employee": employee, "task": task,
        }
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        sys.stdout.write(f"[{row['ts']}] c{cycle} {component:<7} {title[:110]}\n")
        sys.stdout.flush()


class _DashboardBus(EventBus):
    """Chorus EventBus that mirrors run/beat telemetry into the live event log."""

    def __init__(self, log: EventLog) -> None:
        super().__init__(log_path=None)
        self.log = log
        self.cycle = 0
        self.task_owner: dict[str, str] = {}

    def emit(self, event: Event) -> None:
        self.mirror(event)
        super().emit(event)

    def mirror(self, event: Event) -> None:
        """Also usable directly as a dream run_task observer (CEO beats bypass the scheduler)."""
        with contextlib.suppress(Exception):
            self._mirror(event)

    def _mirror(self, event: Event) -> None:
        p = event.payload
        task = event.task_id or ""
        who = self.task_owner.get(task, str(p.get("employee_id", "")))
        if event.kind is EventKind.RUN_STARTED:
            self.log.emit("dream", "beat", "beat started", cycle=self.cycle,
                          employee=who, task=task, detail=str(p.get("run_id", "")))
        elif event.kind is EventKind.RUN_TOOL_USE:
            self.log.emit("dream", "tool", f"→ {p.get('tool')}", cycle=self.cycle,
                          employee=who, task=task, detail=str(p.get("input", ""))[:300])
        elif event.kind is EventKind.RUN_TOOL_RESULT and bool(p.get("is_error")):
            self.log.emit("dream", "error", f"✗ {p.get('tool')} error", cycle=self.cycle,
                          employee=who, task=task, detail=str(p.get("content_preview", "")))
        elif event.kind is EventKind.RUN_TEXT:
            text = str(p.get("text", "")).strip()
            if len(text) >= 60:
                self.log.emit("dream", "text", "role.text", cycle=self.cycle,
                              employee=who, task=task, detail=text[:400])
        elif event.kind is EventKind.RUN_EVALUATED:
            self.log.emit("chorus", "verdict", f"verdict: {p.get('outcome', p.get('passed'))}",
                          cycle=self.cycle, employee=who, task=task,
                          detail=json.dumps({k: str(v)[:120] for k, v in p.items()}))
        elif event.kind is EventKind.TASK_STATUS:
            self.log.emit("chorus", "status", f"task → {p.get('status')}", cycle=self.cycle,
                          employee=who, task=task)


_DASHBOARD_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Latch — company loop</title><style>
body{margin:0;font:14px/1.5 -apple-system,"Helvetica Neue",Arial,sans-serif;background:#111312;color:#e8e6df}
header{position:sticky;top:0;background:#181b1a;border-bottom:1px solid #2a2e2c;padding:12px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;font-weight:600;margin:0}
.chip{padding:2px 10px;border-radius:999px;font-size:12px;border:1px solid #3a3f3d;cursor:pointer;user-select:none}
.chip.on{background:#2a2e2c}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
#status{font-size:12px;color:#9aa09c;margin-left:auto}
#feed{padding:12px 20px 60px;max-width:1100px;margin:0 auto}
.ev{display:flex;gap:10px;padding:5px 8px;border-left:3px solid #333;margin:2px 0;background:#161918;border-radius:0 6px 6px 0;align-items:baseline}
.ev .ts{color:#6f7672;font-size:11px;min-width:56px}
.ev .cy{font-size:11px;color:#9aa09c;min-width:24px}
.ev .who{font-size:11px;color:#c9cec9;min-width:44px}
.ev .ti{flex:0 0 auto}
.ev .de{color:#9aa09c;font-size:12px;white-space:pre-wrap;word-break:break-word;flex:1;min-width:0}
.horizon{border-color:#D85A30}.chorus{border-color:#1D9E75}.dream{border-color:#7F77DD}
.lattice{border-color:#D4537E}.run{border-color:#B4B2A9}
.k-error .ti{color:#F09595}.k-check-pass .ti{color:#97C459}.k-check-fail .ti{color:#F09595}
.k-beat .ti{color:#AFA9EC}.k-verdict .ti{color:#5DCAA5}
#knobs{font-size:12px;color:#9aa09c;padding:8px 20px;border-bottom:1px solid #2a2e2c;display:none;white-space:pre-wrap}
</style></head><body>
<header><h1>Latch — company loop</h1>
<span class="chip on" data-f="all">all</span>
<span class="chip on" data-f="horizon"><span class="dot" style="background:#D85A30"></span>horizon</span>
<span class="chip on" data-f="chorus"><span class="dot" style="background:#1D9E75"></span>chorus</span>
<span class="chip on" data-f="dream"><span class="dot" style="background:#7F77DD"></span>dream</span>
<span class="chip on" data-f="lattice"><span class="dot" style="background:#D4537E"></span>lattice</span>
<span class="chip" id="knobBtn">knobs</span>
<span class="chip on" id="follow">follow</span>
<span id="status">connecting…</span></header>
<div id="knobs"></div><div id="feed"></div>
<script>
let seen=0,on={all:1,horizon:1,chorus:1,dream:1,lattice:1,run:1},follow=1;
const feed=document.getElementById('feed'),status=document.getElementById('status');
document.querySelectorAll('.chip[data-f]').forEach(c=>c.onclick=()=>{const f=c.dataset.f;
 if(f==='all'){const v=!on.all;Object.keys(on).forEach(k=>on[k]=v);document.querySelectorAll('.chip[data-f]').forEach(x=>x.classList.toggle('on',v));}
 else{on[f]=!on[f];c.classList.toggle('on',on[f]);}
 document.querySelectorAll('.ev').forEach(e=>e.style.display=on[e.dataset.c]?'flex':'none');});
document.getElementById('follow').onclick=e=>{follow=!follow;e.target.classList.toggle('on',follow);};
document.getElementById('knobBtn').onclick=()=>{const k=document.getElementById('knobs');k.style.display=k.style.display==='block'?'none':'block';};
function row(e){const d=document.createElement('div');d.className='ev '+e.component+' k-'+e.kind;d.dataset.c=e.component;
 d.style.display=on[e.component]?'flex':'none';
 d.innerHTML='<span class="ts">'+e.ts+'</span><span class="cy">'+(e.cycle?('c'+e.cycle):'')+'</span>'+
 '<span class="who">'+(e.employee||'')+'</span><span class="ti"></span><span class="de"></span>';
 d.querySelector('.ti').textContent=e.title;d.querySelector('.de').textContent=e.detail||'';return d;}
async function poll(){try{
 const r=await fetch('events.jsonl?_='+Date.now(),{cache:'no-store'});const t=await r.text();
 const lines=t.split('\\n').filter(Boolean);
 if(lines.length>seen){for(let i=seen;i<lines.length;i++){const e=JSON.parse(lines[i]);
  if(e.kind==='knobs'){document.getElementById('knobs').textContent=e.detail;continue;}
  feed.appendChild(row(e));}
  seen=lines.length;if(follow)window.scrollTo(0,document.body.scrollHeight);}
 const last=lines.length?JSON.parse(lines[lines.length-1]):null;
 status.textContent=lines.length+' events'+(last&&last.kind==='finished'?' — run finished':' — live');
}catch(err){status.textContent='stream ended ('+seen+' events)';}
setTimeout(poll,1500);}poll();
</script></body></html>
"""


def _serve(directory: Path, port: int) -> socketserver.TCPServer:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    handler.log_message = lambda *a, **k: None  # type: ignore[method-assign]
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# -- run helpers --------------------------------------------------------------------------------

def _seed(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# latch seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-qm", "init"],
        check=True, capture_output=True,
    )


def _short_beat_plugins(timeout_s: float) -> list[RolePlugin]:
    plugins: list[RolePlugin] = []
    for plugin in default_roles():
        if plugin.name not in _WORKER_ROLES:
            plugins.append(plugin)
            continue
        manifest = replace(plugin.manifest, beat_timeout_s=timeout_s, lease_ttl_s=timeout_s + 90.0)
        plugins.append(RolePlugin(
            name=plugin.name, manifest=manifest, dod_generator=plugin.dod_generator,
            outcome_kind=plugin.outcome_kind, declared_routines=plugin.declared_routines,
            replace=True,
        ))
    return plugins


def _horizon_tasks(ledger: Any) -> dict[str, str]:
    rows = ledger._conn.execute(
        "SELECT id, intent FROM task WHERE origin_kind = 'horizon_intake'"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base_url and deployment):
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (_REPORT_DIR / "dashboard.html").write_text(_DASHBOARD_HTML, encoding="utf-8")
    log = EventLog(_REPORT_DIR / "events.jsonl")
    httpd = _serve(_REPORT_DIR, _PORT)
    print(f"\n*** live dashboard: http://127.0.0.1:{_PORT}/dashboard.html ***\n")

    stamp = datetime.now(UTC).strftime("%m%d-%H%M%S")
    company_id = f"latch-{stamp}"
    base = Path(tempfile.mkdtemp(prefix="company-loop-"))
    seed = base / "source"
    _seed(seed)

    plugins = _short_beat_plugins(_BEAT_TIMEOUT_S)
    registry = RoleRegistry.from_plugins(plugins)
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base_url, deployment=deployment,
        company_id=company_id, roles=registry, seed=seed, timeout_s=_BEAT_TIMEOUT_S,
    )
    bus = _DashboardBus(log)
    org = Chorus.build(
        db_path=str(base / "ledger.db"), org_repo=str(base / "org"),
        memory_repo=str(factory.company_root / "memory"), dream=dream,
        beat_runner_for=factory, landers=default_landers(factory.company_root),
        roles=plugins, company_id=company_id, caps=Caps(max_concurrent_runs=3),
    )
    org._event_bus = bus  # composition root: swap in the mirroring bus
    org._scheduler._event_bus = bus
    ledger = org._ledger

    decisions = DecisionStore(base / "decisions.json")
    strategy = StrategyStore(base / "strategy.json")
    horizon = Horizon(
        goals=ChorusGoalStore(org), intake=ChorusIntakePort(org),
        outcomes=ChorusOutcomeFeed(org), reasoner=None, decisions=decisions,
        strategy=strategy, proposals=ProposalStore(base / "proposals.json"),
        default_assignee=None,
    )
    gov = HorizonGovernance(horizon)
    ceo_factory = EmployeeHarnessFactory(
        api_key=key, base_url=base_url, deployment=deployment, company_id=company_id,
        roles=registry, ledger=ledger, governance=gov, timeout_s=600.0,
    )

    workers = {
        "bex": org.hire(name="Bex", role="backend_engineer"),
        "fay": org.hire(name="Fay", role="frontend_engineer"),
        "ada": org.hire(name="Ada", role="analyst"),
    }
    casey = org.hire(name="Casey", role="ceo")
    mat = ceo_factory.materialize(casey)
    stop_listener = horizon.start()

    knobs = {
        "run": {"cycles": _CYCLES, "beat_timeout_s": _BEAT_TIMEOUT_S,
                "max_ticks_per_cycle": _MAX_TICKS, "deployment": deployment},
        "chorus": {"max_concurrent_runs": 3, "tick_interval_s": 1.0,
                   "workers": "bex(backend) fay(frontend) ada(analyst)",
                   "dod_policy": "explicit command 'python -m pytest -q' (no reviewer)",
                   "org": "flat — no manager, no reviewer"},
        "horizon": {"score→priority": "ScorePolicy bands (≥0.8 high, mid medium, low)",
                    "score_decay_on_pass": 0.5, "assignee_routing": "tag → worker at root",
                    "intake": "idempotent (origin_fingerprint dedup)"},
        "dream": {"heads": "planner → generator → evaluator (oracle verdict)",
                  "ceo_timeout_s": 600},
        "lattice": {"gate_min_new_episodes": DEFAULT_MIN_NEW_EPISODES,
                    "gate_min_cluster_size": DEFAULT_MIN_CLUSTER_SIZE,
                    "expectation": "gate stays CLOSED for a 3-cycle run (cost policy)"},
    }
    log.emit("run", "knobs", "knob snapshot", detail=json.dumps(knobs, indent=1))
    log.emit("run", "start", f"company {company_id} — {_CYCLES} cycles",
             detail=f"root {factory.company_root}")

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "", cycle: int = 0) -> None:
        checks.append((name, ok, detail))
        log.emit("run", "check-pass" if ok else "check-fail",
                 f"[{'PASS' if ok else 'FAIL'}] {name}", cycle=cycle, detail=detail)

    verifier = ceo_plugin().dod_generator(_CEO_INTENT)
    rubric = verifier.spec.rubric if isinstance(verifier.spec, AgentReview) else ""
    seen_tasks: dict[str, str] = {}
    evidence: list[str] = []

    for cycle in range(1, _CYCLES + 1):
        bus.cycle = cycle
        log.emit("run", "cycle", f"— cycle {cycle} —", cycle=cycle)

        strong_brief, weak_brief = _cycle_briefs(cycle, evidence)
        strong = horizon.reconcile([strong_brief])[0]
        weak = horizon.reconcile([weak_brief])[0]
        log.emit("horizon", "proposal", f"proposed: {strong_brief.recommendation[:80]}",
                 cycle=cycle, detail=f"{strong.id} conf={strong_brief.confidence} "
                 f"evidence={strong_brief.evidence_refs}")
        log.emit("horizon", "proposal", f"proposed: {weak_brief.recommendation[:80]}",
                 cycle=cycle, detail=f"{weak.id} conf={weak_brief.confidence}")

        log.emit("dream", "beat", "CEO governance beat starting", cycle=cycle, employee="casey")
        outcome = await mat.runner.run_task(
            task_id=f"gov-c{cycle}", intent=_CEO_INTENT, run_id=f"run-gov-c{cycle}-{stamp}",
            rubric=rubric, observer=bus.mirror,
        )
        props = {p.id: p.status for p in horizon.list_proposals(status=None)}
        log.emit("horizon", "adjudicated",
                 f"strong={props.get(strong.id)} weak={props.get(weak.id)}",
                 cycle=cycle, employee="casey",
                 detail=f"CEO beat passed={outcome.passed} · {getattr(outcome, 'summary', '')}")
        check(f"c{cycle} strong proposal approved", props.get(strong.id) == "approved",
              str(props.get(strong.id)), cycle)
        check(f"c{cycle} weak proposal rejected", props.get(weak.id) == "rejected",
              str(props.get(weak.id)), cycle)
        check(f"c{cycle} CEO beat passed DoD", bool(outcome.passed),
              str(getattr(outcome, "summary", "")), cycle)
        directive = mat.working_dir / "directive.md"
        if directive.is_file():
            log.emit("horizon", "directive", f"directive.md v{cycle}", cycle=cycle,
                     employee="casey", detail=directive.read_text(encoding="utf-8")[:800])
        check(f"c{cycle} directive.md written", directive.is_file(), cycle=cycle)

        all_tasks = _horizon_tasks(ledger)
        fresh = {tid: intent for tid, intent in all_tasks.items() if tid not in seen_tasks}
        seen_tasks = all_tasks
        cycle_tasks: dict[str, str] = {}
        for tid, intent in fresh.items():
            tag = next((t for t in _TAG_TO_WORKER if intent.startswith(t)), None)
            if tag is None:
                log.emit("chorus", "error", f"no route for task {tid}", cycle=cycle,
                         detail=intent[:200])
                continue
            worker = _TAG_TO_WORKER[tag]
            ledger.dod.create(tid, Verifier.command(_PYTEST_DOD, artifact_class="pr"))
            org.assign(tid, workers[worker].id)
            bus.task_owner[tid] = worker
            cycle_tasks[tid] = worker
            task = ledger.tasks.get(tid)
            prio = task.priority.value if task is not None else "?"
            log.emit("chorus", "intake", f"task → {worker} ({prio})",
                     cycle=cycle, employee=worker, task=tid, detail=intent[:220])
        check(f"c{cycle} approval produced tasks", bool(cycle_tasks),
              f"{len(cycle_tasks)} task(s)", cycle)

        for tick in range(_MAX_TICKS):
            await org.tick()
            await org.drain()
            statuses = {
                t: (x.status.value if (x := ledger.tasks.get(t)) is not None else "?")
                for t in cycle_tasks
            }
            log.emit("chorus", "tick", f"tick {tick + 1}: {statuses}", cycle=cycle)
            if all(s in {"done", "failed", "cancelled", "rejected"} for s in statuses.values()):
                break
        done = [t for t in cycle_tasks
                if (x := ledger.tasks.get(t)) is not None and x.status.value == "done"]
        check(f"c{cycle} all worker tasks done", len(done) == len(cycle_tasks),
              f"{len(done)}/{len(cycle_tasks)}", cycle)
        evidence = [f"landed:cycle{cycle}:{t}" for t in done]

        approved = [p for p in horizon.list_proposals(status="approved")]
        for p in approved:
            if p.linked_decision_id is None:
                continue
            decision = decisions.get(p.linked_decision_id)
            if decision is None:
                continue
            for gid in decision.goal_ids:
                view = horizon.goal_view(gid)
                if view is not None:
                    log.emit("horizon", "health", f"goal {view.health} score={view.score}",
                             cycle=cycle, detail=f"{gid} · {view.title[:90]}")
        lattice = build_lattice_for_chorus(factory.company_root)
        store = EpisodicStore(factory.company_root / "memory")
        for slug, emp in workers.items():
            count = len(store.records_for(emp.id))
            gate = lattice.gate_open(emp.id)
            log.emit("lattice", "gate", f"{slug}: gate {'OPEN' if gate else 'closed'} "
                     f"({count}/{DEFAULT_MIN_NEW_EPISODES} episodes)", cycle=cycle,
                     employee=slug)
        check(f"c{cycle} episodic captured for done beats",
              sum(len(store.records_for(e.id)) for e in workers.values()) >= len(done),
              cycle=cycle)

    dedup_before = len(_horizon_tasks(ledger))
    for p in horizon.list_proposals(status="approved"):
        if p.linked_decision_id:
            with contextlib.suppress(Exception):
                horizon.submit_decision(p.linked_decision_id)
    check("intake idempotent across cycles", len(_horizon_tasks(ledger)) == dedup_before,
          f"{dedup_before} tasks before and after resubmit")

    stop_listener()
    passed = sum(1 for _, ok, _ in checks if ok)
    result = {"company_id": company_id, "cycles": _CYCLES, "passed": passed,
              "total": len(checks), "all_pass": passed == len(checks),
              "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]}
    (_REPORT_DIR / "data.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.emit("run", "finished", f"RESULT: {'PASS' if result['all_pass'] else 'FAIL'} "
             f"({passed}/{len(checks)})", detail=json.dumps(result["checks"], indent=1))
    print(f"\nRESULT: {'PASS' if result['all_pass'] else 'FAIL'} ({passed}/{len(checks)})")
    print(f"dashboard stays live for {_HOLD_S:.0f}s: http://127.0.0.1:{_PORT}/dashboard.html")
    await asyncio.sleep(_HOLD_S)
    httpd.shutdown()
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
