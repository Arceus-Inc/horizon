"""``Reconciler`` — turn analyst :class:`DirectionBrief`s into *proposed* decisions (C-4).

The tail of the generation funnel, and the last **deterministic** stage (no LLM, no beats). Each brief
becomes a ``Proposal`` written to the :class:`ProposalStore` — **never** to chorus or the live
``DecisionStore``. Only a human ``approve`` (the C-gate slice) promotes a proposal into the live tree.

Dedup is two-sided so the same opportunity is never proposed twice: a brief is skipped when its
recommendation already exists as an **open proposal** (same ``proposal_id``) or already matches a
**live decision** (normalized-equal statement). Returns only the newly-created proposals.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from horizon.generation._brief import DirectionBrief
from horizon.generation._proposal import Proposal, ProposalStore, proposal_id
from horizon.intake._fingerprint import normalize_intent
from horizon.store._decision_store import DecisionStore


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Reconciler:
    """Fold analyst briefs into deduped, proposal-only decision records."""

    def __init__(
        self,
        *,
        proposals: ProposalStore,
        decisions: DecisionStore | None = None,
        now: Callable[[], str] = _now_iso,
    ) -> None:
        self._proposals = proposals
        self._decisions = decisions
        self._now = now

    def reconcile(self, briefs: list[DirectionBrief]) -> list[Proposal]:
        """Create a proposal per new recommendation; skip blanks, dups, and live decisions."""
        live = self._live_statements()
        seen: set[str] = {p.id for p in self._proposals.all()}
        created: list[Proposal] = []
        for brief in briefs:
            statement = brief.recommendation.strip()
            if not statement:
                continue
            if normalize_intent(statement) in live:
                continue
            pid = proposal_id(statement)
            if pid in seen:
                continue
            proposal = Proposal(
                id=pid,
                status="proposed",
                brief=brief,
                decision_statement=statement,
                decision_rationale=brief.rationale,
                created_at=self._now(),
            )
            self._proposals.put(proposal)
            seen.add(pid)
            created.append(proposal)
        return created

    def _live_statements(self) -> set[str]:
        if self._decisions is None:
            return set()
        return {normalize_intent(d.statement) for d in self._decisions.all()}
