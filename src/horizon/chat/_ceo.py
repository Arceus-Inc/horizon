"""``Ceo`` — the single executive: one identity backing the chat and the beat, over one memory (D5).

The capstone-facing surface. Construct it over a live :class:`Horizon` + a reasoner and you get a CEO you
can talk to (:meth:`ask` / :meth:`confirm`) and hand executive work to (:meth:`govern`), all sharing one
persistent memory. Bounded autonomy (a standing :class:`AutonomyPolicy`) lets it act on pre-approved
classes of action and report after; everything else stays gated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from horizon.chat._actions import AutonomyPolicy, PendingAction
from horizon.chat._beat import BeatResult, CeoBeat
from horizon.chat._chat import Answer, CeoChat, Turn
from horizon.chat._memory import CeoMemory
from horizon.facade import Horizon
from horizon.planning._reasoner import Reasoner


class Ceo:
    """One executive: chat + beat + memory, over a live horizon."""

    def __init__(
        self,
        *,
        horizon: Horizon,
        reasoner: Reasoner,
        memory_path: str | Path = ".horizon/ceo_memory.json",
        model: str | None = None,
        directive: bool = True,
        autonomy: AutonomyPolicy | None = None,
        max_steps: int = 8,
        name: str = "ceo",
    ) -> None:
        self.name = name
        self.memory = CeoMemory(memory_path)
        self.chat = CeoChat(
            reasoner=reasoner,
            horizon=horizon,
            memory=self.memory,
            directive=directive,
            model=model,
            max_steps=max_steps,
        )
        self.beat = CeoBeat(chat=self.chat, memory=self.memory, autonomy=autonomy, by=name)

    def ask(self, question: str, *, history: Any = ()) -> Answer:
        """Talk to the CEO — a grounded, cited answer (may prepare gated actions)."""
        return self.chat.ask(question, history=history)

    def confirm(self, action: PendingAction) -> str:
        """Approve a prepared action (the human confirm)."""
        return self.chat.confirm(action, by=self.name)

    def discard(self, action: PendingAction) -> None:
        """Reject a prepared action."""
        self.chat.discard(action)

    def govern(self) -> BeatResult:
        """Run a governance-audit beat: find problems + prepare corrections (auto-applying the safe ones)."""
        return self.beat.governance_audit()

    def review_decisions(self) -> BeatResult:
        """Run a decision-review beat."""
        return self.beat.decision_review()

    def remember(self, layer: str, text: str, *, importance: float = 0.6) -> None:
        """Record something the CEO should carry forward (e.g. an org fact or a directive)."""
        self.memory.write(layer, text, importance=importance)


__all__ = ["AutonomyPolicy", "Ceo", "Turn"]
