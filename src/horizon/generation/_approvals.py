"""``Approvals`` — the minimal confirm-to-write gate (C-gate): the ONLY path proposal -> live tree.

Theme C is proposal-only, so a human must approve before anything reaches the live tree. This is the
smallest surface that unblocks the funnel; Theme D's CEO chat later replaces the CLI but reuses these
methods. The gate owns the **status transitions + audit trail**; the actual promotion (seed a decision +
decompose + submit) is an injected ``PromoteFn`` so the gate stays deterministic and unit-testable — and
so promotion always flows through horizon's *existing* entry points, never a second door.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from horizon.errors import ProposalNotOpen, UnknownProposal
from horizon.generation._proposal import Proposal, ProposalStore

PromoteFn = Callable[[Proposal], str]
"""Promote an approved proposal into the live tree; returns the created (live) decision id."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Approvals:
    """List, preview, approve, or reject proposals — the human gate at the funnel's mouth."""

    def __init__(
        self,
        *,
        proposals: ProposalStore,
        promote: PromoteFn,
        now: Callable[[], str] = _now_iso,
    ) -> None:
        self._proposals = proposals
        self._promote = promote
        self._now = now

    def list_proposals(self, *, status: str | None = "proposed") -> list[Proposal]:
        """All proposals, optionally filtered by status (default: the open 'proposed' ones)."""
        return [p for p in self._proposals.all() if status is None or p.status == status]

    def explain(self, proposal_id: str) -> str:
        """An auditable preview of what approving would create — reads only, never writes."""
        p = self._require(proposal_id)
        lines = [
            f"Proposal {p.id} [{p.status}]",
            f"Decision: {p.decision_statement}",
            f"Rationale: {p.decision_rationale}",
        ]
        if p.brief is not None:
            lines.append(f"Confidence: {p.brief.confidence:.2f}")
            if p.brief.risks:
                lines.append("Risks: " + "; ".join(p.brief.risks))
            for g in p.brief.candidate_goals:
                lines.append(f"  - goal: {g.title} ({g.metric} -> {g.target})")
            if p.brief.evidence_refs:
                lines.append("Evidence: " + ", ".join(p.brief.evidence_refs))
        return "\n".join(lines)

    def approve(self, proposal_id: str, *, by: str) -> str:
        """Promote a proposed proposal into the live tree; returns the created decision id."""
        p = self._require(proposal_id)
        self._ensure_open(p)
        decision_id = self._promote(p)
        p.status = "approved"
        p.decided_by = by
        p.decided_at = self._now()
        p.linked_decision_id = decision_id
        self._proposals.put(p)
        return decision_id

    def reject(self, proposal_id: str, *, by: str, reason: str = "") -> None:
        """Close a proposal without promoting it — records who / when / why."""
        p = self._require(proposal_id)
        self._ensure_open(p)
        p.status = "rejected"
        p.decided_by = by
        p.decided_at = self._now()
        p.note = reason
        self._proposals.put(p)

    def _require(self, proposal_id: str) -> Proposal:
        p = self._proposals.get(proposal_id)
        if p is None:
            raise UnknownProposal(proposal_id)
        return p

    @staticmethod
    def _ensure_open(p: Proposal) -> None:
        if p.status != "proposed":
            raise ProposalNotOpen(f"{p.id} is '{p.status}', not 'proposed'")
