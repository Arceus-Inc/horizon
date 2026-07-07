"""horizon's own domain types (``Decision`` / ``Goal`` / ``StrategyRecord``) — distinct from the seam DTOs.

These are horizon-native. The seam DTO :class:`dream.contracts.GoalNode` is the lean shape chorus sees;
:class:`Goal` here is horizon's rich internal view (skeleton + strategy fields + decision link).
"""

from __future__ import annotations

from horizon.model._decision import Decision
from horizon.model._goal import Goal
from horizon.model._strategy import StrategyRecord

__all__ = ["Decision", "Goal", "StrategyRecord"]
