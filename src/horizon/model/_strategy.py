"""``StrategyRecord`` — the rich, strategy-only facts horizon keeps about one goal (keyed by ``goal_id``).

chorus persists the goal *skeleton* (id / title / level / status / parent / owner). The strategy-only
fields horizon reasons over — the numeric ``score``, the ``health`` read, the ``metric`` + ``target``,
and the ``evidence`` behind them — live here, in horizon's own store, so chorus needs no schema change.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StrategyRecord:
    """The rich, strategy-only facts about one goal (merged with chorus's skeleton at read time)."""

    goal_id: str
    score: float = 0.0
    health: str = "unknown"  # on_track | drifting | blocked | unknown
    metric: str | None = None
    target: str | None = None
    evidence: list[str] = field(default_factory=list)
