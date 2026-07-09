"""Theme C, slices C-0 + C-4: the generation-funnel data shapes, ProposalStore, and Reconciler.

Offline + deterministic — no LLM, no beats. Proves the *tail* of the funnel (briefs -> proposals ->
storage), which is the part an approval gate later reads. The scout/analyst beats (C-2/C-3) come later.
"""

from __future__ import annotations

from horizon.generation import (
    CandidateGoal,
    DirectionBrief,
    Proposal,
    ProposalStore,
    Reconciler,
    proposal_id,
)
from horizon.model import Decision
from horizon.store import DecisionStore

_FIXED_NOW = "2026-07-10T00:00:00+00:00"


def _brief(recommendation: str, *, confidence: float = 0.8) -> DirectionBrief:
    return DirectionBrief(
        candidate_id="cand_1",
        recommendation=recommendation,
        rationale="because the evidence points here",
        confidence=confidence,
        risks=["data may be stale"],
        candidate_goals=[
            CandidateGoal(
                title="Quantify the opportunity",
                metric="incremental profit",
                target="+10% QoQ",
                rationale="ground it in numbers",
            )
        ],
        evidence_refs=["ev_1", "ev_2"],
    )


# --- C-0: shapes + ProposalStore round-trip -----------------------------------


def test_proposal_id_is_deterministic_and_normalizes_statement():
    a = proposal_id("Focus sales investment on region A")
    assert a == proposal_id("  focus   SALES investment on Region A ")  # normalized-equal
    assert a.startswith("prop_")
    assert a != proposal_id("Focus sales investment on region B")


def test_proposal_store_round_trips_a_nested_brief(tmp_path):
    store = ProposalStore(tmp_path / "proposals.json")
    p = Proposal(
        id="prop_x",
        status="proposed",
        brief=_brief("Concentrate investment in the top region"),
        decision_statement="Concentrate investment in the top region",
        decision_rationale="evidence",
        created_at=_FIXED_NOW,
    )
    store.put(p)
    got = store.get("prop_x")
    assert got == p  # full equality incl. the nested DirectionBrief + CandidateGoal
    assert got is not None and got.brief is not None
    assert got.brief.candidate_goals[0].metric == "incremental profit"


def test_proposal_store_put_overwrites_same_id_and_all_lists(tmp_path):
    store = ProposalStore(tmp_path / "proposals.json")
    store.put(Proposal(id="prop_x", status="proposed"))
    store.put(Proposal(id="prop_x", status="approved", decided_by="moe"))
    assert store.get("prop_x").status == "approved"
    assert len(store.all()) == 1


def test_proposal_store_missing_is_none(tmp_path):
    assert ProposalStore(tmp_path / "proposals.json").get("nope") is None


# --- C-4: Reconciler (briefs -> proposals, deduped) ---------------------------


def test_reconcile_creates_a_proposed_proposal(tmp_path):
    store = ProposalStore(tmp_path / "proposals.json")
    rec = Reconciler(proposals=store, now=lambda: _FIXED_NOW)

    created = rec.reconcile([_brief("Shift budget toward region A")])

    assert len(created) == 1
    p = created[0]
    assert p.status == "proposed"
    assert p.decision_statement == "Shift budget toward region A"
    assert p.decision_rationale == "because the evidence points here"
    assert p.created_at == _FIXED_NOW
    assert p.brief is not None and p.brief.candidate_goals  # brief carried through
    assert store.get(p.id) == p  # persisted


def test_reconcile_is_idempotent_on_the_same_statement(tmp_path):
    store = ProposalStore(tmp_path / "proposals.json")
    rec = Reconciler(proposals=store, now=lambda: _FIXED_NOW)

    first = rec.reconcile([_brief("Shift budget toward region A")])
    again = rec.reconcile([_brief("  shift   BUDGET toward Region A ")])  # normalized-equal

    assert len(first) == 1
    assert again == []  # no new proposal
    assert len(store.all()) == 1


def test_reconcile_skips_statements_that_match_a_live_decision(tmp_path):
    proposals = ProposalStore(tmp_path / "proposals.json")
    decisions = DecisionStore(tmp_path / "decisions.json")
    decisions.put(Decision(id="dec_1", statement="Grow profit in region A", status="active"))
    rec = Reconciler(proposals=proposals, decisions=decisions, now=lambda: _FIXED_NOW)

    created = rec.reconcile([_brief("  grow   profit in Region A ")])  # already a live decision

    assert created == []
    assert proposals.all() == []


def test_reconcile_skips_blank_recommendations(tmp_path):
    store = ProposalStore(tmp_path / "proposals.json")
    rec = Reconciler(proposals=store, now=lambda: _FIXED_NOW)
    assert rec.reconcile([_brief("   ")]) == []
    assert store.all() == []


def test_reconcile_returns_only_newly_created(tmp_path):
    store = ProposalStore(tmp_path / "proposals.json")
    rec = Reconciler(proposals=store, now=lambda: _FIXED_NOW)

    created = rec.reconcile(
        [
            _brief("Move into the enterprise segment"),
            _brief("Move into the enterprise segment"),  # dup within the batch
            _brief("Double down on SMB"),
        ]
    )

    assert {p.decision_statement for p in created} == {
        "Move into the enterprise segment",
        "Double down on SMB",
    }
    assert len(store.all()) == 2
