"""``CandidateOpportunity`` + the ``Scout`` — cluster evidence into candidate theses (C-2).

The scout is a bounded reasoner pass (the same shape as the decomposer): it reads a batch of
:class:`~horizon.generation._evidence.EvidencePacket` and emits zero or more candidate opportunities —
a one-paragraph thesis plus the evidence that supports it. It only clusters + normalizes; it never
authors goals (that is the analyst, and only a human-approved proposal becomes real goals). Output is a
strict ``json_schema`` object, so what the system parses is typed at the API boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from horizon._ids import mint_id
from horizon._jsonio import extract_json
from horizon.errors import GenerationError
from horizon.generation._evidence import EvidencePacket
from horizon.planning._reasoner import Reasoner


@dataclass(frozen=True)
class CandidateOpportunity:
    """A scout-proposed thesis worth an analyst brief — evidence-referenced, not yet a decision."""

    id: str
    title: str
    thesis: str = ""  # one-paragraph "why this could be worth a decision"
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0..1, scout-declared


_PROMPT = """You are an opportunity scout for an autonomous software company.

You are given EVIDENCE — normalized signals from the org's own ledger, human seeds, and market data.
Cluster it into a small set of candidate OPPORTUNITIES that could be worth a strategic decision. Only
surface theses the evidence genuinely supports — do NOT invent goals, plans, or facts.

Rules:
- Produce 0 to 5 candidates (0 is valid if the evidence supports nothing actionable).
- Each candidate: a concrete `title`, a one-paragraph `thesis`, the `evidence_ids` that support it
  (ONLY ids that appear in the EVIDENCE below), and a `confidence` in [0,1].
- Output STRICT JSON only — no prose, no code fences — matching exactly:
  {"candidates": [{"title": "...", "thesis": "...", "evidence_ids": ["..."], "confidence": 0.0}]}

EVIDENCE:
__EVIDENCE__
"""

_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous reply could not be parsed. Reply with STRICT JSON ONLY — exactly "
    '{"candidates": [{"title": "...", "thesis": "...", "evidence_ids": ["..."], "confidence": 0.0}]} '
    "— no prose, no markdown, no code fences."
)

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "scout_candidates",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["candidates"],
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "thesis", "evidence_ids", "confidence"],
                        "properties": {
                            "title": {"type": "string"},
                            "thesis": {"type": "string"},
                            "evidence_ids": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number"},
                        },
                    },
                }
            },
        },
    },
}


def _clamp(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    if isinstance(value, str):
        try:
            return min(1.0, max(0.0, float(value)))
        except ValueError:
            return 0.0
    return 0.0


def _render_evidence(evidence: list[EvidencePacket]) -> str:
    return "\n".join(
        f"[{p.id}] ({p.source}, reliability={p.reliability:.2f}) {p.body}" for p in evidence
    )


class Scout:
    """Bounded reasoner pass: EvidencePackets -> candidate opportunities (structured output)."""

    def __init__(
        self,
        *,
        reasoner: Reasoner,
        model: str | None = None,
        max_output_tokens: int = 4000,
        structured: bool = True,
    ) -> None:
        self._reasoner = reasoner
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._structured = structured

    def survey(self, evidence: list[EvidencePacket]) -> list[CandidateOpportunity]:
        """Cluster the evidence into candidate opportunities; grounds evidence_ids to real packets."""
        if not evidence:
            return []
        known = {p.id for p in evidence}
        prompt = _PROMPT.replace("__EVIDENCE__", _render_evidence(evidence))
        params: dict[str, Any] = {"max_tokens": self._max_output_tokens}
        if self._model is not None:
            params["model"] = self._model
        if self._structured:
            params["response_format"] = _RESPONSE_FORMAT
        result = self._reasoner.complete(prompt, params)
        try:
            raw = self._parse(result.text)
        except GenerationError:
            fallback = {k: v for k, v in params.items() if k != "response_format"}
            retry = self._reasoner.complete(prompt + _RETRY_SUFFIX, fallback)
            raw = self._parse(retry.text)
        return [self._to_candidate(item, known) for item in raw]

    @staticmethod
    def _parse(text: str) -> list[dict[str, Any]]:
        try:
            data = json.loads(extract_json(text))
        except json.JSONDecodeError as exc:
            raise GenerationError(f"scout output was not valid JSON: {exc}") from exc
        items = data.get("candidates") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise GenerationError("scout returned no 'candidates' array")
        return [i for i in items if isinstance(i, dict) and str(i.get("title", "")).strip()]

    @staticmethod
    def _to_candidate(item: dict[str, Any], known: set[str]) -> CandidateOpportunity:
        refs = [str(r) for r in item.get("evidence_ids", []) if str(r) in known]  # ground to real ids
        return CandidateOpportunity(
            id=mint_id("cand"),
            title=str(item["title"]).strip(),
            thesis=str(item.get("thesis", "")).strip(),
            evidence_ids=refs,
            confidence=_clamp(item.get("confidence")),
        )
