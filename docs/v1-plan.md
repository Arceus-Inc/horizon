# Horizon v1 — Build Plan

> **Status:** M1 complete · direction sharpened to the **Decision → Goal → Task** spine (with cofounder, 2026-07-07)
> `dream` completes one task · `chorus` runs the org that ships one sprint · **`horizon` decides what the company should do next.**

Horizon is an **SDK** (like dream and chorus), not a running company. It ships the abstractions for a
strategy layer that decides *which* work should exist, at *what* priority, and *whether the company is
still aimed right* — turning strategy into **intake** and **back-pressure**, without ever touching the
scheduler or the agent loop.

This document is the v1 build plan: the spine, the goal, the invariants, the seam to chorus, the package
structure, the milestones, and the locked decisions.

---

## 1. The spine — Decision → Goal → Task

Our product operates at the **Decision** altitude — the way Claude Code operates at the **task** altitude
and goal-level tools sit one below. That altitude *is* the differentiator.

| Layer | What it is | Who owns it | Where it lives | Cadence |
|---|---|---|---|---|
| **Decision** | The sprint's strategic anchor, in natural language — *"build an AI note-taker for working professionals"*, *"gamify onboarding"* | **horizon** (proposed by user chat; funnel proposes only) | **horizon's own store — chorus never sees it** | slow: 1–3 per sprint, stable within a sprint, change on pivot |
| **Goal** | A decision decomposed into outcome-shaped work (dept-aware later: PM/analyst research → engineering goals) | **horizon** authors them | a chorus `goal` row (level `goal`) | churns within a sprint |
| **Task** | The executable unit a beat actually runs | **chorus** (+ a future **manager** splits a goal into tasks) | a chorus `task` row, `task.goal_id → goal` | continuous |

**Horizon's core job:** *turn Decisions into Goals.* Until a manager exists, a **leaf goal maps 1:1 to a
single task** submitted to the one employee; the manager that splits a goal into `backend / frontend /
design` tasks comes later. The **feedback loop flows up** the spine: task outcomes → goal health →
(rarely) a decision re-evaluation.

## 2. Goal (of the SDK)

A working `horizon` SDK that, running **in-process alongside chorus**, can:

1. **Own decisions** (horizon-native) and **decompose them into the goal tree** — the *why work exists*.
2. **Turn leaf goals into chorus intake** and steer `task.priority` (the *direction → intake* write).
3. **Close the feedback loop** — read landed outcomes, update goal health, re-prioritise (the *back-pressure* read).
4. **Generate direction from evidence** — opportunity scouts + the reused analyst producing a `DirectionBrief`.
5. **Expose a CEO-chat control surface** — read/explain the tree + draft submit intents (writes gated).

…all **without importing chorus** and **without running the schedule**. v1 operates at **one-employee
level**.

## 3. Invariants (load-bearing)

- **No sideways import.** chorus, horizon, lattice never import each other. They meet only at the **data
  layer** (the `goal` table, `task.priority`, the event stream) and at **`dream.contracts` Protocols**.
- **Ownership split.** chorus owns the **execution data** (goals + tasks + the event bus). horizon owns
  the **strategy** — **decisions** (horizon-native), the decision→goal map, the ranking/fingerprint/
  outcome-interpretation policy, and the strategy-only fields. **Decisions never enter chorus.**
- **Horizon never schedules or dispatches.** It only *writes* `goal` rows and `task.priority`; chorus's
  scheduler orders by deps + caps + priority. A tick loop in horizon means you crossed into chorus.
- **Direction is a write; back-pressure is a read.** Re-prioritise = `UPDATE task.priority`, never a call
  into the scheduler. "Drifting" is read from landed outcomes, never from an agent's prose.
- **Outcomes, not prose.** Goal health is judged from landed DoD in the ledger — what actually passed.
- **Bounded beats only.** Scouts and the analyst are bounded `dream.run_task` beats. No unbounded trees.
- **One intake door.** Horizon drives the *same* `chorus.submit` door; chorus never grows a second one.

## 4. The seam — `dream.contracts.strategy`

horizon binds **only** to three Protocols + a few plain shapes in `dream.contracts` (content-named
`strategy.py`, not consumer-named). A consumer's composition root wires chorus's concretes into them.

| Port | Shape | Horizon's role |
|---|---|---|
| `IntakePort` | `submit(intent, *, assignee, priority, depends_on, goal_id, origin_fingerprint) → id` · `set_priority(task_id, priority)` | the **writer** of intents + ranking (idempotent on `horizon_intake` + fingerprint) |
| `GoalStore` | `upsert(GoalNode) → id` · `get` · `children(parent_id)` | the **author** of the goal tree |
| `OutcomeFeed` | `subscribe(cb) → unsubscribe` · `replay(after=)` → `OutcomeEvent` | **subscribes** + interprets landed outcomes |

**Not in the seam:** **Decisions.** They are horizon-native, so `dream.contracts` never learns about
them — the seam is only ever about goals + tasks + outcomes. Strategy-only fields chorus never reads
(score, health, metric, target, evidence) live in **horizon's own `StrategyStore`**, keyed by `goal_id`;
decisions + the decision→goal map live in horizon's **`DecisionStore`**.

## 5. Cross-repo picture

v1 touches **three repos**, in dependency order:

```
dream (contracts.strategy)  ──►  chorus (satisfies, horizon-seam branch)  ──►  horizon (binds to the ports)
```

- **dream** (`horizon-seam`) — `IntakePort` / `GoalStore` / `OutcomeFeed` + `GoalNode` / `OutcomeEvent` / `Priority` in `contracts/strategy.py`; `__contract_version__` 0.2.0.
- **chorus** (`horizon-seam` off `Chorus-employees`) — additive seam only: `goal_id` + `origin_kind` + `origin_fingerprint` through `Chorus.submit`; `GoalRepo.children/update`; `TaskRepo.find_by_origin`; `OriginKind.HORIZON_INTAKE`; `GoalLevel` = `[company, team, employee, task, goal]`. No migration.
- **horizon** (`main`) — the SDK + a composition-root adapter (`examples/chorus_bridge.py`) that makes a chorus instance satisfy the three ports.

## 6. Package structure

horizon mirrors the layered shape of chorus/dream:

```
src/horizon/
  __init__.py   facade.py (Horizon)   ports.py (re-export the strategy seam)   errors.py   py.typed
  model/      _decision.py (Decision) · _goal.py (Goal, rich view) · _strategy.py (StrategyRecord)
  store/      _decision_store.py (DecisionStore) · _strategy_store.py (StrategyStore) · _jsonfile.py
  planning/   Decision → Goals decomposer            (M2)
  intake/     Submitter · Prioritiser · fingerprint  (M2)
  feedback/   OutcomeListener · health/drift          (M2)
  generation/ sources → evidence → DirectionBrief     (M4)
  chat/       CEO chat (read + propose, confirm-to-write)  (M5)
examples/     chorus_bridge.py — the composition root (the one place importing both)
tests/        test_m1_seam.py (+ test_public_api.py pin in M3)
```

## 7. Milestones

Build order **M1 → M2 → M3** (the proven seam — ship as **v1.0**), then **M4 → M5**.

### M1 — Seam + shared data *(P1 + P3)* — ✅ **done**
- `dream.contracts.strategy`: the three Protocols + `GoalNode` / `OutcomeEvent` / `Priority`; version 0.2.0.
- chorus (`horizon-seam`): `goal_id` / `origin_kind` / `origin_fingerprint` through `Chorus.submit`; `GoalRepo.children/update`; `TaskRepo.find_by_origin`; `HORIZON_INTAKE`; `GoalLevel` trimmed to a single `GOAL`.
- horizon: the package scaffold + `DecisionStore` / `StrategyStore` + the composition-root adapter.
- **Proven:** the boundary holds — the adapters satisfy the ports (runtime-checkable), the goal tree round-trips, intake is idempotent + goal-linked, and outcomes translate — all against a real chorus, importing only `dream.contracts`. (4 tests · ruff + mypy strict clean.)

### M2 — Execution loop *(P2 + P4)* — **next**
- `planning`: a `Decomposer` — a seeded **Decision** → a goal tree written through `GoalStore` (v1: a leaf goal per decision).
- `intake`: a `Submitter` (leaf goal → exactly one idempotent `submit()` to the one employee, linked by `goal_id`, fingerprinted on `goal_id` + normalized-intent hash) + a `Prioritiser` (numeric `score` → `Priority` via `set_priority`).
- `feedback`: an `OutcomeListener` — subscribe `OutcomeFeed`; on a landed DoD verdict, update goal `health` in the `StrategyStore` and re-rank. Outcome-only, push-driven.
- **Proves:** the closed loop at one-employee level over a seeded decision.

### M3 — Proof of the seam *(P5)* — **ship v1.0**
- `examples/` demo: seed a decision → decompose to a goal → submit the leaf to the one employee → chorus runs the real beat → read the outcome → update health + re-prioritise → print the direction state.
- `tests/test_public_api.py` pinning horizon's public surface.
- a thin `horizon-cli` (seed / inspect direction).

### M4 — Generation funnel *(scouts + analyst + reconcile)*
- `SourceAdapter` Protocol + typed evidence packets (provenance / freshness / reliability).
- v1 sources: **internal** (chorus ledger/events) + human-seeded + **a web/market adapter** (external egress → behind a **governance gate** + credentials).
- `Scout`: bounded beat, reads adapters + event stream → normalized candidate opportunity.
- **Reuse/extend chorus's existing `analyst` employee**, governed by horizon policy → `DirectionBrief` (recommended edits, rationale, confidence, risks, candidate goals, proposed submit intents) behind an evidence gate. This is where the **department flow** lives (PM/analyst research → engineering goals).
- `Reconciler`: briefs → **proposed** decisions/goals. Proposal-only in v1 — a human confirms.
- **Proves:** direction generated from evidence, not hand-seeded.

### M5 — CEO chat + capstone
- Context assembler (tree · ledger · repo · product · metrics · memory · people · risk · commitments).
- **Minimal** surface: read/explain the Decision→Goal→Task tree + draft a decision or a `chorus.submit` intent; **all writes require explicit confirm/approval** (no auto-apply). A direction-changing answer produces an auditable tree diff + evidence refs + a draft intent or decision record.
- Capstone demo: signals → scout → brief → reconcile → CEO review → submit → execute → outcome → re-priority.

## 8. Locked decisions

| Decision | Choice |
|---|---|
| Spine | **Decision → Goal → Task** (Decision is our altitude) |
| Decision storage | **horizon-native** — chorus only ever sees goals + tasks |
| horizon location | New sibling repo `q:/projects/inspired-arc/horizon` (dream/chorus shape) |
| Protocol home | **`dream.contracts.strategy`** (renamed from `horizon.py` — content-named) |
| chorus changes | Additive on **`horizon-seam`** off `Chorus-employees` (dream too, matching) |
| Decision writers (v1) | **User chat only** (M5); the generation funnel (M4) is **proposal-only** |
| Decision cadence | **1–3 per sprint**, stable within a sprint, change on pivot |
| Analyst | **Reuse/extend chorus's existing `analyst`** employee, governed by horizon policy |
| v1 sources | Internal + human-seeded **+ a web/market adapter** (creds + governance gate) |
| CEO chat | **Minimal** — read/explain + draft; writes need confirm/approval |

## 9. Open-question defaults (override anytime)

- **Priority semantics:** a rich **numeric score** on the goal, mapped to chorus's coarse `TaskPriority`
  (critical/high/medium/low) at submit.
- **Fingerprint scope:** `goal_id` + a normalized intent hash defines "the same opportunity" for dedup.
- **Drift signal:** landed-DoD **pass-rate** on a goal's tasks + a **staleness clock** (elapsed since last landed outcome).

---

*Source of record: the `horizon — direction` v0 doc + the Decision/Goal/Task refinement. This plan operationalizes them for v1.*
