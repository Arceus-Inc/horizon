"""chat — the **CEO chat** control surface (read + propose; every write is confirm-to-apply).

The human write path for decisions (v1's only decision author). It reads + explains the Decision -> Goal
-> Task tree and *drafts* a decision or a submit intent; nothing is applied without explicit user
confirmation (no auto-writes). Bounded, typed, auditable-diff writes only.

Lands in M5. Scaffolded now per the agreed structure.
"""

from __future__ import annotations

__all__: list[str] = []
