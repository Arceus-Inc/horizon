"""``validate_roadmap`` — the ledger's deterministic, LLM-free accept-path guard (defense in depth).

Given the goal specs a CEO's ``roadmap_propose`` tool has already reasoned + catalog-checked, this
enforces the **structural** invariants the ledger must never persist a roadmap without:

- a non-empty ``title``;
- a measurable ``metric`` and a ``target`` present;
- a ``score`` that is a real number in ``[0, 1]``;
- when the optional ``depends_on`` is used, every reference resolves to a sibling ``key`` and the
  dependency graph is acyclic (flat v1 roadmaps carry no keys/deps and pass untouched);
- no goal that duplicates already-completed work (title-equal, case/space-insensitive).

Profession/catalog checks are intentionally NOT here — they need chorus's role registry and stay in the
chorus tool. This module is pure (no I/O, no LLM), so it is trivially unit-testable and shared by the
facade's :meth:`Horizon.propose_roadmap`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def _norm(title: str) -> str:
    """Case- and whitespace-insensitive title key for dup-of-done comparison."""
    return " ".join(title.split()).casefold()


def validate_roadmap(
    specs: Sequence[Mapping[str, Any]],
    *,
    done_titles: Iterable[str] = (),
) -> list[Mapping[str, Any]]:
    """Validate the roadmap's structural invariants; raise ``RoadmapError`` on the first breach.

    Returns the specs (as a list) unchanged when every invariant holds. Validation is complete *before*
    the caller persists anything, so a rejected roadmap leaves no partial writes.
    """
    from horizon.errors import RoadmapError

    specs = list(specs)
    if not specs:
        raise RoadmapError("a roadmap needs at least one goal spec")

    done = {_norm(title) for title in done_titles if title}
    keys = {spec["key"]: i for i, spec in enumerate(specs) if spec.get("key") is not None}

    for spec in specs:
        title = spec.get("title")
        if not isinstance(title, str) or not title.strip():
            raise RoadmapError(f"goal title must be a non-empty string, got {title!r}")
        metric = spec.get("metric")
        if not isinstance(metric, str) or not metric.strip():
            raise RoadmapError(f"goal {title!r} needs a measurable metric")
        target = spec.get("target")
        if not isinstance(target, str) or not target.strip():
            raise RoadmapError(f"goal {title!r} needs a target")
        score = spec.get("score")
        # bool is a subclass of int — reject it explicitly; require a real number in [0, 1].
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0:
            raise RoadmapError(f"goal {title!r} score must be a number in [0, 1], got {score!r}")
        if _norm(title) in done:
            raise RoadmapError(f"goal {title!r} duplicates already-completed work")
        for dep in spec.get("depends_on") or ():
            if dep not in keys:
                raise RoadmapError(f"goal {title!r} depends on unknown goal {dep!r}")

    _ensure_acyclic(specs, keys)
    return specs


def _ensure_acyclic(specs: Sequence[Mapping[str, Any]], keys: Mapping[str, int]) -> None:
    """Raise ``RoadmapError`` if the ``depends_on`` edges over keyed specs contain a cycle."""
    from horizon.errors import RoadmapError

    adjacency: dict[str, list[str]] = {key: [] for key in keys}
    for spec in specs:
        key = spec.get("key")
        if key is None:
            continue
        adjacency[key].extend(spec.get("depends_on") or ())  # deps proven to be known keys already

    white, gray, black = 0, 1, 2
    color = dict.fromkeys(keys, white)

    def visit(node: str) -> None:
        color[node] = gray
        for nxt in adjacency[node]:
            if color[nxt] == gray:
                raise RoadmapError("roadmap dependencies contain a cycle")
            if color[nxt] == white:
                visit(nxt)
        color[node] = black

    for key in keys:
        if color[key] == white:
            visit(key)
