"""planning — turn a **Decision** into a tree of **Goals** (horizon's core job).

*"horizon ka kaam hoga: Decisions ko Goals banaye."* A ``Decomposer`` takes a horizon-native
:class:`~horizon.model.Decision` and authors the goal tree beneath it (written to chorus through the
``GoalStore`` port). Until a manager exists, a leaf goal maps 1:1 to a single task; department-aware
decomposition (PM/analyst research -> engineering goals) arrives with the generation funnel (M4).

Lands in M2: ``_decomposer.py``.
"""

from __future__ import annotations

from horizon.planning._decomposer import Decomposer
from horizon.planning._effective_priority import EffectivePriorityPolicy, EffectiveResult
from horizon.planning._reasoner import CompletionResult, Reasoner

__all__ = [
    "CompletionResult",
    "Decomposer",
    "EffectivePriorityPolicy",
    "EffectiveResult",
    "Reasoner",
]
