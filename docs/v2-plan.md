# Horizon v2 — Build Plan

> **Status:** v1.0 shipped (M1–M3) + a hardening pass (recovery · staleness · structured outputs · full-transparency reporting). This plan sets the **next** altitude of work — planned with the cofounder, 2026-07-10.
> `dream` completes one task · `chorus` runs the org that ships one sprint · **`horizon` decides what the company should do next** — and now closes the loop when the work lands.

v1 proved the **spine works end-to-end**: a Decision decomposes into Goals, Goals become chorus intake at a
score-derived priority, and landed DoD verdicts fold back into goal health + re-prioritisation — with a
recovery loop that pushes goals to completion. v2 makes each turn of that loop **mean more** (better
signals), **reach wider** (portfolio + team), **originate itself** (evidence, not hand-seeding), and become
**steerable by a human** (the CEO chat) — without ever breaking the v1 invariants.

This document is the v2 build plan: what shipped, the four themes, the cross-cutting track, the milestones,
and the decisions locked (and still open).

---

## 0. Where v1 landed (the baseline v2 builds on)

Shipped and proven live (Azure OpenAI `gpt-5.2`):

| Capability | Surface | State |
|---|---|---|
| Decision → Goals decomposition | `Horizon.decompose` · `planning.Decomposer` | LLM, **strict `json_schema`** outputs, grounded in `decompose_context`, tolerant retry |
| Prioritise + submit | `Horizon.submit_decision` · `intake.Submitter` / `Prioritiser` | idempotent on `goal_id` + intent fingerprint; score → `Priority` |
| Outcome feedback | `Horizon.start` / `note_outcome` · `feedback.OutcomeListener` | folds landed DoD verdicts → health + re-priority; observable `handled/dropped/deferred` |
| Health + drift | `feedback.HealthPolicy` · `Horizon.sweep_staleness` | on_track / drifting / blocked from pass-rate; staleness clock re-surfaces stale goals |
| Recovery loop | `Horizon.recover` | diagnostic-carrying retry, **reuses prior worktree work**, bounded, end-to-end |
| Direction read model | `Horizon.state` / `goal_view` · `reporting.render_direction` | live per-goal score/priority/health/status/task |
| Full-transparency report | `examples/strong_run.py` | raw prompt + completion, score→priority + health arithmetic, real verdicts, **per-employee tools & operations log** |

**Invariants carried forward unchanged** (§3 of v1-plan): no sideways import; ownership split (chorus owns
execution data, horizon owns strategy); horizon never schedules; direction is a write, back-pressure is a
read; outcomes-not-prose; bounded beats only; one intake door.

---

## 1. The four themes

v2 is organized into four themes plus a cross-cutting track. Recommended build order is **A → B → C → D**,
because A deepens what just shipped (in-repo, immediate value), B is the first structural widening (one
cross-repo push), and C/D are the original M4/M5 that assume A/B exist.

```
A. Deepen the loop      (make outcomes mean more)      — mostly in-repo
B. Widen the loop       (portfolio + team)             — one cross-repo push (the manager)
C. Originate direction  (M4 generation funnel)         — evidence → proposed decisions
D. Control surface      (M5 CEO chat)                  — human steering, confirm-to-write
X. Cross-cutting        (observability + self-eval)    — runs alongside all of the above
```

---

## Theme A — Deepen the loop *(make outcomes mean more)*

Today feedback is binary: a task passed or failed. Theme A makes horizon reason about **the number**, **the
lever**, and **the decision** — the highest-leverage next work because it extends the loop we already have
and needs no chorus changes.

### A1 · Metric-aware outcomes
**What.** Goals already carry `metric` + `target` (produced by the decomposer), but `OutcomeListener` only
reads DoD pass/fail. Introduce a **metric reading** on each landed outcome and judge health against the
*target*, not just task completion.

**Why.** "The task passed" ≠ "the strategy is working." A goal can ship clean work that fails to move the
number. Metric-aware health is the difference between measuring *activity* and measuring *progress*.

**Scope.**
- Extend `StrategyRecord` with `metric_value`, `metric_history: list[(ts, value)]`, `target`, and a
  `to_target` distance.
- A `MetricReading` shape on `OutcomeEvent` (or a sidecar `MetricFeed` port) — where does the number come
  from? v2 default: the analyst's landed artifact reports it in a typed block (structured output), read at
  fold time.
- `HealthPolicy` gains a target-aware rule: `on_track` requires both a passing DoD **and** movement toward
  target; a passing DoD that stalls the metric → `drifting`.
- `goal_view` / `render_direction` show `metric: current → target (Δ)`.

**Proves.** Direction is driven by business outcomes, not task counts.

**Seam impact.** In-repo, plus a small structured-output convention for the analyst (no chorus code change).

### A2 · Recovery escalation *(change the lever, don't just retry)*
**What.** `recover()` re-attempts with the diagnostic. Add an **escalation ladder**: after each failed
attempt, horizon changes a *lever* rather than repeating the same shape —
1. retry with diagnostic (today),
2. enrich the brief / add allowed context,
3. re-decompose the goal into a different shape,
4. escalate to a human (flag `needs_human`).

**Why.** Blind retries waste beats on a goal that's failing for a structural reason. The whole point of a
strategy layer is to *change the approach*, not hammer the same one.

**Scope.**
- `StrategyRecord.escalation_level` (0–3) advanced on each fold-with-fail.
- A policy object `RecoveryPolicy` mapping level → lever (retry / enrich-brief / re-decompose / human).
- `recover()` reads the level and applies the corresponding lever; the re-submitted intent (or re-decompose
  call) reflects it.
- `needs_human` surfaces in `state()` / the report.

**Proves.** The system adapts strategy on repeated failure instead of looping.

**Seam impact.** In-repo (re-decompose reuses the existing `Decomposer`).

### A3 · Decision re-evaluation *(feedback flows all the way up)*
**What.** When a decision's goals **persistently** fail/drift (e.g. a majority blocked past max escalation),
bubble the signal to the **decision** — flag it `needs_review` with the aggregated evidence.

**Why.** The v1 plan reserved the top of the spine for "rarely, a decision re-evaluation." This is that
rarely: sometimes the goals are fine and the *decision* is wrong.

**Scope.**
- `DecisionState` gains `needs_review` + a `review_reason` (aggregated from child records).
- A `Horizon.review_decisions()` sweep (like `sweep_staleness`) that aggregates child health and flags.
- Report/CLI surface the flagged decision with its evidence.

**Proves.** The loop can question the strategy, not just the work. (Acting on the flag is human — see D.)

---

## Theme B — Widen the loop *(one decision / one employee → portfolio / team)*

v1 operates at **one decision, one employee, leaf-goal = one task**. Theme B lifts all three limits.

### B1 · Goal → multi-task splitting (the "manager") — *the big one*
**What.** Introduce the **manager** that splits a leaf goal into multiple dependent tasks
(`backend / frontend / design`) assigned across employees — the piece v1 explicitly deferred.

**Why.** The single-Analyst ceiling is the main thing between horizon and driving *real* org work. This is
the structural unlock for everything team-shaped.

**Scope (cross-repo).**
- **chorus:** a manager that, given a `goal_id`, emits several linked `task` rows with dependencies (this is
  chorus-side execution structure — horizon does not schedule).
- **horizon:** the decomposer/submitter learn a **goal can fan out**; `StrategyRecord` tracks a goal with
  *many* task_ids; the listener folds a goal's health from *all* its tasks' verdicts (not one).
- Health aggregation: a goal is `done` when its tasks' DoD are all passed; `blocked` if any hard-blocks.

**Proves.** Horizon drives multi-person work, not a single Analyst.

**Seam impact.** First real cross-repo push of v2 (chorus manager + a `GoalStore`/intake fan-out shape).
Additive, matching the v1 seam discipline.

### B2 · Multi-decision portfolio
**What.** Manage the sprint's **1–3 concurrent decisions** with cross-decision ranking and a portfolio-level
direction view.

**Why.** Real sprints juggle a few bets at once; horizon must rank *across* them, not just within one.

**Scope.**
- `Horizon.state()` returns a portfolio view (decisions × their goals) with cross-decision priority.
- A portfolio prioritiser that normalizes scores across decisions (respecting per-decision weight).
- Report/CLI: a portfolio summary above the per-decision detail.

**Proves.** Horizon holds the whole sprint's direction, not one decision.

### B3 · Capacity- & budget-aware prioritisation
**What.** Priority today is score-only. Factor in **employee capacity**, **cost/token budget**, and
**dependencies** so ranking reflects what the org can actually take on now.

**Why.** A high-value goal that no one has capacity for shouldn't sit at the top blocking throughput.

**Scope.**
- A `CapacitySignal` / `BudgetSignal` input (read from chorus ledger: in-flight load; from the ops log: token
  spend).
- `Prioritiser` blends score with capacity/budget headroom → an *effective* priority.
- Report shows why a goal's effective priority differs from its raw score.

**Proves.** Ranking reflects reality, not just desirability.

---

## Theme C — Originate direction *(the M4 generation funnel)*

From **hand-seeded** decisions to **evidence-generated** ones — strictly **proposal-only**, human-confirmed.
(This is the original M4, now assuming A/B exist so proposals land in a richer loop.)

### C1 · Source adapters + evidence packets
- A `SourceAdapter` Protocol + typed **evidence packets** (provenance / freshness / reliability).
- v1 sources: **internal** (chorus ledger/events) + human-seeded + **a web/market adapter** (external egress
  **behind a governance gate** + credentials).

### C2 · Scout beats
- A bounded `dream.run_task` **Scout** that reads adapters + the event stream → a normalized **candidate
  opportunity** (no unbounded trees; §3 invariant).

### C3 · Analyst → `DirectionBrief`
- **Reuse/extend chorus's `analyst`** employee, governed by horizon policy → a `DirectionBrief` (recommended
  edits, rationale, confidence, risks, candidate goals, proposed submit intents) behind an **evidence gate**.
- This is where the **department flow** lives (PM/analyst research → engineering goals).

### C4 · Reconciler
- Briefs → **proposed** decisions/goals. **Proposal-only in v2** — a human confirms (ties into D).

**Proves.** Direction generated from evidence, not hand-seeded.

---

## Theme D — Control surface *(the M5 CEO chat)*

A human steers the whole thing — **read + propose, confirm-to-write** (no auto-apply).

### D1 · Context assembler
- Assembles the tree · ledger · repo · product · metrics · memory · people · risk · commitments into a
  bounded context for the chat.

### D2 · Minimal chat surface
- Read/explain the **Decision → Goal → Task** tree; draft a decision or a `chorus.submit` intent.
- **All writes require explicit confirm/approval.** A direction-changing answer produces an **auditable tree
  diff** + evidence refs + a draft intent or decision record.

### D3 · Approve the funnel + re-eval flags
- The confirm surface is where C4's proposals and A3's `needs_review` flags get human sign-off.

**Capstone.** signals → scout → brief → reconcile → CEO review → submit → (manager fan-out) → execute →
metric-aware outcome → re-priority.

---

## Theme X — Cross-cutting *(observability + self-eval)*

Runs alongside A–D; each item is small but compounding.

- **X1 · Durable event log + replay.** The current EventBus has no log path, so `replay()` is empty. Give the
  bridge a log path so outcomes are replayable and horizon can rebuild state after a restart.
- **X2 · Decision-quality self-eval.** Evaluate horizon's *own* decomposition: was the goal set faithful to
  the decision? measurable? grounded? (a bounded eval beat over the decision + its goals).
- **X3 · Trend dashboards.** Persist health/score/priority history and render trends over time — extending
  the per-employee ops log already in the report.

---

## 2. Milestones (build order)

| Milestone | Contents | Cross-repo? | Ships |
|---|---|---|---|
| **M6 — Deepen** | A1 metric-aware outcomes · A2 recovery escalation | no | v2 signal quality |
| **M7 — Steer up** | A3 decision re-evaluation · B2 portfolio · X1 durable log | no | v2 breadth |
| **M8 — The manager** | B1 goal → multi-task split · B3 capacity/budget priority | **yes** (chorus) | v2 team-scale |
| **M9 — Generation funnel** | C1–C4 (scouts + analyst → DirectionBrief → reconcile) | yes (analyst) | evidence-driven direction |
| **M10 — CEO chat + capstone** | D1–D3 · X2 self-eval · X3 trends · capstone demo | yes | steerable, self-originating loop |

Each milestone stays **shippable on its own** and preserves the v1 invariants. Build **M6 first** — it turns
the loop we just proved into one that measures progress, and needs nothing outside horizon.

---

## 3. Locked decisions (v2)

| Decision | Choice |
|---|---|
| Order | **A → B → C → D**, cross-cutting X alongside; **M6 (deepen) first** |
| Metric source (A1) | Analyst reports the metric in a **typed/structured block**; horizon reads it at fold time (no chorus change) |
| Recovery levers (A2) | Ladder: retry → enrich brief → re-decompose → human; bounded, policy-driven |
| Decision re-eval (A3) | **Flag only** (`needs_review`); acting on it is human (Theme D) |
| The manager (B1) | Lives in **chorus** (execution structure); horizon only authors the goal + folds aggregated health |
| Generation funnel (C) | **Proposal-only**, evidence-gated, reuses chorus's analyst — unchanged from v1-plan M4 |
| CEO chat (D) | **Minimal**, read/explain + draft; **writes need confirm/approval** — unchanged from v1-plan M5 |
| Invariants | All v1 §3 invariants hold; no sideways import; horizon never schedules |

---

## 4. Open questions (defaults; override anytime)

- **Metric plumbing (A1):** typed analyst block (default) vs. a dedicated `MetricFeed` port. Start with the
  block; promote to a port if a second metric source appears.
- **Escalation thresholds (A2/A3):** how many failed attempts before each lever / before a decision is
  flagged? Default: escalate per attempt (levels 0–3); flag a decision when a majority of its goals reach
  level 3.
- **Portfolio weighting (B2):** equal weight vs. per-decision weight. Default: per-decision weight, equal if
  unset.
- **Capacity signal source (B3):** in-flight task count (default) vs. a richer chorus capacity API.
- **Manager fan-out authorship (B1):** who names the sub-tasks — the manager (default) or a horizon hint on
  the goal? Default: manager owns task shape; horizon owns the goal + its metric/target.
