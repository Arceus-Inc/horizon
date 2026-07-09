"""generation — evidence -> **DirectionBrief** -> *proposed* decisions/goals (Theme C, proposal-only).

A ``SourceAdapter`` gathers evidence (internal chorus signals + a governed web/market adapter), a Scout
beat + the reused chorus ``analyst`` distill it into a :class:`DirectionBrief`, and the
:class:`Reconciler` turns that into *proposed* decisions. This path is **proposal-only** — a human
confirms before anything reaches the live tree.

Slices C-0 (shapes + :class:`ProposalStore`) and C-4 (:class:`Reconciler`) have landed; the scout and
analyst beats (C-2/C-3) and the approval gate follow.
"""

from __future__ import annotations

from horizon.generation._approvals import Approvals, PromoteFn
from horizon.generation._brief import Analyst, CandidateGoal, DirectionBrief, passes_evidence_gate
from horizon.generation._evidence import EvidencePacket, evidence_id
from horizon.generation._gate import GovernanceGate
from horizon.generation._proposal import Proposal, ProposalStore, proposal_id
from horizon.generation._reconciler import Reconciler
from horizon.generation._scout import CandidateOpportunity, Scout
from horizon.generation._sources import (
    EvidenceBus,
    Fetcher,
    InternalSource,
    SeedSource,
    SourceAdapter,
    WebMarketSource,
)

__all__ = [
    "Analyst",
    "Approvals",
    "CandidateGoal",
    "CandidateOpportunity",
    "DirectionBrief",
    "EvidenceBus",
    "EvidencePacket",
    "Fetcher",
    "GovernanceGate",
    "InternalSource",
    "PromoteFn",
    "Proposal",
    "ProposalStore",
    "Reconciler",
    "Scout",
    "SeedSource",
    "SourceAdapter",
    "WebMarketSource",
    "evidence_id",
    "passes_evidence_gate",
    "proposal_id",
]
