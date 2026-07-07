# horizon

**The strategy layer that decides the sprint.**

> `dream` completes one task · `chorus` runs the org that ships one sprint · **`horizon` decides what the company should do next.**

horizon is an SDK — a library, like dream and chorus. It owns the top of the **Decision → Goal → Task**
spine: it holds **decisions** (horizon-native), decomposes them into **goals** with an LLM, turns leaf
goals into **chorus intake** (`submit` at a score-derived `task.priority`), and closes the **feedback
loop** (landed DoD verdicts → goal health → re-prioritise). It never imports chorus and never runs the
schedule: the two are siblings that meet only at the **data layer** (the `goal` table, `task.priority`,
the event stream) and at **`dream.contracts`** typed Protocols.

See [`docs/v1-plan.md`](docs/v1-plan.md) for the full v1 build plan, milestones, and locked decisions.

## The spine

| Layer | What it is | Who owns it |
|---|---|---|
| **Decision** | the sprint's strategic anchor, in natural language | **horizon** (horizon-native — chorus never sees it) |
| **Goal** | a decision decomposed into an executable deliverable | **horizon** authors it as a chorus `goal` row |
| **Task** | the unit a chorus beat actually runs | **chorus** (a future manager splits a goal into tasks) |

The loop: **seed a decision → decompose (LLM) → submit goals → outcomes land → health + re-priority.**

## Quickstart

```bash
uv sync --extra dev
```

CLI (works offline, over horizon's own stores):

```bash
uv run horizon seed "Build an AI note-taker for working professionals" --owner moe
uv run horizon decisions
uv run horizon show
```

SDK (wire the ports at a composition root, then drive the loop):

```python
from horizon import Horizon, LoopReporter

horizon = Horizon(
    goals=goal_store,        # a dream.contracts.GoalStore  (adapts chorus's goal table)
    intake=intake_port,      # a dream.contracts.IntakePort  (adapts chorus.submit)
    outcomes=outcome_feed,   # a dream.contracts.OutcomeFeed (adapts chorus's event bus)
    reasoner=substrate,      # an LLM complete() — dream's OpenAIChatSubstrate, or a fake
    default_assignee="moe",
)
horizon.seed_decision(decision)
horizon.decompose(decision.id)     # LLM: decision -> goals
horizon.submit_decision(decision.id)
horizon.start()                    # subscribe: outcomes -> health -> re-priority
horizon.state()                    # the current direction (read model)
```

## Demos + reports

Two runnable demos generate full insight reports (decomposer · submitter · listener · feedback):

```bash
uv run python examples/demo_offline.py   # deterministic: real chorus wiring, canned LLM + synthetic verdicts
uv run python examples/demo_live.py      # real LLM + a real one-employee Analyst beat (needs AZURE_OPENAI_*)
```

- [`reports/offline-demo-report.md`](reports/offline-demo-report.md) — the loop end-to-end, showing back-pressure surface a failed goal above the passed ones.
- [`reports/live-demo-report.md`](reports/live-demo-report.md) — a real LLM decomposition + a real Analyst beat's DoD verdict closing the loop.

## Architecture

horizon binds only to three `dream.contracts` Protocols (the strategy seam) + a minimal `Reasoner`:

- `IntakePort` — open a depth-0 task + set priority (idempotent on a goal-scoped fingerprint).
- `GoalStore` — read/write the goal tree.
- `OutcomeFeed` — subscribe to / replay landed outcomes.

A consumer's **composition root** (see [`examples/chorus_bridge.py`](examples/chorus_bridge.py)) — the
one place allowed to import both — adapts chorus's concrete classes into those ports. chorus owns the
execution data (goals + tasks + events); horizon owns the strategy (decisions, ranking/fingerprint/
outcome policy, and the strategy fields), stored in its own `.horizon/` stores keyed by `goal_id`.

```
src/horizon/
  facade.py (Horizon)   ports.py   reporting.py   errors.py
  model/     Decision · Goal · StrategyRecord · DecisionState
  store/     DecisionStore · StrategyStore
  planning/  Decomposer + Reasoner        (Decision -> Goals, LLM)
  intake/    Submitter · Prioritiser · fingerprint
  feedback/  OutcomeListener · health/drift
src/horizon_cli/         thin CLI (seed / decisions / show)
examples/                chorus_bridge.py + demo_offline.py + demo_live.py
tests/                   unit + integration + public-API pin (58 + live)
```

## Boundaries

- **Does not schedule or dispatch** — that is chorus.
- **Does not run the agent loop** — that is dream.
- **Does not import chorus or lattice** — siblings meet at the data layer + `dream.contracts`.

## Local dev

```bash
uv sync --extra dev
uv run pytest -m "not live"      # fast suite (no creds)
uv run pytest -m live            # live LLM tests (needs AZURE_OPENAI_*)
uv run ruff check src tests examples
uv run mypy
```
