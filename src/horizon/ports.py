"""horizon's port surface — external seam and direction repository Protocols.

horizon never imports chorus. It speaks only these Protocols; a consumer's composition root (see
``examples/chorus_bridge.py``) supplies adapters that wrap chorus's concrete classes to satisfy them.
Re-exported here so horizon code + tests import the seam from one place (``horizon.ports``).
Direction persistence is horizon-owned, but its callers depend on these small repository contracts so
the v1 JSON files and the planned Postgres repositories remain interchangeable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from dream.contracts import (
    CapacityPort,
    DelegatedIntakePort,
    DelegatedWorkRef,
    DelegatedWorkRequest,
    GoalNode,
    GoalStore,
    IntakePort,
    OutcomeEvent,
    OutcomeFeed,
    Priority,
    ProfessionCapacity,
    StaffingBlocked,
    StaffingRequirement,
)

from horizon.model import Decision, StrategyRecord

if TYPE_CHECKING:
    from horizon.generation import Proposal


class DecisionRepository(Protocol):
    """Persistence needed for horizon-native decisions."""

    def get(self, decision_id: str) -> Decision | None: ...

    def put(self, decision: Decision) -> Decision: ...

    def all(self) -> list[Decision]: ...


class StrategyRepository(Protocol):
    """Persistence needed for horizon's per-goal strategy records."""

    def get(self, goal_id: str) -> StrategyRecord | None: ...

    def put(self, record: StrategyRecord) -> StrategyRecord: ...

    def all(self) -> list[StrategyRecord]: ...


class ProposalRepository(Protocol):
    """Persistence needed for human-gated direction proposals."""

    def get(self, proposal_id: str) -> Proposal | None: ...

    def put(self, proposal: Proposal) -> Proposal: ...

    def all(self) -> list[Proposal]: ...

__all__ = [
    "CapacityPort",
    "DecisionRepository",
    "DelegatedIntakePort",
    "DelegatedWorkRef",
    "DelegatedWorkRequest",
    "GoalNode",
    "GoalStore",
    "IntakePort",
    "OutcomeEvent",
    "OutcomeFeed",
    "Priority",
    "ProfessionCapacity",
    "ProposalRepository",
    "StaffingBlocked",
    "StaffingRequirement",
    "StrategyRepository",
]
