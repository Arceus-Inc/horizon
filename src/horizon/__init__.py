"""horizon — the strategy SDK that decides the sprint.

horizon owns the OKR tree, turns leaf goals into chorus intake, and closes the
outcome -> health -> re-priority loop. It binds ONLY to ``dream.contracts`` ports
(``IntakePort`` / ``GoalStore`` / ``OutcomeFeed``); a consumer's composition root
wires chorus's concrete classes into those ports. horizon never imports chorus
and never runs the schedule.

Public surface is grown milestone by milestone (see ``docs/v1-plan.md``); it is
pinned by ``tests/test_public_api.py``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
