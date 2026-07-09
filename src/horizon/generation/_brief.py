"""``DirectionBrief`` + ``CandidateGoal`` + the ``Analyst`` — the evidence-gated recommendation (C-3).

The analyst is a bounded reasoner pass that turns one :class:`CandidateOpportunity` (+ its supporting
evidence) into a ``DirectionBrief``: a recommended strategic move, its rationale, confidence, risks, and
the goals it would create. ``candidate_goals`` deliberately mirror horizon's decomposer output so an
approved brief flows straight into the live tree with no translation. Output is a strict ``json_schema``
object; ``passes_evidence_gate`` is the quality bar a brief must clear before it becomes a proposal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from horizon._jsonio import extract_json
from horizon.errors import GenerationError
from horizon.generation._evidence import EvidencePacket
from horizon.generation._scout import CandidateOpportunity
from horizon.planning._reasoner import Reasoner


@dataclass(frozen=True)
class CandidateGoal:
    """A goal an approved brief would create — the decomposer's goal shape, mirrored."""

    title: str
    metric: str = ""
    target: str = ""
    rationale: str = ""
    score: float = 0.0  # 0..1 relative priority (mirrors the decomposer's per-goal score)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CandidateGoal:
        return cls(
            title=str(raw.get("title", "")),
            metric=str(raw.get("metric", "")),
            target=str(raw.get("target", "")),
            rationale=str(raw.get("rationale", "")),
            score=float(raw.get("score", 0.0) or 0.0),
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


def passes_evidence_gate(
    brief: DirectionBrief, *, min_confidence: float = 0.6, min_evidence: int = 1
) -> bool:
    """The bar a brief must clear to become a proposal: real move, real goals, enough evidence."""
    return (
        bool(brief.recommendation.strip())
        and bool(brief.candidate_goals)
        and brief.confidence >= min_confidence
        and len(brief.evidence_refs) >= min_evidence
    )


_PROMPT = """You are a strategy analyst for an autonomous software company.

Given ONE candidate opportunity and its supporting EVIDENCE, produce a DirectionBrief: a recommended
strategic move, the rationale, your confidence, the risks, and the concrete GOALS it would create.
Ground every claim in the evidence — do NOT invent facts or data sources.

Rules:
- `recommendation` is a single strategic move, phrased as a decision statement.
- `candidate_goals`: 1 to 6 goals, each a deliverable one engineer completes whole, with `metric`,
  `target`, `rationale`, and a `score` in [0,1] (1 = do first).
- `confidence` in [0,1]; `risks` a short list; `evidence_refs` the evidence ids you relied on
  (ONLY ids from the EVIDENCE below).
- Output STRICT JSON only — no prose, no code fences — matching exactly:
  {"recommendation": "...", "rationale": "...", "confidence": 0.0, "risks": ["..."],
   "candidate_goals": [{"title": "...", "metric": "...", "target": "...", "rationale": "...",
   "score": 0.0}], "evidence_refs": ["..."]}

CANDIDATE:
__CANDIDATE__

EVIDENCE:
__EVIDENCE__
"""

_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous reply could not be parsed. Reply with STRICT JSON ONLY matching the "
    "schema above — no prose, no markdown, no code fences."
)

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "direction_brief",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "recommendation",
                "rationale",
                "confidence",
                "risks",
                "candidate_goals",
                "evidence_refs",
            ],
            "properties": {
                "recommendation": {"type": "string"},
                "rationale": {"type": "string"},
                "confidence": {"type": "number"},
                "risks": {"type": "array", "items": {"type": "string"}},
                "candidate_goals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "metric", "target", "rationale", "score"],
                        "properties": {
                            "title": {"type": "string"},
                            "metric": {"type": "string"},
                            "target": {"type": "string"},
                            "rationale": {"type": "string"},
                            "score": {"type": "number"},
                        },
                    },
                },
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


def _render_evidence(evidence: list[EvidencePacket]) -> str:
    return "\n".join(f"[{p.id}] ({p.source}) {p.body}" for p in evidence)


class Analyst:
    """Bounded reasoner pass: one candidate + its evidence -> a DirectionBrief (structured output)."""

    def __init__(
        self,
        *,
        reasoner: Reasoner,
        model: str | None = None,
        max_output_tokens: int = 6000,
        structured: bool = True,
    ) -> None:
        self._reasoner = reasoner
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._structured = structured

    def analyze(
        self, candidate: CandidateOpportunity, evidence: list[EvidencePacket]
    ) -> DirectionBrief:
        """Turn one candidate into a DirectionBrief; grounds evidence_refs to the real packets."""
        known = {p.id for p in evidence}
        prompt = _PROMPT.replace(
            "__CANDIDATE__", f"{candidate.title}\n{candidate.thesis}"
        ).replace("__EVIDENCE__", _render_evidence(evidence))
        params: dict[str, Any] = {"max_tokens": self._max_output_tokens}
        if self._model is not None:
            params["model"] = self._model
        if self._structured:
            params["response_format"] = _RESPONSE_FORMAT
        result = self._reasoner.complete(prompt, params)
        try:
            data = self._parse(result.text)
        except GenerationError:
            fallback = {k: v for k, v in params.items() if k != "response_format"}
            retry = self._reasoner.complete(prompt + _RETRY_SUFFIX, fallback)
            data = self._parse(retry.text)
        data["candidate_id"] = candidate.id
        data["evidence_refs"] = [r for r in data.get("evidence_refs", []) if str(r) in known]
        return DirectionBrief.from_dict(data)

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        try:
            data = json.loads(extract_json(text))
        except json.JSONDecodeError as exc:
            raise GenerationError(f"analyst output was not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or not str(data.get("recommendation", "")).strip():
            raise GenerationError("analyst returned no 'recommendation'")
        return data
