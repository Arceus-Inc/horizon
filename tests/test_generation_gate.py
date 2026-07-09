"""Theme C, slice C-gate: the minimal confirm-to-write approval gate.

Offline + deterministic — the promote step (seed + decompose + submit into the live tree) is injected as
a fake, so these prove the *gate*: status transitions, audit fields, previews-without-writes, and the
proposal-only invariant (only ``approve`` promotes, and only once).
"""

from __future__ import annotations

import pytest

from horizon.errors import ProposalNotOpen, UnknownProposal
from horizon.generation import (
    Approvals,
    CandidateGoal,
    DirectionBrief,
    Proposal,
    ProposalStore,
)

_NOW = "2026-07-10T00:00:00+00:00"


def _seed_proposal(store: ProposalStore, *, pid: str = "prop_x", status: str = "proposed") -> None:
    store.put(
        Proposal(
            id=pid,
            status=status,
            brief=DirectionBrief(
                candidate_id="c1",
                recommendation="Focus on region A",
                rationale="evidence",
                confidence=0.8,
                risks=["data may be stale"],
                candidate_goals=[CandidateGoal(title="Quantify", metric="profit", target="+10%")],
                evidence_refs=["ev_1"],
            ),
            decision_statement="Focus on region A",
            decision_rationale="evidence",
            created_at=_NOW,
        )
    )


def _gate(store: ProposalStore, promoted: list[Proposal]) -> Approvals:
    def promote(p: Proposal) -> str:
        promoted.append(p)
        return "dec_1"

    return Approvals(proposals=store, promote=promote, now=lambda: _NOW)


def test_list_proposals_filters_by_status(tmp_path):
    store = ProposalStore(tmp_path / "p.json")
    _seed_proposal(store, pid="a", status="proposed")
    _seed_proposal(store, pid="b", status="approved")
    gate = _gate(store, [])
    assert {p.id for p in gate.list_proposals(status="proposed")} == {"a"}
    assert {p.id for p in gate.list_proposals(status=None)} == {"a", "b"}  # None = all


def test_explain_previews_without_writing(tmp_path):
    store = ProposalStore(tmp_path / "p.json")
    _seed_proposal(store)
    gate = _gate(store, [])
    text = gate.explain("prop_x")
    assert "Focus on region A" in text  # the decision statement
    assert "Quantify" in text  # the candidate goal
    assert "ev_1" in text  # the evidence ref
    assert store.get("prop_x").status == "proposed"  # unchanged — a preview never writes


def test_approve_promotes_and_links(tmp_path):
    store = ProposalStore(tmp_path / "p.json")
    _seed_proposal(store)
    promoted: list[Proposal] = []
    gate = _gate(store, promoted)

    decision_id = gate.approve("prop_x", by="moe")

    assert decision_id == "dec_1"
    assert len(promoted) == 1 and promoted[0].id == "prop_x"  # promoted exactly once
    p = store.get("prop_x")
    assert p is not None
    assert p.status == "approved"
    assert p.decided_by == "moe"
    assert p.decided_at == _NOW
    assert p.linked_decision_id == "dec_1"


def test_approve_twice_is_blocked(tmp_path):
    store = ProposalStore(tmp_path / "p.json")
    _seed_proposal(store)
    promoted: list[Proposal] = []
    gate = _gate(store, promoted)
    gate.approve("prop_x", by="moe")
    with pytest.raises(ProposalNotOpen):
        gate.approve("prop_x", by="moe")
    assert len(promoted) == 1  # not promoted a second time


def test_reject_marks_rejected_with_note_and_never_promotes(tmp_path):
    store = ProposalStore(tmp_path / "p.json")
    _seed_proposal(store)
    promoted: list[Proposal] = []
    gate = _gate(store, promoted)

    gate.reject("prop_x", by="moe", reason="not this sprint")

    p = store.get("prop_x")
    assert p is not None
    assert p.status == "rejected"
    assert p.decided_by == "moe"
    assert p.note == "not this sprint"
    assert promoted == []


def test_reject_then_approve_is_blocked(tmp_path):
    store = ProposalStore(tmp_path / "p.json")
    _seed_proposal(store)
    gate = _gate(store, [])
    gate.reject("prop_x", by="moe", reason="no")
    with pytest.raises(ProposalNotOpen):
        gate.approve("prop_x", by="moe")


def test_unknown_proposal_raises(tmp_path):
    store = ProposalStore(tmp_path / "p.json")
    gate = _gate(store, [])
    with pytest.raises(UnknownProposal):
        gate.approve("nope", by="moe")
    with pytest.raises(UnknownProposal):
        gate.explain("nope")
