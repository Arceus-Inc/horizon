"""``CeoBeat`` — the CEO acting as an employee: bounded, unattended executive runs (D4).

A beat is "the CEO thinking hard, unattended, and writing back a directive-grade result." It reuses the
whole chat foundation — the same context, tools, memory, and confirm-to-write gate — but runs on a
high-level executive task (a governance audit, a decision review) instead of a human question. It
produces a memo *and* a set of prepared corrective actions (still gated: a human confirms them), and
logs the run to the decision-log so the CEO remembers what it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from horizon.chat._actions import AutonomyPolicy, PendingAction, permits
from horizon.chat._chat import CeoChat, ChatStep
from horizon.chat._memory import CeoMemory

_GOVERNANCE_TASK = (
    "Run a GOVERNANCE AUDIT of the entire company. Inspect the direction (every decision and goal) and "
    "the open proposals. Identify every problem: goals that are blocked or drifting, goals that look "
    "stale or dead, duplicated or runaway work, and proposals waiting on a decision. For EACH problem, "
    "prepare a concrete corrective action with the gated write tools — archive a dead goal, re-prioritise "
    "a mis-ranked one, approve a strong proposal, or reject a weak one. Then ANSWER with a concise "
    "executive memo: what you found and what you have prepared for confirmation."
)

_DECISION_REVIEW_TASK = (
    "Review each ACTIVE decision. For each, judge whether it is on track given its goals' health, and "
    "whether it should be re-scoped, re-prioritised, or flagged. Prepare any corrective actions (gated). "
    "ANSWER with a short per-decision memo and the actions you have prepared."
)


@dataclass(frozen=True)
class BeatResult:
    """The output of a CEO beat: the memo, what it cited, and the corrections it prepared (gated)."""

    label: str
    findings: str
    citations: list[str] = field(default_factory=list)
    prepared_actions: list[PendingAction] = field(default_factory=list)
    steps: list[ChatStep] = field(default_factory=list)
    auto_applied: list[str] = field(default_factory=list)  # action ids applied under standing autonomy


class CeoBeat:
    """Run the CEO as an unattended executive employee over a high-level task."""

    def __init__(
        self,
        *,
        chat: CeoChat,
        memory: CeoMemory | None = None,
        autonomy: AutonomyPolicy | None = None,
        by: str = "ceo",
    ) -> None:
        self._chat = chat
        self._memory = memory
        self._autonomy = autonomy
        self._by = by

    def governance_audit(self) -> BeatResult:
        """Audit the whole company and prepare corrective actions (gated)."""
        return self.run(_GOVERNANCE_TASK, label="governance-audit")

    def decision_review(self) -> BeatResult:
        """Review every active decision and prepare corrections (gated)."""
        return self.run(_DECISION_REVIEW_TASK, label="decision-review")

    def run(self, task: str, *, label: str = "executive-beat") -> BeatResult:
        """Run one executive task; returns the memo + prepared actions, and logs it to memory."""
        answer = self._chat.ask(task)
        auto_applied = self._apply_autonomous(answer.pending_actions)
        result = BeatResult(
            label=label,
            findings=answer.text,
            citations=answer.citations,
            prepared_actions=answer.pending_actions,
            steps=answer.steps,
            auto_applied=auto_applied,
        )
        if self._memory is not None:
            pending = len(result.prepared_actions) - len(auto_applied)
            self._memory.write(
                "decision-log",
                f"CEO {label}: {answer.text} "
                f"(auto-applied {len(auto_applied)}, {pending} awaiting confirm)",
                importance=0.7,
                tags=[label],
            )
        return result

    def _apply_autonomous(self, actions: list[PendingAction]) -> list[str]:
        """Apply the actions a standing directive pre-approves (report-after); returns their ids."""
        if self._autonomy is None:
            return []
        applied: list[str] = []
        for action in actions:
            if len(applied) >= self._autonomy.max_auto:
                break
            if action.status == "pending" and permits(self._autonomy, action, self._chat.horizon):
                self._chat.confirm(action, by=self._by)
                applied.append(action.id)
        return applied
