"""``Goal`` — horizon's rich view of a goal: chorus's skeleton + horizon's strategy fields + its decision.

Distinct from :class:`dream.contracts.GoalNode` (the lean DTO on the chorus seam). This is what horizon
reasons over internally; a reader assembles it from the ``GoalStore`` skeleton + the ``StrategyStore``
record + the owning ``Decision``. The ``decision_id`` link is horizon-only (chorus never stores it).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dream.contracts import StaffingRequirement


@dataclass
class Goal:
    """horizon's rich goal — the middle of the Decision -> Goal -> Task spine."""

    id: str
    title: str
    decision_id: str | None = None  # the horizon-only decision this goal decomposed from
    parent_id: str | None = None
    status: str = "active"
    owner: str | None = None
    score: float = 0.0
    health: str = "unknown"
    metric: str | None = None
    target: str | None = None
    evidence: list[str] = field(default_factory=list)
    task_id: str | None = None  # the chorus task realizing this goal, once submitted
    root_task_id: str | None = None
    task_ids: list[str] = field(default_factory=list)
    team_id: str | None = None
    lead_id: str | None = None
    task_outcomes: dict[str, str] = field(default_factory=dict)
    delivery_shape: str = "single"
    lead_professions: tuple[str, ...] = ()
    staffing_requirements: tuple[StaffingRequirement, ...] = ()
    effective_score: float | None = None
    effective_priority: str | None = None
    priority_reason: str = ""
