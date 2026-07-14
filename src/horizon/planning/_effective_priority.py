"""Capacity-informed effective priority without mutating strategic value."""

from __future__ import annotations

from dataclasses import dataclass, field

from horizon.intake import ScorePolicy
from horizon.ports import Priority, ProfessionCapacity, StaffingRequirement

LoadBand = tuple[float, float, str]


@dataclass(frozen=True)
class EffectiveResult:
    """The execution-aware score and the facts that produced it."""

    score: float
    priority: Priority
    reason: str


@dataclass(frozen=True)
class EffectivePriorityPolicy:
    """Apply configurable load and dependency weights to a raw strategic score."""

    load_bands: tuple[LoadBand, ...] = (
        (0.5, 1.0, "low"),
        (1.5, 0.75, "moderate"),
        (float("inf"), 0.5, "heavy"),
    )
    dependency_multiplier: float = 0.5
    score_policy: ScorePolicy = field(default_factory=ScorePolicy)

    def evaluate(
        self,
        *,
        raw_score: float,
        requirements: tuple[StaffingRequirement, ...],
        capacities: tuple[ProfessionCapacity, ...],
        dependencies_ready: bool = True,
    ) -> EffectiveResult:
        """Return execution-aware priority while leaving ``raw_score`` untouched."""
        score = min(1.0, max(0.0, raw_score))
        by_profession = {capacity.profession: capacity for capacity in capacities}
        loads: list[tuple[str, float, int, int]] = []
        budget_notes: list[str] = []

        for requirement in requirements:
            capacity = by_profession.get(requirement.profession)
            if capacity is None or capacity.eligible < requirement.count:
                return EffectiveResult(
                    score=0.0,
                    priority="staffing_blocked",
                    reason=f"staffing_blocked: insufficient eligible {requirement.profession} capacity",
                )
            available = max(0, capacity.eligible - capacity.budget_blocked)
            if available < requirement.count:
                return EffectiveResult(
                    score=0.0,
                    priority="staffing_blocked",
                    reason=(
                        f"staffing_blocked: {requirement.profession} capacity is budget blocked "
                        f"({available}/{requirement.count} available)"
                    ),
                )
            active = capacity.running + capacity.assigned_nonterminal + capacity.queued_wakes
            loads.append((requirement.profession, active / available, active, available))
            if capacity.budget_blocked or capacity.budget_headroom_cents == 0:
                budget_notes.append(f"{requirement.profession} budget constrained")

        worst_load = max((load for _, load, _, _ in loads), default=0.0)
        multiplier, load_label = self._load_weight(worst_load)
        if not dependencies_ready:
            multiplier *= self.dependency_multiplier
        effective_score = round(score * multiplier, 4)
        load_detail = ", ".join(
            f"{profession} load {active}/{available}"
            for profession, _, active, available in loads
        ) or "no staffing requirements"
        reason_parts = [f"{load_label} load: {load_detail}"]
        reason_parts.extend(budget_notes or ["budget healthy"])
        if not dependencies_ready:
            reason_parts.append("dependencies not ready")
        return EffectiveResult(
            score=effective_score,
            priority=self.score_policy.priority_for(effective_score),
            reason="; ".join(reason_parts),
        )

    def _load_weight(self, load: float) -> tuple[float, str]:
        for maximum, multiplier, label in self.load_bands:
            if load <= maximum:
                return multiplier, label
        raise ValueError("load_bands must cover all possible loads")
