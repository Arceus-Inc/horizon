"""``EvidencePacket`` — the typed unit the generation funnel reads (C1).

A source adapter normalizes a raw signal (a chorus ledger event, a human note, a market datapoint) into
an ``EvidencePacket`` carrying **provenance**, **freshness**, and **reliability** so the scout + analyst
downstream reason over evidence, not raw prose. The adapters that produce these land in C1; this is just
the shape they emit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from horizon.intake._fingerprint import normalize_intent


def evidence_id(source: str, body: str) -> str:
    """A stable, content-scoped id so the same signal from the same source dedups across polls."""
    digest = hashlib.sha256(f"{source}:{normalize_intent(body)}".encode()).hexdigest()[:12]
    return f"ev_{digest}"


@dataclass(frozen=True)
class EvidencePacket:
    """A normalized, attributable piece of evidence the funnel reasons over."""

    id: str
    source: str  # adapter name, e.g. "chorus.ledger" | "seed" | "web.market"
    kind: str  # "signal" | "metric" | "market" | "note"
    body: str  # the normalized content the scout reads
    provenance: str = ""  # where it came from (url / task_id / person)
    freshness_s: float = 0.0  # age in seconds at capture
    reliability: float = 1.0  # 0..1 adapter-declared trust
    captured_at: str = ""
