"""generation — evidence -> **DirectionBrief** (the department flow that *proposes* decisions/goals).

*"PM aur analyst research karega -> input PM ko -> horizon feedback lega -> engineering ke goals banaye."*
A ``SourceAdapter`` gathers evidence (internal chorus signals + a governed web/market adapter), a Scout
beat + the reused chorus ``analyst`` employee distill it into a ``DirectionBrief``, and a ``Reconciler``
turns that into *proposed* goals/decisions. In v1 this path is **proposal-only** — a human confirms.

Lands in M4. Scaffolded now per the agreed structure.
"""

from __future__ import annotations

__all__: list[str] = []
