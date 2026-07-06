# Horizon v1 — Build Plan

> **Status:** finalized · decisions locked · M1 in progress
> `dream` completes one task · `chorus` runs the org that ships one sprint · **`horizon` decides what the company should do next.**

Horizon is an **SDK** (like dream and chorus), not a running company. It ships the abstractions for a
strategy layer that decides *which* work should exist, at *what* priority, and *whether the company is
still aimed right* — turning strategy into **intake** and **back-pressure**, without ever touching the
scheduler or the agent loop.

This document is the v1 build plan: the goal, the invariants, the seam to chorus, the milestones, the
locked decisions, and the open-question defaults.

---

## 1. Goal

A working `horizon` SDK that, running **in-process alongside chorus**, can:

1. **Own the OKR tree** — the company-direction graph (`goal` rows) that explains *why work exists*.
2. **Turn leaf goals into chorus intake** and steer `task.priority` (the *direction → intake* write).
3. **Close the feedback loop** — read landed outcomes, update goal health, re-prioritise (the *back-pressure* read).
4. **Generate direction from evidence** — opportunity scouts + an analyst/architect producing a `DirectionBrief`.
5. **Expose a CEO-chat control surface** — read/explain the tree + draft submit intents (writes gated).

…all **without importing chorus** and **without running the schedule**. v1 operates at **one-employee
level** (horizon submits a single right-sized task-intent one employee completes whole) — the manager
that splits work into children comes later.

## 2. Invariants (load-bearing — from the direction doc)

- **No sideways import.** chorus, horizon, lattice never import each other. They meet only at the **data
  layer** (the `goal` table, `task.priority`, the event stream) and at **`dream.contracts` Protocols**.
- **Horizon never schedules or dispatches.** It only *writes* `goal` rows and `task.priority`; chorus's
  scheduler orders by deps + caps + priority. A tick loop in horizon means you crossed into chorus.
- **Direction is a write; back-pressure is a read.** Re-prioritise = `UPDATE task.priority`, never a call
  into the scheduler. "Drifting" is read from landed outcomes, never from an agent's prose.
- **Outcomes, not prose.** Objective health is judged from landed DoD in the ledger — what actually
  passed — never a self-report.
- **Bounded beats only.** Scouts and the analyst/architect are bounded `dream.run_task` beats. No
  unbounded agent trees.
- **One intake door.** Horizon drives the *same* `chorus.submit` door; chorus never grows a second one.

## 3. The seam (what already exists in chorus)

chorus **pre-built** the entire horizon-facing seam:

| Seam | In chorus today | Horizon's role |
|---|---|---|
| Intake door | `Chorus.submit(intent, *, assignee, dod, depends_on, priority, …)` | becomes the **writer** of intents |
| OKR tree | `goal` table + `Goal` + `GoalLevel` + `GoalRepo` (flat skeleton) | becomes the **author** of the tree |
| goal↔task link | `task.goal_id` FK **already in the schema** (`Task.goal_id` field exists) | **populates** it via submit |
| Idempotent intake | `origin_kind` / `origin_fingerprint` + dedup unique indexes | owns the **fingerprint policy** |
| Outcome feed | `EventBus.subscribe(cb)` / `replay()` + typed `RUN_DONE`/`RUN_EVALUATED`/`TASK_STATUS`/`RECOVERY_ESCALATED` | **subscribes** + interprets |
| Priority | `task.priority` (`TaskPriority`: high/medium/low) — the field the scheduler orders by | owns the **ranking policy** |

**Ownership rule:** the *data* (tables, repos, FK, event bus) stays in chorus (the shared substrate);
the *policy* (writing, ranking, fingerprinting, outcome-interpretation) is horizon's. Strategy-only
fields chorus never reads (evidence, rationale, decision log) live in **horizon's own git-backed store**,
keyed by `goal_id`.

## 4. Cross-repo picture

v1 touches **three repos**, in dependency order:

```
dream (contracts)  ──►  chorus (satisfies them, horizon-seam branch)  ──►  horizon (binds to them)
```

- **dream** — add `IntakePort` / `GoalStore` / `OutcomeFeed` Protocols to `dream.contracts` (branch `horizon-seam`).
- **chorus** — additive seam changes on branch `horizon-seam` off `Chorus-employees`.
- **horizon** (this repo) — the SDK + a composition-root adapter that wires chorus's concretes into the ports.

## 5. Milestones

Build order **M1 → M2 → M3** (the proven seam — ship as **v1.0**), then **M4 → M5**.

### M1 — Seam + shared data *(P1 + P3)*
- `dream.contracts`: `IntakePort` / `GoalStore` / `OutcomeFeed` Protocols + minimal data types (`GoalNode`, `OutcomeEvent`); contract-version bump.
- chorus (`horizon-seam`): thread `goal_id` through `Chorus.submit`; enrich `Goal` (numeric score, `health`, one metric/target) + extend `GoalLevel` (add product/objective/key_result/initiative); add `HORIZON_INTAKE` origin kind + dedup index + migration.
- horizon: git-backed store for strategy-only fields keyed by `goal_id`; a composition-root adapter that makes a chorus instance satisfy the three ports.
- **Proves:** the boundary holds — horizon reads/writes the tree and submits through the port, importing only `dream.contracts`.

### M2 — Execution loop *(P2 + P4)*
- `Submitter`: leaf goal → exactly one idempotent `submit()` to the single employee, at a horizon-set priority, linked by `goal_id`.
- `Prioritiser`: the ranking policy that fills `task.priority`.
- `OutcomeListener`: subscribe the `OutcomeFeed`; on a terminal outcome, read landed DoD, map via `goal_id`, update goal health, re-rank via `task.priority`. Outcome-only, push-driven.
- **Proves:** the closed loop at one-employee level over a hand-seeded tree.

### M3 — Proof of the seam *(P5)* — **ship v1.0**
- `examples/` demo: seed a tiny OKR tree → submit a leaf to the one employee → chorus runs the real beat → read the outcome → update health + re-prioritise → print the direction state.
- `tests/test_public_api.py` pinning horizon's public surface (mirrors chorus).
- a thin `horizon-cli` (seed / inspect direction).

### M4 — Generation funnel *(scouts + analyst/architect + reconcile)*
- `SourceAdapter` Protocol + typed evidence packets (provenance/freshness/reliability).
- v1 sources: **internal** (chorus ledger/events) + human-seeded + **a web/market adapter** (external egress → behind a **governance gate** + credentials).
- `Scout`: bounded beat, reads adapters + event stream → normalized candidate opportunity.
- **Reuse/extend chorus's existing `analyst` employee**, governed by horizon policy → `DirectionBrief` (recommended OKR edits, rationale, confidence, risks, candidate initiatives, proposed submit intents) behind an evidence gate.
- `Reconciler`: briefs → proposed OKR nodes (writes the tree).
- **Proves:** direction generated from evidence, not hand-seeded.

### M5 — CEO chat + capstone
- Context assembler (tree · ledger · repo · product · metrics · memory · people · risk · commitments).
- **Minimal** surface: read/explain the tree + draft a `chorus.submit` intent; **all writes require explicit confirm/approval** (no auto-apply). A direction-changing answer must produce an auditable OKR-tree diff + evidence refs + a draft intent or a decision record.
- Capstone demo: signals → scout → brief → reconcile → CEO review → submit → execute → outcome → re-priority.

## 6. Locked decisions

| Decision | Choice |
|---|---|
| horizon location | **New sibling repo** `q:/projects/inspired-arc/horizon` (dream/chorus shape) |
| Protocol home | **`dream.contracts`** (`IntakePort` / `GoalStore` / `OutcomeFeed`) |
| chorus changes | **New branch `horizon-seam`** off `Chorus-employees` (dream too, matching) |
| Analyst/architect | **Reuse/extend chorus's existing `analyst`** employee, governed by horizon policy |
| v1 sources | Internal (chorus ledger/events) + human-seeded **+ a web/market adapter** (creds + governance gate) |
| CEO chat | **Minimal** — read/explain + draft submit; writes need confirm/approval |

## 7. Open-question defaults (override anytime)

- **Priority semantics:** a rich **numeric score** on the goal, mapped to chorus's coarse `TaskPriority`
  (high/medium/low) at submit.
- **Fingerprint scope:** `goal_id` + a normalized intent hash defines "the same opportunity" for dedup.
- **Drift signal:** landed-DoD **pass-rate** on a goal's tasks + a **staleness clock** (elapsed since last landed outcome).

---

*Source of record: the `horizon — direction` v0 doc. This plan operationalizes it for v1.*
