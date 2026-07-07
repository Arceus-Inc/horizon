"""Tiny atomic JSON-file helpers shared by horizon's stores (v1 persistence — sqlite can come later)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from ``path``, or an empty dict if it does not exist."""
    if not path.exists():
        return {}
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write ``data`` to ``path`` (write-temp-then-replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
