"""Source adapters + the evidence bus — the mouth of the generation funnel (C-1).

A ``SourceAdapter`` normalizes a raw signal (a landed chorus outcome, a human note, a market datapoint)
into an :class:`EvidencePacket` carrying provenance / freshness / reliability. Three built-ins ship:

- :class:`InternalSource` — reads the chorus event stream through the existing ``OutcomeFeed`` (no egress).
- :class:`SeedSource` — human-dropped notes/URLs (no egress).
- :class:`WebMarketSource` — external egress, **only** through a :class:`GovernanceGate` + an injected
  fetcher (so it is real when wired to a real HTTP client, and network-free in tests).

The :class:`EvidenceBus` collects packets from many adapters and dedups them by stable id, so the scout
downstream reasons over a clean, attributable set — never the same signal twice.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from horizon.generation._evidence import EvidencePacket, evidence_id
from horizon.generation._gate import GovernanceGate
from horizon.ports import OutcomeEvent, OutcomeFeed


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@runtime_checkable
class SourceAdapter(Protocol):
    """A named producer of evidence — poll it for the packets it has seen since a cursor."""

    name: str

    def poll(self, *, since: str | None = None) -> list[EvidencePacket]: ...


class InternalSource:
    """Reads landed chorus outcomes via the existing ``OutcomeFeed`` — the org's own signal (no egress)."""

    name = "chorus.internal"

    def __init__(self, outcomes: OutcomeFeed, *, now: Callable[[], str] = _now_iso) -> None:
        self._outcomes = outcomes
        self._now = now

    def poll(self, *, since: str | None = None) -> list[EvidencePacket]:
        return [self._to_packet(event) for event in self._outcomes.replay(after=since)]

    def _to_packet(self, event: OutcomeEvent) -> EvidencePacket:
        parts = [event.kind]
        if event.task_id:
            parts.append(f"task={event.task_id}")
        if event.goal_id:
            parts.append(f"goal={event.goal_id}")
        if event.status:
            parts.append(f"status={event.status}")
        if event.passed is not None:
            parts.append(f"passed={event.passed}")
        body = " ".join(parts)
        if event.detail:
            body += f" — {event.detail}"
        return EvidencePacket(
            id=evidence_id(self.name, body),
            source=self.name,
            kind="signal",
            body=body,
            provenance=event.task_id or event.goal_id or "chorus",
            reliability=1.0,  # the org's own ledger — fully trusted
            captured_at=self._now(),
        )


class SeedSource:
    """Human-dropped evidence (notes / URLs) — deterministic, no egress."""

    name = "seed"

    def __init__(self, *, now: Callable[[], str] = _now_iso) -> None:
        self._seeds: list[EvidencePacket] = []
        self._now = now

    def add(
        self,
        body: str,
        *,
        kind: str = "note",
        provenance: str = "",
        reliability: float = 1.0,
    ) -> EvidencePacket:
        """Record a human-provided signal; returns the packet it becomes."""
        packet = EvidencePacket(
            id=evidence_id(self.name, body),
            source=self.name,
            kind=kind,
            body=body.strip(),
            provenance=provenance,
            reliability=reliability,
            captured_at=self._now(),
        )
        self._seeds.append(packet)
        return packet

    def poll(self, *, since: str | None = None) -> list[EvidencePacket]:
        return list(self._seeds)


Fetcher = Callable[[str], str]
"""Fetch a URL's text body. Injected so the source is real with a real HTTP client, faked in tests."""


class WebMarketSource:
    """External market/web evidence — every fetch passes through the :class:`GovernanceGate` first."""

    name = "web.market"

    def __init__(
        self,
        *,
        gate: GovernanceGate,
        fetch: Fetcher,
        urls: Sequence[str],
        credential: str | None = None,
        now: Callable[[], str] = _now_iso,
    ) -> None:
        self._gate = gate
        self._fetch = fetch
        self._urls = list(urls)
        self._credential = credential
        self._now = now

    def poll(self, *, since: str | None = None) -> list[EvidencePacket]:
        packets: list[EvidencePacket] = []
        for url in self._urls:
            self._gate.authorize(url, credential=self._credential)  # allow-list + creds, pre-fetch
            body = self._fetch(url)
            self._gate.guard_size(len(body.encode("utf-8")))  # size cap, post-fetch
            packets.append(
                EvidencePacket(
                    id=evidence_id(self.name, url),  # id by url so re-polling one url dedups
                    source=self.name,
                    kind="market",
                    body=body.strip(),
                    provenance=url,
                    reliability=0.6,  # external — trusted less than the org's own ledger
                    captured_at=self._now(),
                )
            )
        return packets


class EvidenceBus:
    """Collects packets from many adapters, deduped by stable id — the scout's clean input set."""

    def __init__(self) -> None:
        self._packets: dict[str, EvidencePacket] = {}

    def collect(
        self, adapters: Sequence[SourceAdapter], *, since: str | None = None
    ) -> list[EvidencePacket]:
        """Poll every adapter; return only the packets not seen before (deduped by id)."""
        fresh: list[EvidencePacket] = []
        for adapter in adapters:
            for packet in adapter.poll(since=since):
                if packet.id not in self._packets:
                    self._packets[packet.id] = packet
                    fresh.append(packet)
        return fresh

    def all(self) -> list[EvidencePacket]:
        return list(self._packets.values())
