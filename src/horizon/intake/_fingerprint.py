"""Idempotency fingerprint for horizon intake — ``goal_id`` scoped + a normalized-intent hash.

Two submissions are "the same opportunity" iff they share a goal and a semantically-equal intent, so
re-deriving a goal (same title, different whitespace/case) dedups to one task. chorus's intake is
idempotent on ``(origin_kind=horizon_intake, origin_fingerprint)``; this computes that fingerprint.
"""

from __future__ import annotations

import hashlib
import re

_WHITESPACE = re.compile(r"\s+")


def normalize_intent(intent: str) -> str:
    """Lowercase + collapse all whitespace runs to single spaces + strip (semantic equality key)."""
    return _WHITESPACE.sub(" ", intent.strip().lower())


def fingerprint(goal_id: str, intent: str) -> str:
    """Return ``<goal_id>:<sha256(normalized intent)[:16]>`` — the idempotent-intake key."""
    digest = hashlib.sha256(normalize_intent(intent).encode("utf-8")).hexdigest()[:16]
    return f"{goal_id}:{digest}"
