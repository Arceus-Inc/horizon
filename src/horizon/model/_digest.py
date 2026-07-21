"""``RealityDigest`` — the deterministic, bounded snapshot the CEO plans a roadmap against.

Assembled purely from horizon's read model (``DecisionState`` list) plus the optional capacity snapshot:
goals grouped by execution state (done / blocked / in_flight), a per-decision summary, a health
histogram, and capacity by profession. No LLM, no I/O — :func:`build_reality_digest` is a pure function
over the already-assembled state, so it is trivially testable and stable (order follows decision then
goal order). Archived decisions are excluded by the caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from dream.contracts import ProfessionCapacity

from horizon.model._state import DecisionState


@dataclass(frozen=True)
class GoalDigest:
    """One goal, flattened to the fields the CEO reasons over (a lean read of :class:`Goal`)."""

    id: str
    title: str
    decision_id: str | None
    status: str
    health: str
    score: float
    effective_priority: str | None
    metric: str | None
    target: str | None


@dataclass(frozen=True)
class DecisionDigest:
    """A one-line summary of a decision and how many goals hang off it."""

    id: str
    statement: str
    status: str
    goal_count: int


@dataclass(frozen=True)
class RealityDigest:
    """The bounded reality snapshot: decisions, goals grouped by state, health, and capacity."""

    decisions: tuple[DecisionDigest, ...] = ()
    goals_total: int = 0
    done: tuple[GoalDigest, ...] = ()
    blocked: tuple[GoalDigest, ...] = ()
    in_flight: tuple[GoalDigest, ...] = ()
    by_health: dict[str, int] = field(default_factory=dict)
    capacity: tuple[ProfessionCapacity, ...] = ()
    capacity_available: bool = False


def _goal_digest(goal) -> GoalDigest:
    return GoalDigest(
        id=goal.id,
        title=goal.title,
        decision_id=goal.decision_id,
        status=goal.status,
        health=goal.health,
        score=goal.score,
        effective_priority=goal.effective_priority,
        metric=goal.metric,
        target=goal.target,
    )


def build_reality_digest(
    states: Sequence[DecisionState],
    *,
    capacity: Sequence[ProfessionCapacity] | None = None,
) -> RealityDigest:
    """Fold assembled decision states (+ optional capacity) into the bounded reality digest.

    Grouping: a goal is **done** when its status is ``"done"``; otherwise **blocked** when its health is
    ``"blocked"``; otherwise **in_flight``. The health histogram counts every goal. Pure + deterministic.
    """
    decisions: list[DecisionDigest] = []
    done: list[GoalDigest] = []
    blocked: list[GoalDigest] = []
    in_flight: list[GoalDigest] = []
    by_health: dict[str, int] = {}
    total = 0

    for state in states:
        decisions.append(
            DecisionDigest(
                id=state.decision.id,
                statement=state.decision.statement,
                status=state.decision.status,
                goal_count=len(state.goals),
            )
        )
        for goal in state.goals:
            total += 1
            by_health[goal.health] = by_health.get(goal.health, 0) + 1
            digest = _goal_digest(goal)
            if goal.status == "done":
                done.append(digest)
            elif goal.health == "blocked":
                blocked.append(digest)
            else:
                in_flight.append(digest)

    return RealityDigest(
        decisions=tuple(decisions),
        goals_total=total,
        done=tuple(done),
        blocked=tuple(blocked),
        in_flight=tuple(in_flight),
        by_health=by_health,
        capacity=tuple(capacity) if capacity is not None else (),
        capacity_available=capacity is not None,
    )
