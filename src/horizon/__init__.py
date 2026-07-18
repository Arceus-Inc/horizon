"""horizon — the strategy SDK that decides the sprint.

horizon owns the **Decision -> Goal -> Task** spine's top two altitudes: it holds decisions
(horizon-native), decomposes them into goals, turns leaf goals into chorus intake, and closes the
outcome -> health -> re-priority loop. It binds ONLY to ``dream.contracts`` ports (``IntakePort`` /
``GoalStore`` / ``OutcomeFeed``); a consumer's composition root wires chorus's concrete classes into
those ports. horizon never imports chorus and never runs the schedule.

Public surface is grown milestone by milestone (see ``docs/v1-plan.md``); it is pinned by
``tests/test_public_api.py``.
"""

from __future__ import annotations

from horizon.facade import Horizon
from horizon.feedback import HealthPolicy
from horizon.intake import ScorePolicy
from horizon.model import Decision, DecisionState, Goal, StrategyRecord
from horizon.reporting import render_direction
from horizon.store import DecisionStore, StrategyStore

__version__ = "0.1.0"

__all__ = [
    "Decision",
    "DecisionState",
    "DecisionStore",
    "Goal",
    "HealthPolicy",
    "Horizon",
    "ScorePolicy",
    "StrategyRecord",
    "StrategyStore",
    "__version__",
    "render_direction",
]
