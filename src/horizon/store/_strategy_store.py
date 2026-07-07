"""``StrategyStore`` — JSON-backed map ``goal_id -> StrategyRecord`` under ``.horizon/strategy.json``.

horizon-owned rich fields (score / health / metric / target / evidence). A reader overlays these on
chorus's lean goal skeleton (read through the ``GoalStore`` port) to assemble a full :class:`Goal`.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from horizon.model._strategy import StrategyRecord
from horizon.store._jsonfile import read_json, write_json


class StrategyStore:
    """A tiny JSON-backed map ``goal_id -> StrategyRecord``."""

    def __init__(self, path: str | Path = ".horizon/strategy.json") -> None:
        self._path = Path(path)

    def get(self, goal_id: str) -> StrategyRecord | None:
        raw = read_json(self._path).get(goal_id)
        return StrategyRecord(**raw) if raw is not None else None

    def put(self, record: StrategyRecord) -> StrategyRecord:
        data = read_json(self._path)
        data[record.goal_id] = asdict(record)
        write_json(self._path, data)
        return record

    def all(self) -> list[StrategyRecord]:
        return [StrategyRecord(**raw) for raw in read_json(self._path).values()]
