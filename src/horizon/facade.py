"""``Horizon`` — the strategy layer's public entry point (the composition root binds ports into it).

horizon binds **only** to the ``dream.contracts`` strategy seam (``IntakePort`` / ``GoalStore`` /
``OutcomeFeed``) — never to chorus. A consumer wires chorus's concretes into those ports (see
``examples/chorus_bridge.py``) and hands them here, along with horizon's own stores. v1 wires the
stores; the planning / intake / feedback engines attach their behavior in M2.
"""

from __future__ import annotations

from horizon.ports import GoalStore, IntakePort, OutcomeFeed
from horizon.store import DecisionStore, StrategyStore


class Horizon:
    """The strategy layer, composed over the ports (execution seam) + horizon's own stores (strategy)."""

    def __init__(
        self,
        *,
        goals: GoalStore,
        intake: IntakePort,
        outcomes: OutcomeFeed,
        decisions: DecisionStore | None = None,
        strategy: StrategyStore | None = None,
    ) -> None:
        self._goals = goals
        self._intake = intake
        self._outcomes = outcomes
        self._decisions = decisions or DecisionStore()
        self._strategy = strategy or StrategyStore()
