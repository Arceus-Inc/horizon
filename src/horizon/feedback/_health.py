"""The health + drift model — how a landed outcome moves a goal's health and score.

Outcomes, not prose: a goal's health is computed from its landed-DoD counters (``passes`` / ``fails``)
plus a staleness clock, never from an agent's self-report. Health adjusts the goal's **score** (the one
knob), which the Prioritiser maps to chorus priority:

- a **pass** -> ``on_track`` and the score **decays** (the work landed; deprioritise);
- a **fail** -> ``drifting`` (or ``blocked`` if the pass-rate is poor) and the score is **bumped up**
  (surface it) — but horizon never auto-resubmits; re-execution is chorus recovery / the next loop;
- **staleness** (no outcome for too long) drifts an otherwise ``on_track`` goal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from horizon.model._strategy import StrategyRecord


@dataclass(frozen=True)
class HealthPolicy:
    """Configurable knobs for the health + drift signal."""

    fail_bump: float = 0.25  # a fail raises score by this (surface it)
    pass_decay: float = 0.5  # a pass multiplies score by this (handled -> deprioritise)
    block_pass_rate: float = 0.5  # a fresh fail with pass-rate below this -> blocked (else drifting)
    stale_after_s: float = 86_400.0  # no outcome for this long -> an on_track goal drifts
    stale_bump: float = 0.15  # a drifted-by-staleness goal is resurfaced by this much score


def apply_outcome(
    record: StrategyRecord,
    *,
    passed: bool,
    policy: HealthPolicy | None = None,
    now: datetime | None = None,
) -> StrategyRecord:
    """Fold one landed DoD verdict into the record (counters + health + score). Mutates + returns it."""
    policy = policy or HealthPolicy()
    moment = now or datetime.now(UTC)
    if passed:
        record.passes += 1
        record.health = "on_track"
        record.score = round(max(0.0, record.score * policy.pass_decay), 4)
    else:
        record.fails += 1
        total = record.passes + record.fails
        pass_rate = record.passes / total if total else 0.0
        record.health = "blocked" if pass_rate < policy.block_pass_rate else "drifting"
        record.score = round(min(1.0, record.score + policy.fail_bump), 4)
    record.last_outcome_at = moment.isoformat()
    return record


def staleness_health(
    record: StrategyRecord,
    *,
    policy: HealthPolicy | None = None,
    now: datetime | None = None,
) -> str:
    """Return the health after applying the staleness clock (an ``on_track`` stale goal drifts)."""
    policy = policy or HealthPolicy()
    if record.last_outcome_at is None:
        return record.health
    moment = now or datetime.now(UTC)
    elapsed = (moment - datetime.fromisoformat(record.last_outcome_at)).total_seconds()
    if elapsed > policy.stale_after_s and record.health == "on_track":
        return "drifting"
    return record.health
