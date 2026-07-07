"""The Prioritiser — map a goal's numeric ``score`` to chorus's coarse ``Priority`` and apply it.

The single knob: horizon keeps a rich ``score`` in ``[0,1]``; chorus orders by a coarse
``critical|high|medium|low``. ``ScorePolicy`` is the (configurable) mapping; ``Prioritiser.apply``
writes it through ``IntakePort.set_priority`` — a pure data write, never a scheduler call. ``critical``
is reserved for a human/explicit override, so the score ladder only ever emits high/medium/low.
"""

from __future__ import annotations

from dataclasses import dataclass

from horizon.ports import IntakePort, Priority


@dataclass(frozen=True)
class ScorePolicy:
    """Thresholds mapping a ``[0,1]`` score to a coarse ``Priority`` (configurable)."""

    high: float = 0.75
    medium: float = 0.40

    def priority_for(self, score: float) -> Priority:
        if score >= self.high:
            return "high"
        if score >= self.medium:
            return "medium"
        return "low"


class Prioritiser:
    """Apply a goal's score to its task's priority via the intake port."""

    def __init__(self, intake: IntakePort, *, policy: ScorePolicy | None = None) -> None:
        self._intake = intake
        self._policy = policy or ScorePolicy()

    def priority_for(self, score: float) -> Priority:
        return self._policy.priority_for(score)

    def apply(self, task_id: str, score: float) -> Priority:
        """Set the task's priority from ``score`` and return the priority chosen."""
        priority = self._policy.priority_for(score)
        self._intake.set_priority(task_id, priority)
        return priority
