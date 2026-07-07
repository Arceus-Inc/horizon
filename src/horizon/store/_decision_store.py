"""``DecisionStore`` — JSON-backed map ``decision_id -> Decision`` under ``.horizon/decisions.json``.

Decisions are horizon-native (chorus never sees them). This holds the decision records + their
decision -> goal decomposition edges (``Decision.goal_ids``). The top of the Decision -> Goal -> Task
spine lives here and nowhere else.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from horizon.model._decision import Decision
from horizon.store._jsonfile import read_json, write_json


class DecisionStore:
    """A tiny JSON-backed map ``decision_id -> Decision``."""

    def __init__(self, path: str | Path = ".horizon/decisions.json") -> None:
        self._path = Path(path)

    def get(self, decision_id: str) -> Decision | None:
        raw = read_json(self._path).get(decision_id)
        return Decision(**raw) if raw is not None else None

    def put(self, decision: Decision) -> Decision:
        data = read_json(self._path)
        data[decision.id] = asdict(decision)
        write_json(self._path, data)
        return decision

    def all(self) -> list[Decision]:
        return [Decision(**raw) for raw in read_json(self._path).values()]
