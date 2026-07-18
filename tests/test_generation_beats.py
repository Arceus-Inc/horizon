"""Theme C, slices C-2 + C-3: the Scout and Analyst reasoner passes (structured output).

Offline + deterministic — a scripted substrate returns canned strict-JSON, so these prove the parse,
the evidence grounding (refs pinned to real packets), the retry-on-bad-JSON fallback, and the evidence
gate — without a live LLM. One live smoke of each lives behind the ``live`` marker elsewhere.
"""

from __future__ import annotations

import json

from horizon.generation import (
    Analyst,
    CandidateGoal,
    CandidateOpportunity,
    DirectionBrief,
    EvidencePacket,
    Scout,
    passes_evidence_gate,
)
from tests.fakes import FakeSubstrate, SequenceSubstrate


def _evidence():
    return [
        EvidencePacket(
            id="ev_1", source="chorus.internal", kind="signal", body="Region A margins up"
        ),
        EvidencePacket(id="ev_2", source="seed", kind="note", body="Cofounder: double down on A"),
    ]


# --- C-2: Scout ---------------------------------------------------------------


def test_scout_parses_candidates_and_grounds_evidence_ids():
    reply = json.dumps(
        {
            "candidates": [
                {
                    "title": "Concentrate on region A",
                    "thesis": "A is outperforming",
                    "evidence_ids": ["ev_1", "ev_2", "ev_ghost"],  # ghost must be dropped
                    "confidence": 0.82,
                }
            ]
        }
    )
    scout = Scout(reasoner=FakeSubstrate(reply))
    cands = scout.survey(_evidence())
    assert len(cands) == 1
    c = cands[0]
    assert c.title == "Concentrate on region A"
    assert c.id.startswith("cand_")
    assert c.evidence_ids == ["ev_1", "ev_2"]  # ev_ghost dropped — grounded to real packets
    assert c.confidence == 0.82


def test_scout_returns_empty_on_no_evidence_without_calling_the_model():
    sub = FakeSubstrate("should not be called")
    assert Scout(reasoner=sub).survey([]) == []
    assert sub.calls == []


def test_scout_sends_structured_response_format():
    scout = Scout(reasoner=(sub := FakeSubstrate(json.dumps({"candidates": []}))))
    scout.survey(_evidence())
    assert sub.params[-1]["response_format"]["json_schema"]["name"] == "scout_candidates"


def test_scout_retries_without_schema_on_bad_json():
    sub = SequenceSubstrate(["not json at all", json.dumps({"candidates": []})])
    Scout(reasoner=sub).survey(_evidence())
    assert len(sub.calls) == 2  # first failed parse -> retried
    assert "response_format" not in sub.params[-1]  # retry dropped the schema


# --- C-3: Analyst -------------------------------------------------------------


def _candidate():
    return CandidateOpportunity(
        id="cand_1", title="Concentrate on region A", thesis="A outperforms", evidence_ids=["ev_1"]
    )


def test_analyst_parses_a_brief_and_pins_candidate_and_refs():
    reply = json.dumps(
        {
            "recommendation": "Shift next-quarter investment to region A",
            "rationale": "A has the best margins",
            "confidence": 0.75,
            "risks": ["data may be stale"],
            "candidate_goals": [
                {
                    "title": "Quantify A upside",
                    "metric": "incremental profit",
                    "target": "+10%",
                    "rationale": "ground it",
                    "score": 0.9,
                }
            ],
            "evidence_refs": ["ev_1", "ev_ghost"],  # ghost dropped
        }
    )
    brief = Analyst(reasoner=FakeSubstrate(reply)).analyze(_candidate(), _evidence())
    assert isinstance(brief, DirectionBrief)
    assert brief.candidate_id == "cand_1"  # pinned from the candidate, not the model
    assert brief.recommendation == "Shift next-quarter investment to region A"
    assert brief.evidence_refs == ["ev_1"]  # ev_ghost dropped — grounded
    assert brief.candidate_goals[0].metric == "incremental profit"
    assert brief.candidate_goals[0].score == 0.9


def test_analyst_retries_without_schema_on_bad_json():
    good = json.dumps(
        {
            "recommendation": "Do the thing",
            "rationale": "r",
            "confidence": 0.7,
            "risks": [],
            "candidate_goals": [
                {"title": "g", "metric": "m", "target": "t", "rationale": "r", "score": 0.5}
            ],
            "evidence_refs": ["ev_1"],
        }
    )
    sub = SequenceSubstrate(["garbage", good])
    Analyst(reasoner=sub).analyze(_candidate(), _evidence())
    assert len(sub.calls) == 2
    assert "response_format" not in sub.params[-1]


# --- the evidence gate --------------------------------------------------------


def test_evidence_gate_passes_a_strong_brief():
    brief = DirectionBrief(
        candidate_id="c1",
        recommendation="Do it",
        confidence=0.7,
        candidate_goals=[CandidateGoal(title="g")],
        evidence_refs=["ev_1"],
    )
    assert passes_evidence_gate(brief)


def test_evidence_gate_rejects_low_confidence_or_no_evidence_or_no_goals():
    strong_goals = [CandidateGoal(title="g")]
    assert not passes_evidence_gate(  # low confidence
        DirectionBrief(
            candidate_id="c",
            recommendation="x",
            confidence=0.4,
            candidate_goals=strong_goals,
            evidence_refs=["ev_1"],
        )
    )
    assert not passes_evidence_gate(  # no evidence
        DirectionBrief(
            candidate_id="c",
            recommendation="x",
            confidence=0.9,
            candidate_goals=strong_goals,
            evidence_refs=[],
        )
    )
    assert not passes_evidence_gate(  # no goals
        DirectionBrief(
            candidate_id="c",
            recommendation="x",
            confidence=0.9,
            candidate_goals=[],
            evidence_refs=["ev_1"],
        )
    )
