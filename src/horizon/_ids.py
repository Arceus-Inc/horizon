"""Id minting for horizon-native entities (decisions, goals) — prefix + short uuid, like chorus's ids."""

from __future__ import annotations

from uuid import uuid4


def mint_id(prefix: str) -> str:
    """Return a collision-resistant id like ``goal_9f3c1a2b4d5e`` (prefix + 12 hex chars)."""
    return f"{prefix}_{uuid4().hex[:12]}"


def mint_uuid() -> str:
    """Return a fresh **canonical uuid text** id (e.g. ``"9f3c1a2b-…-b3d4"``).

    Used for entities that cross the strategy seam into chorus's Postgres ledger, whose id columns are
    native ``uuid`` (spec 12 §6): a prefixed/truncated ``mint_id`` value is unparseable as a uuid and is
    rejected by the column at insert time. The kind is named by the column, so the id needs no prefix.
    """
    return str(uuid4())
