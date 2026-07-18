"""Theme C, slice C-1: source adapters + the governance gate + the evidence bus.

Deterministic + network-free — the web adapter's fetch is injected, so egress policy is proven without
touching the network. Covers the internal (chorus outcomes), seed (human), and web/market sources, the
allow-list/credential/size gate, and the dedup bus.
"""

from __future__ import annotations

import pytest

from horizon.errors import EgressBlocked
from horizon.generation import (
    EvidenceBus,
    GovernanceGate,
    InternalSource,
    SeedSource,
    SourceAdapter,
    WebMarketSource,
    evidence_id,
)
from horizon.ports import OutcomeEvent
from tests.fakes import FakeOutcomeFeed

_NOW = "2026-07-10T00:00:00+00:00"


# --- evidence_id + SeedSource -------------------------------------------------


def test_evidence_id_is_stable_and_normalizes_body():
    a = evidence_id("seed", "Region A is underinvested")
    assert a == evidence_id("seed", "  region A   is UNDERINVESTED ")
    assert a.startswith("ev_")
    assert a != evidence_id("web.market", "Region A is underinvested")  # source-scoped


def test_seed_source_records_and_polls():
    seed = SeedSource(now=lambda: _NOW)
    p = seed.add("Region A margins are climbing", provenance="cofounder", reliability=0.9)
    assert p.source == "seed"
    assert p.provenance == "cofounder"
    assert p.reliability == 0.9
    assert p.captured_at == _NOW
    assert seed.poll() == [p]


# --- InternalSource (reads the chorus OutcomeFeed) ----------------------------


def test_internal_source_converts_outcomes_to_packets():
    feed = FakeOutcomeFeed()
    feed.emit(
        OutcomeEvent(kind="run.evaluated", task_id="t1", goal_id="g1", passed=True, detail="clean")
    )
    feed.emit(
        OutcomeEvent(
            kind="run.evaluated", task_id="t2", goal_id="g2", passed=False, detail="regressed"
        )
    )
    src = InternalSource(feed, now=lambda: _NOW)

    packets = src.poll()

    assert len(packets) == 2
    assert all(p.source == "chorus.internal" and p.kind == "signal" for p in packets)
    assert all(p.reliability == 1.0 for p in packets)
    first = packets[0]
    assert "goal=g1" in first.body and "passed=True" in first.body and "clean" in first.body
    assert first.provenance == "t1"


def test_internal_and_seed_satisfy_the_source_adapter_protocol():
    assert isinstance(InternalSource(FakeOutcomeFeed()), SourceAdapter)
    assert isinstance(SeedSource(), SourceAdapter)


# --- GovernanceGate -----------------------------------------------------------


def test_gate_allows_listed_host_with_credential():
    gate = GovernanceGate(allowed_hosts=["example.com"])
    gate.authorize(
        "https://data.example.com/report", credential="key"
    )  # subdomain allowed, no raise


def test_gate_blocks_unlisted_host():
    gate = GovernanceGate(allowed_hosts=["example.com"])
    with pytest.raises(EgressBlocked):
        gate.authorize("https://evil.test/x", credential="key")


def test_gate_blocks_missing_credential_when_required():
    gate = GovernanceGate(allowed_hosts=["example.com"])
    with pytest.raises(EgressBlocked):
        gate.authorize("https://example.com/x")  # no credential


def test_gate_allows_missing_credential_when_not_required():
    gate = GovernanceGate(allowed_hosts=["example.com"], require_credential=False)
    gate.authorize("https://example.com/x")  # no raise


def test_gate_guards_size():
    gate = GovernanceGate(allowed_hosts=["example.com"], max_bytes=10)
    gate.guard_size(10)  # boundary ok
    with pytest.raises(EgressBlocked):
        gate.guard_size(11)


# --- WebMarketSource (gated, injected fetch) ----------------------------------


def test_web_source_fetches_through_the_gate():
    gate = GovernanceGate(allowed_hosts=["example.com"])
    src = WebMarketSource(
        gate=gate,
        fetch=lambda url: "Market grew 12% QoQ",
        urls=["https://example.com/market"],
        credential="key",
        now=lambda: _NOW,
    )
    packets = src.poll()
    assert len(packets) == 1
    p = packets[0]
    assert p.source == "web.market" and p.kind == "market"
    assert p.body == "Market grew 12% QoQ"
    assert p.provenance == "https://example.com/market"
    assert p.reliability == 0.6


def test_web_source_blocks_disallowed_host_before_fetching():
    gate = GovernanceGate(allowed_hosts=["example.com"])
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return "x"

    src = WebMarketSource(gate=gate, fetch=fetch, urls=["https://evil.test/x"], credential="key")
    with pytest.raises(EgressBlocked):
        src.poll()
    assert fetched == []  # never fetched — blocked pre-egress


def test_web_source_blocks_oversize_response():
    gate = GovernanceGate(allowed_hosts=["example.com"], max_bytes=5)
    src = WebMarketSource(
        gate=gate,
        fetch=lambda url: "way too long",
        urls=["https://example.com/x"],
        credential="key",
    )
    with pytest.raises(EgressBlocked):
        src.poll()


# --- EvidenceBus (dedup across adapters + polls) ------------------------------


def test_bus_collects_and_dedups_across_polls():
    seed = SeedSource(now=lambda: _NOW)
    seed.add("Region A is underinvested")
    bus = EvidenceBus()

    first = bus.collect([seed])
    assert len(first) == 1

    seed.add("  region A   is UNDERINVESTED ")  # normalized-equal -> same id
    seed.add("A brand-new signal")
    second = bus.collect([seed])

    assert {p.body for p in second} == {"A brand-new signal"}  # only the genuinely new one
    assert len(bus.all()) == 2
