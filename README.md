# horizon

**The strategy layer that decides the sprint.**

> `dream` completes one task · `chorus` runs the org that ships one sprint · **`horizon` decides what the company should do next.**

horizon is an SDK — a library, like dream and chorus. It owns the **OKR tree**, turns strategy into
**chorus intake** (`submit` at a set `task.priority`), and closes the **feedback loop** (landed outcomes
→ goal health → re-prioritise). It never imports chorus and never runs the schedule: the two are
siblings that meet only at the **data layer** (the `goal` table, `task.priority`, the event stream) and
at **`dream.contracts`** typed Protocols.

See [`docs/v1-plan.md`](docs/v1-plan.md) for the full v1 build plan, milestones, and locked decisions.

## Boundaries

- **Does not schedule or dispatch** — that is chorus.
- **Does not run the agent loop** — that is dream.
- **Does not import chorus or lattice** — siblings meet at the data layer + `dream.contracts`.

## Layout

```
src/horizon/       # the SDK — ports binding, Submitter, OutcomeListener, GoalStore, …
src/horizon_cli/   # thin CLI: seed OKRs / inspect direction
examples/          # a demo OKR tree + the one-employee horizon<->chorus loop
tests/             # public-API pin, like chorus's test_public_api.py
docs/              # v1-plan.md and design notes
```

## Local dev

```bash
uv pip install -e ../dream -e ../chorus -e .[dev]   # only the composition root imports chorus
```
