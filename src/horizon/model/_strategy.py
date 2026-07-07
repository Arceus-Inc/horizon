"""``StrategyRecord`` — the rich, strategy-only facts horizon keeps about one goal (keyed by ``goal_id``).

chorus persists the goal *skeleton* (id / title / level / status / parent / owner). The strategy-only
fields horizon reasons over — the numeric ``score``, the ``health`` read, the ``metric`` + ``target``,
and the ``evidence`` behind them — live here, in horizon's own store, so chorus needs no schema change.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StrategyRecord:
    """The per-goal horizon state (merged with chorus's skeleton at read time).

    Holds the strategy-only fields chorus never sees (``score`` / ``health`` / ``metric`` / ``target`` /
    ``evidence``) plus the bookkeeping horizon needs to close the loop: the owning ``decision_id``, the
    ``task_id`` currently realizing the goal, and the landed-outcome counters (``passes`` / ``fails`` /
    ``last_outcome_at``) the health + drift signal is computed from.
    """

    goal_id: str
    title: str = ""  # cached display title (chorus owns the canonical one; this makes reads offline-safe)
    score: float = 0.0
    health: str = "unknown"  # on_track | drifting | blocked | unknown
    metric: str | None = None
    target: str | None = None
    evidence: list[str] = field(default_factory=list)
    decision_id: str | None = None  # the horizon-only decision this goal decomposed from
    task_id: str | None = None  # the chorus task currently realizing this goal (set at submit)
    passes: int = 0  # landed DoD passes (drift input)
    fails: int = 0  # landed DoD fails (drift input)
    last_outcome_at: str | None = None  # ISO ts of the last landed outcome (staleness input)

