"""feedback — close the loop: **landed outcomes** -> goal **health** -> re-priority (the back-pressure).

An ``OutcomeListener`` subscribes to the ``OutcomeFeed`` port and, on each landed DoD verdict, updates
the goal's ``health`` in the ``StrategyStore`` and re-scores it (drift = landed-DoD pass-rate + a
staleness clock). A drifting/blocked goal re-prioritizes; sustained drift bubbles up to its decision.
This is read-only w.r.t. chorus's schedule — horizon never dispatches.

Lands in M2: ``_listener.py``, ``_health.py``.
"""

from __future__ import annotations

__all__: list[str] = []
