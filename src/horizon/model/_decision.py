"""``Decision`` — the top of the Decision -> Goal -> Task spine, horizon-native (chorus never sees it).

A Decision is the sprint's strategic anchor: a natural-language intent — *"build an AI note-taker for
working professionals"*, *"gamify the onboarding flow"* — the user sets (via chat in v1). horizon
decomposes it into goals; the decision -> goal mapping, the rationale, and the decision log live here,
in horizon's own store, **not** in chorus. chorus only ever sees the goals + tasks that fall out of a
decision, never the decision itself. Cadence: 1-3 per sprint, stable within a sprint, changed on pivot.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Decision:
    """A strategic decision the sprint is aimed at — horizon-owned, decomposed into goals."""

    id: str
    statement: str
    status: str = "active"  # proposed | active | paused | done | archived
    owner: str | None = None
    rationale: str = ""
    goal_ids: list[str] = field(default_factory=list)  # the goals this decision decomposed into
