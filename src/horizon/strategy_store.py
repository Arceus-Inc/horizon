"""The strategy store — horizon-owned rich fields keyed by ``goal_id`` (chorus's goal row stays lean).

chorus persists the goal *skeleton* (id / title / level / status / parent / owner). The strategy-only
fields horizon reasons over — the numeric ``score``, the ``health`` read, the ``metric`` + ``target``,
and the ``evidence`` behind them — live here, in horizon's own store, so chorus needs no schema
migration. JSON-backed for v1 (one file under ``.horizon/``); the shape is intentionally small and
forward-compatible. A reader merges this with chorus's skeleton (via the ``GoalStore`` port).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StrategyRecord:
    """The rich, strategy-only facts about one goal (merged with chorus's skeleton at read time)."""

    goal_id: str
    score: float = 0.0
    health: str = "unknown"
    metric: str | None = None
    target: str | None = None
    evidence: list[str] = field(default_factory=list)


class StrategyStore:
    """A tiny JSON-backed map ``goal_id -> StrategyRecord`` under ``.horizon/strategy.json``."""

    def __init__(self, path: str | Path = ".horizon/strategy.json") -> None:
        self._path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        loaded: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        return loaded

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def get(self, goal_id: str) -> StrategyRecord | None:
        raw = self._load().get(goal_id)
        return StrategyRecord(**raw) if raw is not None else None

    def put(self, record: StrategyRecord) -> StrategyRecord:
        data = self._load()
        data[record.goal_id] = asdict(record)
        self._save(data)
        return record

    def all(self) -> list[StrategyRecord]:
        return [StrategyRecord(**raw) for raw in self._load().values()]
