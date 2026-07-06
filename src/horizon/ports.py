"""horizon's port surface — the ``dream.contracts`` Protocols the strategy layer binds to.

horizon never imports chorus. It speaks only these Protocols; a consumer's composition root (see
``examples/chorus_bridge.py``) supplies adapters that wrap chorus's concrete classes to satisfy them.
Re-exported here so horizon code + tests import the seam from one place (``horizon.ports``).
"""

from __future__ import annotations

from dream.contracts import (
    GoalNode,
    GoalStore,
    IntakePort,
    OutcomeEvent,
    OutcomeFeed,
    Priority,
)

__all__ = [
    "GoalNode",
    "GoalStore",
    "IntakePort",
    "OutcomeEvent",
    "OutcomeFeed",
    "Priority",
]
