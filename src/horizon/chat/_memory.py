"""``CeoMemory`` — the CEO's persistent, layered memory (D2).

Four layers, each with its own decay, make the CEO feel like the same executive across sessions:

- ``conversation`` — rolling chat exchanges (fast-decaying, low importance)
- ``decision-log`` — decisions made + rationale + who approved (long-lived, the strategy audit trail)
- ``directives`` — standing instructions / preferences you've given (persistent, shapes future turns)
- ``org-facts`` — durable truths about the company (slow-changing world model)

Recall ranks by relevance (keyword overlap) x importance x recency and skips superseded entries, so the
right memory resurfaces exactly when it matters and stale ones fade. File-backed like horizon's other
stores; semantic recall can layer on later without changing this surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from horizon._ids import mint_id
from horizon.intake._fingerprint import normalize_intent
from horizon.store._jsonfile import read_json, write_json

LAYERS = ("conversation", "decision-log", "directives", "org-facts")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _tokens(text: str) -> set[str]:
    return {t for t in normalize_intent(text).split() if len(t) > 2}


@dataclass
class MemoryEntry:
    """One remembered fact, keyed by layer, with an importance and a decay flag."""

    id: str
    layer: str
    text: str
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5  # 0..1 — how much it should weigh in recall
    created_at: str = ""
    superseded: bool = False  # replaced/obsolete — kept for audit, skipped in recall


class CeoMemory:
    """A layered, JSON-backed memory the CEO writes to and recalls from."""

    def __init__(self, path: str | Path = ".horizon/ceo_memory.json", *, now: Any = _now_iso) -> None:
        self._path = Path(path)
        self._now = now

    def write(
        self, layer: str, text: str, *, tags: list[str] | None = None, importance: float = 0.5
    ) -> MemoryEntry:
        """Record a memory in one of the four layers; returns the stored entry."""
        if layer not in LAYERS:
            raise ValueError(f"unknown memory layer {layer!r}; expected one of {LAYERS}")
        entry = MemoryEntry(
            id=mint_id("mem"),
            layer=layer,
            text=text.strip(),
            tags=list(tags or []),
            importance=min(1.0, max(0.0, importance)),
            created_at=self._now(),
        )
        data = read_json(self._path)
        data[entry.id] = asdict(entry)
        write_json(self._path, data)
        return entry

    def get(self, entry_id: str) -> MemoryEntry | None:
        raw = read_json(self._path).get(entry_id)
        return MemoryEntry(**raw) if raw is not None else None

    def all(self, *, layer: str | None = None, include_superseded: bool = False) -> list[MemoryEntry]:
        out: list[MemoryEntry] = []
        for raw in read_json(self._path).values():
            entry = MemoryEntry(**raw)
            if layer is not None and entry.layer != layer:
                continue
            if entry.superseded and not include_superseded:
                continue
            out.append(entry)
        return out

    def supersede(self, entry_id: str) -> None:
        """Mark an entry obsolete — kept for audit, excluded from recall."""
        data = read_json(self._path)
        if entry_id in data:
            data[entry_id]["superseded"] = True
            write_json(self._path, data)

    def recall(
        self, query: str, *, layers: tuple[str, ...] | None = None, limit: int = 6
    ) -> list[MemoryEntry]:
        """The most relevant memories for a query - relevance x importance x recency, superseded skipped."""
        entries = [e for e in self.all() if layers is None or e.layer in layers]
        if not entries:
            return []
        by_time = sorted(entries, key=lambda e: e.created_at)
        recency = {e.id: (i + 1) / len(by_time) for i, e in enumerate(by_time)}
        q = _tokens(query)

        def score(e: MemoryEntry) -> float:
            etoks = _tokens(e.text + " " + " ".join(e.tags))
            overlap = len(q & etoks) / len(q) if q else 0.0
            return 0.6 * overlap + 0.25 * e.importance + 0.15 * recency[e.id]

        return sorted(entries, key=lambda e: (score(e), recency[e.id]), reverse=True)[:limit]


def render_memories(entries: list[MemoryEntry]) -> str:
    """A compact block of recalled memories for the CEO's prompt."""
    if not entries:
        return ""
    lines = ["RELEVANT MEMORY (from earlier — cite as memory if you use it):"]
    for e in entries:
        lines.append(f"  - [{e.layer}] {e.text}")
    return "\n".join(lines)
