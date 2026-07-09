"""``Proposal`` + ``ProposalStore`` — the funnel's proposal-only output, horizon-native (C-0).

The Reconciler (C4) writes ``Proposal`` records here — **never** to chorus or the live ``DecisionStore``.
Only a human ``approve`` promotes a proposal into the live tree (the C-gate slice). The store is a tiny
JSON map like ``DecisionStore``; because a ``Proposal`` nests a :class:`DirectionBrief`, it (de)serializes
the nested shapes explicitly.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from horizon.generation._brief import DirectionBrief
from horizon.intake._fingerprint import normalize_intent
from horizon.store._jsonfile import read_json, write_json


@dataclass
class Proposal:
    """A proposed decision (+ its brief) awaiting human approval — the only path to the live tree."""

    id: str
    status: str = "proposed"  # proposed | approved | rejected | superseded
    brief: DirectionBrief | None = None
    decision_statement: str = ""  # what seed_decision would receive
    decision_rationale: str = ""
    created_at: str = ""
    decided_by: str | None = None  # who approved/rejected
    decided_at: str | None = None
    linked_decision_id: str | None = None  # set once approved + seeded
    note: str = ""  # a reject reason / approval note (audit)


def proposal_id(statement: str) -> str:
    """Deterministic, statement-scoped id so the same recommendation dedups to one proposal."""
    digest = hashlib.sha256(normalize_intent(statement).encode("utf-8")).hexdigest()[:12]
    return f"prop_{digest}"


def _proposal_from_dict(raw: dict[str, Any]) -> Proposal:
    brief_raw = raw.get("brief")
    return Proposal(
        id=str(raw["id"]),
        status=str(raw.get("status", "proposed")),
        brief=DirectionBrief.from_dict(brief_raw) if brief_raw else None,
        decision_statement=str(raw.get("decision_statement", "")),
        decision_rationale=str(raw.get("decision_rationale", "")),
        created_at=str(raw.get("created_at", "")),
        decided_by=raw.get("decided_by"),
        decided_at=raw.get("decided_at"),
        linked_decision_id=raw.get("linked_decision_id"),
        note=str(raw.get("note", "")),
    )


class ProposalStore:
    """A tiny JSON-backed map ``proposal_id -> Proposal`` under ``.horizon/proposals.json``."""

    def __init__(self, path: str | Path = ".horizon/proposals.json") -> None:
        self._path = Path(path)

    def get(self, proposal_id: str) -> Proposal | None:
        raw = read_json(self._path).get(proposal_id)
        return _proposal_from_dict(raw) if raw is not None else None

    def put(self, proposal: Proposal) -> Proposal:
        data = read_json(self._path)
        data[proposal.id] = asdict(proposal)
        write_json(self._path, data)
        return proposal

    def all(self) -> list[Proposal]:
        return [_proposal_from_dict(raw) for raw in read_json(self._path).values()]
