"""Pure detection of recurring capability failures for later improvement planning."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite


class CapabilitySeverity(StrEnum):
    """The criticality of one failed capability attempt."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def priority_weight(self) -> float:
        """Return the fixed criticality contribution to a strategic priority score."""
        if self is CapabilitySeverity.LOW:
            return 0.25
        if self is CapabilitySeverity.MEDIUM:
            return 0.5
        if self is CapabilitySeverity.HIGH:
            return 0.75
        return 1.0


@dataclass(frozen=True)
class CapabilityFailureEvidence:
    """One attributable failed capability observation from an agent trajectory."""

    evidence_ref: str
    trajectory_ref: str
    agent_id: str
    task_id: str
    capability_id: str
    severity: CapabilitySeverity
    confidence: float
    observed_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.evidence_ref, "evidence_ref"),
            (self.trajectory_ref, "trajectory_ref"),
            (self.agent_id, "agent_id"),
            (self.task_id, "task_id"),
            (self.capability_id, "capability_id"),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not isinstance(self.severity, CapabilitySeverity):
            raise ValueError("severity must be a CapabilitySeverity")
        if not isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True)
class CapabilityGapPolicy:
    """The explicit recurrence and breadth thresholds for systemic-gap detection."""

    minimum_trajectories: int = 2
    minimum_distinct_agents: int = 2
    minimum_distinct_tasks: int = 2

    def __post_init__(self) -> None:
        self._validate_count(self.minimum_trajectories, "minimum_trajectories", minimum=2)
        self._validate_count(self.minimum_distinct_agents, "minimum_distinct_agents", minimum=1)
        self._validate_count(self.minimum_distinct_tasks, "minimum_distinct_tasks", minimum=1)

    @staticmethod
    def _validate_count(value: int, name: str, *, minimum: int) -> None:
        if type(value) is not int:
            raise ValueError(f"{name} must be an integer")
        if value < minimum:
            raise ValueError(f"{name} must be at least {minimum}")


@dataclass(frozen=True)
class CapabilityGap:
    """A systemic failure pattern, retaining its raw evidence in incoming order."""

    capability_id: str
    provenance: tuple[CapabilityFailureEvidence, ...]
    agent_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    recurrence_count: int
    confidence: float
    severity: CapabilitySeverity
    priority_score: float
    priority_reason: str

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("capability_id must not be blank")
        if not self.provenance:
            raise ValueError("capability gap requires provenance")
        if any(item.capability_id != self.capability_id for item in self.provenance):
            raise ValueError("capability gap provenance must match capability_id")
        if self.recurrence_count != len(self.provenance):
            raise ValueError("recurrence_count must match provenance")
        if self.agent_ids != tuple(sorted(set(self.agent_ids))):
            raise ValueError("agent_ids must be unique and sorted")
        if self.task_ids != tuple(sorted(set(self.task_ids))):
            raise ValueError("task_ids must be unique and sorted")
        if not isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not isinstance(self.severity, CapabilitySeverity):
            raise ValueError("severity must be a CapabilitySeverity")
        if not isfinite(self.priority_score) or not 0.0 <= self.priority_score <= 1.0:
            raise ValueError("priority_score must be between 0.0 and 1.0")
        if not self.priority_reason.strip():
            raise ValueError("priority_reason must not be blank")


@dataclass(frozen=True)
class CapabilityGapDetector:
    """Group ordered failure evidence into recurring, broad capability gaps."""

    policy: CapabilityGapPolicy

    def detect(
        self, evidence: tuple[CapabilityFailureEvidence, ...]
    ) -> tuple[CapabilityGap, ...]:
        """Return deterministic strategic gaps; one-off failures are deliberately excluded."""
        self._reject_duplicate_references(evidence)
        gaps: tuple[CapabilityGap, ...] = ()
        for capability_id in _distinct_in_order(item.capability_id for item in evidence):
            provenance = tuple(item for item in evidence if item.capability_id == capability_id)
            agent_ids = tuple(sorted(_distinct_in_order(item.agent_id for item in provenance)))
            task_ids = tuple(sorted(_distinct_in_order(item.task_id for item in provenance)))
            if not self._is_systemic(provenance, agent_ids, task_ids):
                continue
            severity = self._highest_severity(provenance)
            confidence = round(sum(item.confidence for item in provenance) / len(provenance), 4)
            priority_score = self._priority_score(
                severity=severity,
                recurrence_count=len(provenance),
                agent_count=len(agent_ids),
                task_count=len(task_ids),
                confidence=confidence,
            )
            gaps += (
                CapabilityGap(
                    capability_id=capability_id,
                    provenance=provenance,
                    agent_ids=agent_ids,
                    task_ids=task_ids,
                    recurrence_count=len(provenance),
                    confidence=confidence,
                    severity=severity,
                    priority_score=priority_score,
                    priority_reason=(
                        f"{severity.value} severity; {len(provenance)} trajectories; "
                        f"{len(agent_ids)} agents; {len(task_ids)} tasks; confidence {confidence:.3f}"
                    ),
                ),
            )
        return tuple(sorted(gaps, key=lambda gap: (-gap.priority_score, gap.capability_id)))

    def _reject_duplicate_references(
        self, evidence: tuple[CapabilityFailureEvidence, ...]
    ) -> None:
        evidence_refs: tuple[str, ...] = ()
        trajectory_refs: tuple[str, ...] = ()
        for item in evidence:
            if item.evidence_ref in evidence_refs:
                raise ValueError(f"duplicate evidence_ref: {item.evidence_ref}")
            if item.trajectory_ref in trajectory_refs:
                raise ValueError(f"duplicate trajectory_ref: {item.trajectory_ref}")
            evidence_refs += (item.evidence_ref,)
            trajectory_refs += (item.trajectory_ref,)

    def _is_systemic(
        self,
        provenance: tuple[CapabilityFailureEvidence, ...],
        agent_ids: tuple[str, ...],
        task_ids: tuple[str, ...],
    ) -> bool:
        return len(provenance) >= self.policy.minimum_trajectories and (
            len(agent_ids) >= self.policy.minimum_distinct_agents
            or len(task_ids) >= self.policy.minimum_distinct_tasks
        )

    @staticmethod
    def _highest_severity(
        provenance: tuple[CapabilityFailureEvidence, ...],
    ) -> CapabilitySeverity:
        severity = CapabilitySeverity.LOW
        for item in provenance:
            if item.severity.priority_weight > severity.priority_weight:
                severity = item.severity
        return severity

    @staticmethod
    def _priority_score(
        *,
        severity: CapabilitySeverity,
        recurrence_count: int,
        agent_count: int,
        task_count: int,
        confidence: float,
    ) -> float:
        recurrence = min(recurrence_count, 5) / 5
        breadth = (min(agent_count, 5) + min(task_count, 5)) / 10
        return round(
            0.4 * severity.priority_weight + 0.3 * recurrence + 0.2 * breadth + 0.1 * confidence,
            4,
        )


def _distinct_in_order(values: Iterable[str]) -> tuple[str, ...]:
    """Return values once, preserving evidence order without mutable grouping state."""
    distinct: tuple[str, ...] = ()
    for value in values:
        if value not in distinct:
            distinct += (value,)
    return distinct
