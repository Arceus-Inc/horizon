# Spec — Theme C: The Generation Funnel *(originate direction from evidence)*

> **Scope:** v2 Theme C / milestone **M9** in [`v2-plan.md`](v2-plan.md). Turns horizon from *hand-seeded*
> decisions into *evidence-generated* ones — **proposal-only, human-confirmed**.
> **Status:** spec / not started. **Owner:** _tbd_.

---

## 0. Can this be built before A / B / D / X?

**Yes — Theme C is the most self-contained theme and can be picked up independently, with one small caveat.**

C sits at the **top** of the funnel: it *produces proposed decisions and goals* and then feeds them into the
**existing v1 loop** (`seed_decision → decompose → submit_decision → outcomes`). It reads signals and writes
proposals; it does not depend on how outcomes are scored or how work fans out.

| Theme | Does C depend on it? | Why / workaround |
|---|---|---|
| **A** (deepen: metric-aware, escalation, re-eval) | **No** | C's output is a proposed decision/goal; it flows through the *current* decompose/submit loop untouched. Metric-aware outcomes make the loop C feeds *better*, but C doesn't need them. |
| **B** (widen: manager, portfolio, capacity) | **No** | A proposed decision runs through the v1 one-employee loop exactly as a hand-seeded one does. The manager (B1) improves execution *below* C; C is agnostic. |
| **D** (CEO chat) | **Partially — one small slice** | C is **proposal-only**, so it needs a *human-confirm gate*. You do **not** need the full CEO chat (M10). C ships with a **minimal approval surface** (§7) — a CLI/list-and-approve — that D later subsumes. |
| **X** (observability) | **No** | Independent. C can reuse X1's durable log later but doesn't require it. |

**Net:** build C standalone. The only new dependency you must build alongside it is a **thin approval gate**
(a few methods + a CLI verb), specced in §7 — not the full Theme D.

**Recommended internal order within C:** `C1 → C4 → (gate) → C2 → C3`. Land the data contracts and the
reconcile-to-proposed path first (fully offline, deterministic), then the human gate, then the two bounded
beats (scout, analyst) that fill the funnel with real evidence. This lets you prove the *whole pipe* with
fakes before spending a single live beat.

---

## 1. Summary

The funnel is a four-stage, **proposal-only** pipeline that ends at a human gate:

```
sources ──►  EvidencePacket  ──►  Scout  ──►  CandidateOpportunity  ──►  Analyst  ──►  DirectionBrief  ──►  Reconciler  ──►  Proposal(s)  ──►  [human confirm]  ──►  seed_decision(status="proposed"→"active") + decompose + submit
   C1               C1                C2              C2                    C3               C3                C4              C4                 §7 gate                       existing v1 loop
```

Every stage is typed, bounded, and auditable. Nothing auto-writes to the live tree: the Reconciler emits
**proposals**, and only an explicit human approval promotes a proposed decision to `active` and runs the
existing decompose/submit path.

---

## 2. Goals / Non-goals

**Goals**
- A `SourceAdapter` Protocol + typed **evidence packets** with provenance / freshness / reliability.
- v2 sources: **internal** (chorus ledger + event stream), **human-seeded**, and **a web/market adapter**
  behind a **governance gate** (external egress + credentials).
- A bounded **Scout** beat that turns evidence into normalized **candidate opportunities**.
- Reuse/extend chorus's **analyst** to turn a candidate into a **`DirectionBrief`** (structured output).
- A **Reconciler** that turns briefs into **proposed** decisions/goals (never live writes).
- A **minimal approval gate** so a human can list, inspect, and approve/reject proposals.

**Non-goals (explicitly out of scope for C)**
- The full CEO chat (Theme D / M10) — C only needs the approval gate slice.
- Auto-applying any proposal (forbidden — proposal-only is a locked decision).
- Unbounded agent trees (invariant: scouts/analyst are bounded `dream.run_task` beats).
- New chorus execution structure (that's B1, the manager) — C reuses the existing single-employee intake.

---

## 3. Where it plugs into the existing loop

C is **additive** and touches only horizon + `dream.contracts`:

- **Reads:** the chorus event stream + ledger via the existing `OutcomeFeed` (internal source) and external
  adapters (web/market) behind the gate.
- **Writes (proposals only):** into a new horizon-native `ProposalStore` — *not* chorus, *not* the live
  `DecisionStore`/`GoalStore` — until a human approves.
- **On approval:** calls the **existing** facade entry points — `seed_decision(...)` with the proposed
  decision (flipping `status` `"proposed" → "active"`), then `decompose(...)` + `submit_decision(...)`.

`Decision.status` already includes `"proposed"` — the model needs **no change** to represent a funnel
output. That is the key reason C slots in cleanly ahead of the other themes.

---

## 4. Architecture

```
                         ┌─────────────────────────── horizon (new: generation/) ───────────────────────────┐
 chorus ledger/events ──►│  SourceAdapter(internal)  ┐                                                        │
 human seed ────────────►│  SourceAdapter(seed)      ├─► EvidenceBus ─► Scout(beat) ─► CandidateOpportunity   │
 web/market (gated) ────►│  SourceAdapter(web) [gate]┘                                        │               │
                         │                                                                    ▼               │
                         │                                          Analyst(beat, reused) ─► DirectionBrief   │
                         │                                                                    │               │
                         │                                                    Reconciler ◄────┘               │
                         │                                                        │                           │
                         │                                                        ▼                           │
                         │                                                  ProposalStore  ◄─ minimal gate ──►│  human
                         └──────────────────────────────────────────────────────┬───────────────────────────┘
                                                                                 │ (on approve)
                                                                                 ▼
                                                     existing v1 loop: seed_decision → decompose → submit
```

New package (mirrors the v1-plan §6 layout, which already reserved `generation/`):

```
src/horizon/
  generation/
    _sources.py      SourceAdapter Protocol + EvidencePacket + built-in adapters (internal/seed/web)
    _gate.py         GovernanceGate (egress allow-list + credential check) for external adapters
    _scout.py        Scout — bounded beat: evidence -> CandidateOpportunity
    _brief.py        DirectionBrief shape + the analyst-beat wrapper (structured output)
    _reconciler.py   Reconciler — briefs -> Proposal(s)
    _proposal.py     Proposal shape + ProposalStore (horizon-native, JSON-file backed)
    _approvals.py    the minimal confirm-to-write gate (list / inspect / approve / reject)
```

---

## 5. Data shapes (typed, all structured-output-friendly)

```python
@dataclass(frozen=True)
class EvidencePacket:
    id: str
    source: str                 # adapter name, e.g. "chorus.ledger" | "seed" | "web.market"
    kind: str                   # "signal" | "metric" | "market" | "note"
    body: str                   # the normalized content the scout reads
    provenance: str             # where it came from (url / task_id / person)
    freshness_s: float          # age in seconds at capture
    reliability: float          # 0..1 adapter-declared trust
    captured_at: str

@dataclass(frozen=True)
class CandidateOpportunity:
    id: str
    title: str
    thesis: str                 # one-paragraph "why this could be worth a decision"
    evidence_ids: list[str]     # the packets that support it
    confidence: float           # 0..1 (scout-declared)

@dataclass(frozen=True)
class DirectionBrief:
    candidate_id: str
    recommendation: str         # the proposed strategic move
    rationale: str
    confidence: float           # 0..1 (analyst-declared)
    risks: list[str]
    candidate_goals: list[CandidateGoal]   # title/metric/target/rationale — same shape the decomposer emits
    evidence_refs: list[str]    # packet ids (auditable)

@dataclass
class Proposal:
    id: str
    status: str = "proposed"    # proposed | approved | rejected | superseded
    brief: DirectionBrief | None = None
    decision_statement: str = ""    # what seed_decision would receive
    decision_rationale: str = ""
    created_at: str = ""
    decided_by: str | None = None   # who approved/rejected
    decided_at: str | None = None
    linked_decision_id: str | None = None   # set once approved + seeded
```

The analyst returns `DirectionBrief` via a **strict `json_schema`** response (same discipline as the
decomposer — anything the system parses is typed). `candidate_goals` deliberately mirror the decomposer's
goal shape so an approved proposal flows straight into `decompose`/`submit` with no translation.

---

## 6. Components in detail

### C1 · SourceAdapter + evidence packets
- **Protocol:** `class SourceAdapter(Protocol): def name(self) -> str; def poll(self, *, since: str | None) -> list[EvidencePacket]`.
- **Built-ins:**
  - `InternalSource` — reads the chorus event stream/ledger via the existing `OutcomeFeed.replay(after=)`
    (once X1 gives it a log path; until then, from live subscription). Emits `signal`/`metric` packets.
  - `SeedSource` — a human drops notes/URLs; deterministic, no egress.
  - `WebMarketSource` — external egress; **must** pass through the `GovernanceGate` (§below).
- **`EvidenceBus`** — collects packets, dedups by `(source, hash(body))`, keeps provenance/freshness.

### C1a · Governance gate *(for external adapters only)*
- `GovernanceGate.check(adapter, request)` — an **egress allow-list** (which hosts/domains) + a
  **credential presence** check + a rate/size cap. External adapters cannot run without passing it.
- Locked decision (from v1-plan): web/market is **behind creds + a governance gate**. Internal/seed sources
  bypass the gate (no egress).

### C2 · Scout *(bounded beat)*
- A bounded `dream.run_task` beat (invariant: no unbounded trees). Input: a batch of `EvidencePacket`s.
  Output: zero or more `CandidateOpportunity` (structured output).
- The scout **only normalizes + clusters** evidence into candidate theses; it does not invent goals.
- Deterministic-testable: a `FakeScout` returns canned candidates for a packet fixture.

### C3 · Analyst → DirectionBrief *(reused, governed)*
- **Reuse chorus's existing `analyst`** employee (locked decision), invoked as a bounded beat, governed by
  horizon policy. Input: one `CandidateOpportunity` + its evidence. Output: a `DirectionBrief` (strict
  `json_schema`).
- This is where the **department flow** lives (PM/analyst research → engineering-shaped candidate goals).
- **Evidence gate:** a brief with `confidence` below a threshold or with empty `evidence_refs` is dropped,
  not proposed.

### C4 · Reconciler → proposals
- Pure, deterministic (no LLM). Input: `DirectionBrief`s. Output: `Proposal`s written to `ProposalStore`.
- Dedups against existing **live** decisions (via `DecisionStore`) and open proposals so the same
  opportunity isn't proposed twice (reuse the intake `fingerprint` idea on the decision statement).
- Emits a `Proposal(status="proposed")` — **never** touches the live tree.

---

## 7. The minimal confirm-to-write gate *(the only D-slice C needs)*

C is proposal-only, so it needs a human to approve. Build the **smallest** surface — not the CEO chat:

- **`horizon.generation.approvals`** on the facade:
  - `list_proposals(status="proposed") -> list[Proposal]`
  - `explain_proposal(id) -> str` (brief + evidence refs + the decision/goals it would create — an
    **auditable preview**, no writes)
  - `approve_proposal(id, *, by) -> str` → seeds the decision (`status "proposed" → "active"`), runs
    `decompose` + `submit_decision`, links `Proposal.linked_decision_id`, marks `approved`.
  - `reject_proposal(id, *, by, reason)` → marks `rejected`.
- **CLI verbs** (thin, mirrors the existing `horizon-cli`):
  `horizon proposals` · `horizon proposal show <id>` · `horizon proposal approve <id>` · `... reject <id>`.
- **Invariant:** approval is the *only* path from proposal → live tree. No auto-apply. Every approval writes
  an auditable record (who/when/what-diff). Theme D (M10) later replaces this CLI with the chat surface but
  reuses the same `approvals` methods.

---

## 8. Invariants respected

- **Proposal-only.** The Reconciler writes to `ProposalStore`, never to chorus or the live `DecisionStore`.
  Only human `approve_proposal` promotes.
- **No sideways import.** Sources read chorus only through the existing `OutcomeFeed`/ledger ports; external
  egress only through the gate. horizon never imports chorus.
- **Bounded beats only.** Scout + analyst are bounded `dream.run_task` beats.
- **Outcomes/evidence, not prose.** Candidates + briefs are typed, evidence-referenced, and gated on
  confidence — not free-form agent chatter.
- **One intake door.** Approval reuses the existing `seed_decision`/`decompose`/`submit_decision` path; no
  second intake.

---

## 9. Build slices (TDD, each shippable)

| Slice | Contents | Tests-first | Live? |
|---|---|---|---|
| **C-0** | `EvidencePacket` / `CandidateOpportunity` / `DirectionBrief` / `Proposal` + `ProposalStore` | round-trip + dedup unit tests | no |
| **C-4** | `Reconciler` briefs → proposals (dedup vs live decisions) | deterministic reconcile tests | no |
| **C-gate** | `approvals` methods + CLI verbs (approve → seed+decompose+submit) | approve-path integration test w/ fakes | no |
| **C-1** | `SourceAdapter` + `InternalSource` + `SeedSource` + `EvidenceBus` | adapter poll + dedup + provenance tests | no |
| **C-1a** | `GovernanceGate` + `WebMarketSource` | allow-list + creds + cap tests | no (mock egress) |
| **C-2** | `Scout` bounded beat (+ `FakeScout`) | fake-scout pipeline test; one live scout | 1 beat |
| **C-3** | Analyst → `DirectionBrief` (structured output, evidence gate) | schema-valid parse + gate tests; one live brief | 1 beat |
| **C-cap** | end-to-end funnel demo → proposal → approve → live loop (report) | capstone script | live |

Order matches §0: prove the **whole pipe offline** (C-0 → C-4 → C-gate → C-1) before spending live beats
(C-2, C-3), then the capstone.

---

## 10. Testing strategy

- **Offline/deterministic (the default suite):** `FakeSource`s emitting fixture packets, a `FakeScout` and a
  `FakeAnalyst` returning canned structured outputs, and an in-memory `ProposalStore`. The entire funnel —
  including approve → seed → decompose → submit — runs with fakes, mirroring the existing
  `demo_offline.py` discipline.
- **Live (marked):** one scout beat + one analyst brief against Azure OpenAI, behind the `live` marker.
- **Public-API pin:** extend `tests/test_public_api.py` with the new facade methods (`list_proposals`,
  `approve_proposal`, …) so the surface is locked.
- **Governance tests:** the gate rejects a disallowed host / missing credential / oversize response.

---

## 11. Open questions (defaults; override anytime)

- **Scout ↔ Analyst split:** one combined beat vs. two. **Default:** two — a cheap scout that clusters
  evidence, then a governed analyst only on survivors (saves live beats).
- **Evidence-gate threshold:** min `confidence` + min evidence count to become a proposal. **Default:**
  `confidence ≥ 0.6` and `≥ 1` evidence ref.
- **Dedup key for proposals:** fingerprint of the decision statement vs. the candidate thesis. **Default:**
  normalized decision statement (reuse `intake.fingerprint`).
- **Approval identity:** who is `by`? **Default:** a CLI `--as <name>` flag now; real identity when Theme D
  lands.
- **Internal source before X1:** poll live subscription until the durable log (X1) exists. **Default:**
  live subscription; swap to `replay(after=)` once X1 ships.

---

## 12. Definition of done for Theme C

- The offline funnel (fakes) produces a `Proposal` from fixture evidence and, on `approve_proposal`, creates
  a live `active` decision with submitted goals — all green in the default suite.
- One **live** capstone run: real evidence → scout → analyst brief → proposal → human approve → the existing
  loop runs a real beat — captured in a report (reusing `strong_run`'s style, incl. the ops log).
- `SourceAdapter` + `GovernanceGate` + `ProposalStore` + `approvals` are public, pinned, ruff + mypy-strict
  clean.
- Zero changes to chorus execution structure; all v1 invariants intact.
