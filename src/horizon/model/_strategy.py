"""``StrategyRecord`` — the rich, strategy-only facts horizon keeps about one goal (keyed by ``goal_id``).

chorus persists the goal *skeleton* (id / title / level / status / parent / owner). The strategy-only
fields horizon reasons over — the numeric ``score``, the ``health`` read, the ``metric`` + ``target``,
and the ``evidence`` behind them — live here, in horizon's own store, so chorus needs no schema change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dream.contracts import StaffingRequirement


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
    root_task_id: str | None = None
    task_ids: list[str] = field(default_factory=list)
    team_id: str | None = None
    lead_id: str | None = None
    task_outcomes: dict[str, str] = field(default_factory=dict)
    task_outcome_revisions: dict[str, int] = field(default_factory=dict)
    outcome_event_ids: list[str] = field(default_factory=list)
    delivery_shape: str = "single"
    staffing_requirements: tuple[StaffingRequirement, ...] = ()
    passes: int = 0  # landed DoD passes (drift input)
    fails: int = 0  # landed DoD fails (drift input)
    last_outcome_at: str | None = None  # ISO ts of the last landed outcome (staleness input)
    done: bool = False  # a passing DoD landed — in v1 (one task per goal) the goal's work is done
    attempts: int = 0  # how many times this goal has been submitted (initial + recoveries)
    needs_recovery: bool = False  # a terminal failure landed; awaiting a diagnostic-carrying re-attempt
    last_diagnostic: str = ""  # why the last attempt failed — stored on the node, read into the next beat

    def __post_init__(self) -> None:
        """Keep the legacy task identity aligned with the authoritative root."""
        if self.root_task_id is not None:
            self.task_id = self.root_task_id
        elif self.task_id is not None:
            self.root_task_id = self.task_id

