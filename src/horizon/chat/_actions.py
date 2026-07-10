"""Confirm-to-write actions — the CEO proposes, a human applies (D3).

A directive from the CEO never mutates the company directly. Instead a write tool *prepares* a
:class:`PendingAction` — a typed operation with a human-readable preview + the evidence behind it — and
the chat returns it unapplied. Only :meth:`ActionExecutor.apply` (called on an explicit human confirm)
routes it through horizon's already-gated facade methods and records it to memory. This is the same
proposal-only invariant the generation funnel enforces, extended to conversational control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from horizon._ids import mint_id
from horizon.chat._memory import CeoMemory
from horizon.errors import HorizonError
from horizon.facade import Horizon
from horizon.model import Decision

_WRITE_KINDS = frozenset(
    {"approve_proposal", "reject_proposal", "set_priority", "archive_goal",
     "record_directive", "draft_decision"}
)


@dataclass
class PendingAction:
    """A proposed write awaiting human confirmation — previewed, never auto-applied."""

    id: str
    kind: str
    args: dict[str, Any]
    preview: str
    evidence: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | applied | discarded
    result: str = ""


class ActionExecutor:
    """Apply a confirmed :class:`PendingAction` through horizon's gated writes; log it to memory."""

    def __init__(self, horizon: Horizon, *, memory: CeoMemory | None = None) -> None:
        self._horizon = horizon
        self._memory = memory

    def apply(self, action: PendingAction, *, by: str) -> str:
        """Execute a pending action (the human confirm). Returns a result string; marks it applied."""
        if action.status != "pending":
            raise HorizonError(f"action {action.id} is '{action.status}', not 'pending'")
        result = self._dispatch(action, by=by)
        action.status = "applied"
        action.result = result
        return result

    def discard(self, action: PendingAction) -> None:
        """Reject a pending action without applying it."""
        if action.status == "pending":
            action.status = "discarded"

    def _dispatch(self, action: PendingAction, *, by: str) -> str:
        a = action.args
        kind = action.kind
        if kind == "approve_proposal":
            did = self._horizon.approve_proposal(str(a["proposal_id"]), by=by)
            self._log("decision-log", f"{by} approved proposal {a['proposal_id']} -> decision {did}", 0.8)
            return f"Approved — seeded live decision {did}."
        if kind == "reject_proposal":
            self._horizon.reject_proposal(str(a["proposal_id"]), by=by, reason=str(a.get("reason", "")))
            self._log("decision-log", f"{by} rejected proposal {a['proposal_id']}: {a.get('reason','')}", 0.5)
            return f"Rejected proposal {a['proposal_id']}."
        if kind == "set_priority":
            p = self._horizon.set_priority(str(a["goal_id"]), str(a["priority"]))
            self._log("decision-log", f"{by} set goal {a['goal_id']} priority -> {p}", 0.5)
            return f"Set goal {a['goal_id']} priority to {p}."
        if kind == "archive_goal":
            self._horizon.archive_goal(str(a["goal_id"]))
            self._log("decision-log", f"{by} archived goal {a['goal_id']}", 0.5)
            return f"Archived goal {a['goal_id']}."
        if kind == "record_directive":
            text = str(a["text"]).strip()
            if self._memory is not None:
                self._memory.write("directives", text, importance=0.9, tags=[by])
            return f"Recorded standing directive: {text}"
        if kind == "draft_decision":
            decision = Decision(
                id=mint_id("dec"),
                statement=str(a["statement"]).strip(),
                status="active",
                owner=None,
                rationale=str(a.get("rationale", "")).strip(),
            )
            self._horizon.seed_decision(decision)
            self._log("decision-log", f"{by} seeded decision {decision.id}: {decision.statement}", 0.8)
            return f"Seeded live decision {decision.id}."
        raise HorizonError(f"unknown action kind {kind!r}; expected one of {sorted(_WRITE_KINDS)}")

    def _log(self, layer: str, text: str, importance: float) -> None:
        if self._memory is not None:
            self._memory.write(layer, text, importance=importance)
