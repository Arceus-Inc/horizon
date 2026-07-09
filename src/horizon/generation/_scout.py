"""``CandidateOpportunity`` — a scout's normalized thesis from clustered evidence (C2).

The scout (a bounded beat, landed in C2) reads a batch of :class:`EvidencePacket` and emits zero or more
candidate opportunities: a one-paragraph thesis plus the evidence that supports it. It only clusters +
normalizes — it never authors goals. This module holds the shape; the beat itself arrives in slice C-2.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CandidateOpportunity:
    """A scout-proposed thesis worth an analyst brief — evidence-referenced, not yet a decision."""

    id: str
    title: str
    thesis: str = ""  # one-paragraph "why this could be worth a decision"
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0..1, scout-declared
