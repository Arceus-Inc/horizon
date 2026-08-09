"""Systemic capability-gap detection stays pure and deterministic."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from horizon.planning import (
    CapabilityFailureEvidence,
    CapabilityGapDetector,
    CapabilityGapPolicy,
    CapabilitySeverity,
)


def _failure(
    evidence_ref: str,
    trajectory_ref: str,
    *,
    capability_id: str = "capability.auth",
    agent_id: str = "agent_a",
    task_id: str = "task_a",
    severity: CapabilitySeverity = CapabilitySeverity.HIGH,
    confidence: float = 0.8,
) -> CapabilityFailureEvidence:
    return CapabilityFailureEvidence(
        evidence_ref=evidence_ref,
        trajectory_ref=trajectory_ref,
        agent_id=agent_id,
        task_id=task_id,
        capability_id=capability_id,
        severity=severity,
        confidence=confidence,
        observed_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )


def test_detects_a_systemic_gap_with_ordered_raw_provenance() -> None:
    evidence = (
        _failure("ev_1", "tr_1", severity=CapabilitySeverity.HIGH, confidence=0.7),
        _failure(
            "ev_2",
            "tr_2",
            agent_id="agent_b",
            task_id="task_b",
            severity=CapabilitySeverity.CRITICAL,
            confidence=0.9,
        ),
        _failure("ev_3", "tr_3", capability_id="capability.search"),
    )

    gaps = CapabilityGapDetector(CapabilityGapPolicy()).detect(evidence)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.capability_id == "capability.auth"
    assert tuple(item.evidence_ref for item in gap.provenance) == ("ev_1", "ev_2")
    assert gap.agent_ids == ("agent_a", "agent_b")
    assert gap.task_ids == ("task_a", "task_b")
    assert gap.recurrence_count == 2
    assert gap.confidence == 0.8
    assert gap.severity is CapabilitySeverity.CRITICAL
    assert gap.priority_reason == (
        "critical severity; 2 trajectories; 2 agents; 2 tasks; confidence 0.800"
    )
    with pytest.raises(FrozenInstanceError):
        gap.recurrence_count = 3  # type: ignore[misc]


def test_uses_distinct_tasks_when_agents_do_not_meet_the_breadth_threshold() -> None:
    policy = CapabilityGapPolicy(minimum_distinct_agents=3, minimum_distinct_tasks=2)
    evidence = (
        _failure("ev_1", "tr_1", task_id="task_a"),
        _failure("ev_2", "tr_2", task_id="task_b"),
    )

    gaps = CapabilityGapDetector(policy).detect(evidence)

    assert len(gaps) == 1
    assert gaps[0].task_ids == ("task_a", "task_b")


def test_never_turns_a_single_or_narrow_recurrence_into_a_gap() -> None:
    detector = CapabilityGapDetector(CapabilityGapPolicy())

    assert detector.detect((_failure("ev_1", "tr_1"),)) == ()
    assert detector.detect(
        (_failure("ev_1", "tr_1"), _failure("ev_2", "tr_2"))
    ) == ()


@pytest.mark.parametrize(
    ("first", "second", "message"),
    (
        (_failure("ev_1", "tr_1"), _failure("ev_1", "tr_2"), "duplicate evidence_ref: ev_1"),
        (_failure("ev_1", "tr_1"), _failure("ev_2", "tr_1"), "duplicate trajectory_ref: tr_1"),
    ),
)
def test_rejects_duplicate_provenance_references(
    first: CapabilityFailureEvidence,
    second: CapabilityFailureEvidence,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        CapabilityGapDetector(CapabilityGapPolicy()).detect((first, second))


def test_rejects_blank_identifiers() -> None:
    with pytest.raises(ValueError, match=r"^evidence_ref must not be blank$"):
        _failure("", "tr_1")
    with pytest.raises(ValueError, match=r"^trajectory_ref must not be blank$"):
        _failure("ev_1", " ")
    with pytest.raises(ValueError, match=r"^agent_id must not be blank$"):
        _failure("ev_1", "tr_1", agent_id=" ")
    with pytest.raises(ValueError, match=r"^task_id must not be blank$"):
        _failure("ev_1", "tr_1", task_id="")
    with pytest.raises(ValueError, match=r"^capability_id must not be blank$"):
        _failure("ev_1", "tr_1", capability_id="\t")


def test_rejects_naive_observation_time() -> None:
    evidence = _failure("ev_1", "tr_1")
    with pytest.raises(ValueError, match=r"^observed_at must be timezone-aware$"):
        CapabilityFailureEvidence(
            evidence_ref=evidence.evidence_ref,
            trajectory_ref=evidence.trajectory_ref,
            agent_id=evidence.agent_id,
            task_id=evidence.task_id,
            capability_id=evidence.capability_id,
            severity=evidence.severity,
            confidence=evidence.confidence,
            observed_at=datetime(2026, 8, 9, 12),
        )


@pytest.mark.parametrize("confidence", (-0.01, 1.01, float("inf")))
def test_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match=r"^confidence must be between 0.0 and 1.0$"):
        _failure("ev_1", "tr_1", confidence=confidence)


def test_rejects_invalid_policy() -> None:
    with pytest.raises(ValueError, match=r"^minimum_trajectories must be at least 2$"):
        CapabilityGapPolicy(minimum_trajectories=1)
    with pytest.raises(ValueError, match=r"^minimum_distinct_agents must be at least 1$"):
        CapabilityGapPolicy(minimum_distinct_agents=0)
    with pytest.raises(ValueError, match=r"^minimum_distinct_tasks must be at least 1$"):
        CapabilityGapPolicy(minimum_distinct_tasks=0)


def test_priority_increases_with_criticality_recurrence_breadth_and_confidence() -> None:
    detector = CapabilityGapDetector(CapabilityGapPolicy())
    low_criticality = detector.detect(
        (
            _failure("ev_1", "tr_1", capability_id="low", severity=CapabilitySeverity.LOW),
            _failure(
                "ev_2",
                "tr_2",
                capability_id="low",
                agent_id="agent_b",
                task_id="task_b",
                severity=CapabilitySeverity.LOW,
            ),
        )
    )[0]
    high_criticality = detector.detect(
        (
            _failure("ev_3", "tr_3", capability_id="critical", severity=CapabilitySeverity.CRITICAL),
            _failure(
                "ev_4",
                "tr_4",
                capability_id="critical",
                agent_id="agent_b",
                task_id="task_b",
                severity=CapabilitySeverity.CRITICAL,
            ),
        )
    )[0]
    lower_confidence = detector.detect(
        (
            _failure("ev_5", "tr_5", capability_id="confidence", confidence=0.2),
            _failure(
                "ev_6",
                "tr_6",
                capability_id="confidence",
                agent_id="agent_b",
                task_id="task_b",
                confidence=0.2,
            ),
        )
    )[0]
    higher_confidence = detector.detect(
        (
            _failure("ev_7", "tr_7", capability_id="confidence-high", confidence=0.9),
            _failure(
                "ev_8",
                "tr_8",
                capability_id="confidence-high",
                agent_id="agent_b",
                task_id="task_b",
                confidence=0.9,
            ),
        )
    )[0]
    lower_recurrence = detector.detect(
        (
            _failure("ev_9", "tr_9", capability_id="recurrence"),
            _failure(
                "ev_10", "tr_10", capability_id="recurrence", agent_id="agent_b", task_id="task_b"
            ),
        )
    )[0]
    higher_recurrence = detector.detect(
        (
            _failure("ev_11", "tr_11", capability_id="recurrence-high"),
            _failure(
                "ev_12",
                "tr_12",
                capability_id="recurrence-high",
                agent_id="agent_b",
                task_id="task_b",
            ),
            _failure("ev_13", "tr_13", capability_id="recurrence-high"),
        )
    )[0]
    lower_breadth = detector.detect(
        (
            _failure("ev_14", "tr_14", capability_id="breadth"),
            _failure("ev_15", "tr_15", capability_id="breadth", agent_id="agent_b", task_id="task_b"),
            _failure("ev_16", "tr_16", capability_id="breadth"),
        )
    )[0]
    higher_breadth = detector.detect(
        (
            _failure("ev_17", "tr_17", capability_id="breadth-high"),
            _failure(
                "ev_18", "tr_18", capability_id="breadth-high", agent_id="agent_b", task_id="task_b"
            ),
            _failure(
                "ev_19", "tr_19", capability_id="breadth-high", agent_id="agent_c", task_id="task_c"
            ),
        )
    )[0]

    assert high_criticality.priority_score > low_criticality.priority_score
    assert higher_confidence.priority_score > lower_confidence.priority_score
    assert higher_recurrence.priority_score > lower_recurrence.priority_score
    assert higher_breadth.priority_score > lower_breadth.priority_score


def test_each_breadth_dimension_contributes_independently() -> None:
    detector = CapabilityGapDetector(CapabilityGapPolicy())
    two_agents = detector.detect(
        (
            _failure("ev_1", "tr_1", capability_id="two-agents"),
            _failure("ev_2", "tr_2", capability_id="two-agents", agent_id="agent_b", task_id="task_b"),
            _failure("ev_3", "tr_3", capability_id="two-agents", task_id="task_c"),
        )
    )[0]
    three_agents = detector.detect(
        (
            _failure("ev_4", "tr_4", capability_id="three-agents"),
            _failure("ev_5", "tr_5", capability_id="three-agents", agent_id="agent_b", task_id="task_b"),
            _failure("ev_6", "tr_6", capability_id="three-agents", agent_id="agent_c", task_id="task_c"),
        )
    )[0]

    assert three_agents.priority_score > two_agents.priority_score


def test_orders_equal_priority_gaps_by_capability_id() -> None:
    gaps = CapabilityGapDetector(CapabilityGapPolicy()).detect(
        (
            _failure("ev_1", "tr_1", capability_id="zeta"),
            _failure("ev_2", "tr_2", capability_id="zeta", agent_id="agent_b", task_id="task_b"),
            _failure("ev_3", "tr_3", capability_id="alpha"),
            _failure("ev_4", "tr_4", capability_id="alpha", agent_id="agent_b", task_id="task_b"),
        )
    )

    assert tuple(gap.capability_id for gap in gaps) == ("alpha", "zeta")
