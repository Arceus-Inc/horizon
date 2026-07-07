"""``DecisionState`` — the read model horizon exposes: a decision with its assembled goals.

Each goal is the rich :class:`Goal` view (chorus's skeleton merged with horizon's strategy record), so a
caller (demo, CLI, report) sees the whole Decision -> Goal picture — title, owner, score, health, the
metric/target, and the realizing task — in one shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from horizon.model._decision import Decision
from horizon.model._goal import Goal


@dataclass(frozen=True)
class DecisionState:
    """A decision and its current goals (assembled skeleton + strategy)."""

    decision: Decision
    goals: list[Goal] = field(default_factory=list)
