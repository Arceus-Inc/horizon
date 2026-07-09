"""``DirectionBrief`` + ``CandidateGoal`` — the analyst's evidence-gated recommendation (C3).

The analyst (a bounded, reused chorus employee — landed in C3) turns one :class:`CandidateOpportunity`
into a ``DirectionBrief``: a recommended strategic move, its rationale, confidence, risks, and the goals
it would decompose into. ``candidate_goals`` deliberately mirror horizon's decomposer output so an
approved brief flows straight into ``decompose``/``submit`` with no translation. This module holds the
shapes; the analyst-beat wrapper arrives in slice C-3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CandidateGoal:
    """A goal an approved brief would create — the decomposer's goal shape, mirrored."""

    title: str
    metric: str = ""
    target: str = ""
    rationale: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CandidateGoal:
        return cls(
            title=str(raw.get("title", "")),
            metric=str(raw.get("metric", "")),
            target=str(raw.get("target", "")),
            rationale=str(raw.get("rationale", "")),
        )


@dataclass(frozen=True)
class DirectionBrief:
    """An analyst recommendation — evidence-referenced, confidence-scored, goal-shaped."""

    candidate_id: str
    recommendation: str  # the proposed strategic move (becomes a decision statement)
    rationale: str = ""
    confidence: float = 0.0  # 0..1, analyst-declared
    risks: list[str] = field(default_factory=list)
    candidate_goals: list[CandidateGoal] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)  # packet ids (auditable)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DirectionBrief:
        return cls(
            candidate_id=str(raw.get("candidate_id", "")),
            recommendation=str(raw.get("recommendation", "")),
            rationale=str(raw.get("rationale", "")),
            confidence=float(raw.get("confidence", 0.0) or 0.0),
            risks=list(raw.get("risks", []) or []),
            candidate_goals=[CandidateGoal.from_dict(g) for g in raw.get("candidate_goals", []) or []],
            evidence_refs=list(raw.get("evidence_refs", []) or []),
        )
