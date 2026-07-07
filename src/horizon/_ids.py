"""Id minting for horizon-native entities (decisions, goals) — prefix + short uuid, like chorus's ids."""

from __future__ import annotations

from uuid import uuid4


def mint_id(prefix: str) -> str:
    """Return a collision-resistant id like ``goal_9f3c1a2b4d5e`` (prefix + 12 hex chars)."""
    return f"{prefix}_{uuid4().hex[:12]}"
