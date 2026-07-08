"""Reporting — render horizon's direction + the loop's decision / intake / feedback insights to markdown.

A :class:`LoopReporter` accumulates the whole story of one loop — what the **Decomposer** produced, what
the **Submitter** opened, what the **OutcomeListener** folded in, and how **feedback** moved health,
score, and priority — and renders it as a readable markdown report. It is stdlib-only and reads horizon's
public model types, so a demo, a test, or the CLI can all emit the same insight report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from horizon.intake._prioritiser import ScorePolicy
from horizon.model import Decision, DecisionState, Goal
from horizon.model._strategy import StrategyRecord
from horizon.ports import OutcomeEvent
from horizon.store import DecisionStore, StrategyStore


@dataclass(frozen=True)
class Submission:
    """One goal opened as a task (the Submitter's insight)."""

    goal_id: str
    title: str
    task_id: str
    priority: str
    assignee: str | None


@dataclass(frozen=True)
class Transition:
    """One landed verdict and the health/score/priority move it caused (the feedback insight)."""

    goal_id: str
    title: str
    passed: bool
    score_before: float
    score_after: float
    health_before: str
    health_after: str
    priority_before: str
    priority_after: str


def _fmt(value: object) -> str:
    return "—" if value is None or value == "" else str(value)


class LoopReporter:
    """Accumulate one loop's story (decompose -> submit -> outcomes) and render a markdown report."""

    def __init__(self, *, title: str = "Horizon loop report", score_policy: ScorePolicy | None = None) -> None:
        self._title = title
        self._policy = score_policy or ScorePolicy()
        self._titles: dict[str, str] = {}
        self.decision: Decision | None = None
        self.decomposition: list[Goal] = []
        self.submissions: list[Submission] = []
        self.transitions: list[Transition] = []

    # -- capture ---------------------------------------------------------------

    def record_decomposition(self, decision: Decision, goals: list[Goal]) -> None:
        self.decision = decision
        self.decomposition = list(goals)
        for goal in goals:
            self._titles[goal.id] = goal.title

    def record_submission(self, goal: Goal, task_id: str, *, assignee: str | None) -> None:
        self._titles.setdefault(goal.id, goal.title)
        self.submissions.append(
            Submission(
                goal_id=goal.id,
                title=goal.title,
                task_id=task_id,
                priority=self._policy.priority_for(goal.score),
                assignee=assignee,
            )
        )

    def observe(self, event: OutcomeEvent, before: StrategyRecord, after: StrategyRecord) -> None:
        """Wire as the ``OutcomeListener`` observer to capture each feedback transition."""
        self.transitions.append(
            Transition(
                goal_id=after.goal_id,
                title=self._titles.get(after.goal_id, after.goal_id),
                passed=bool(event.passed),
                score_before=before.score,
                score_after=after.score,
                health_before=before.health,
                health_after=after.health,
                priority_before=self._policy.priority_for(before.score),
                priority_after=self._policy.priority_for(after.score),
            )
        )

    # -- render ----------------------------------------------------------------

    def render(self, states: list[DecisionState]) -> str:
        parts = [
            f"# {self._title}",
            f"_generated {datetime.now(UTC).isoformat(timespec='seconds')}_",
            self._decomposition_section(),
            self._intake_section(),
            self._feedback_section(),
            render_direction(states),
        ]
        return "\n\n".join(part for part in parts if part)

    def _decomposition_section(self) -> str:
        if not self.decomposition:
            return ""
        head = "## Decomposition — Decision → Goals (LLM)"
        if self.decision is not None:
            head += f"\n\n**Decision:** {self.decision.statement}  \n**Goals produced:** {len(self.decomposition)}"
        rows = ["| # | score | goal | metric | target |", "|---|------|------|--------|--------|"]
        for i, goal in enumerate(
            sorted(self.decomposition, key=lambda g: g.score, reverse=True), start=1
        ):
            rows.append(
                f"| {i} | {goal.score:.2f} | {_fmt(goal.title)} | {_fmt(goal.metric)} | {_fmt(goal.target)} |"
            )
        return head + "\n\n" + "\n".join(rows)

    def _intake_section(self) -> str:
        if not self.submissions:
            return ""
        rows = [
            "## Intake — Goals → chorus tasks (Submitter + Prioritiser)",
            "",
            "| goal | task | priority | assignee |",
            "|------|------|----------|----------|",
        ]
        for sub in self.submissions:
            rows.append(
                f"| {_fmt(sub.title)} | `{sub.task_id}` | **{sub.priority}** | {_fmt(sub.assignee)} |"
            )
        return "\n".join(rows)

    def _feedback_section(self) -> str:
        if not self.transitions:
            return "## Feedback — landed outcomes → health → re-priority\n\n_(no outcomes yet)_"
        rows = [
            "## Feedback — landed outcomes → health → re-priority (OutcomeListener)",
            "",
            f"**Verdicts folded:** {len(self.transitions)}",
            "",
            "| goal | verdict | health | score | priority |",
            "|------|---------|--------|-------|----------|",
        ]
        for t in self.transitions:
            verdict = "PASS" if t.passed else "FAIL"
            health = t.health_before + " → " + t.health_after
            score = f"{t.score_before:.2f} → {t.score_after:.2f}"
            priority = t.priority_before + " → " + t.priority_after
            rows.append(f"| {_fmt(t.title)} | {verdict} | {health} | {score} | {priority} |")
        return "\n".join(rows)


def render_direction(states: list[DecisionState]) -> str:
    """Render the current direction tree (decisions → goals with score/health/priority/task)."""
    policy = ScorePolicy()
    lines = ["## Current direction (read model)"]
    if not states:
        return lines[0] + "\n\n_(no decisions)_"
    for state in states:
        decision = state.decision
        lines.append(f"\n### {decision.statement}  \n`{decision.id}` · status={decision.status}")
        if not state.goals:
            lines.append("\n_(no goals yet)_")
            continue
        lines.append("\n| score | priority | health | goal | task |")
        lines.append("|-------|----------|--------|------|------|")
        for goal in sorted(state.goals, key=lambda g: g.score, reverse=True):
            priority = policy.priority_for(goal.score)
            task = f"`{goal.task_id}`" if goal.task_id else "—"
            lines.append(
                f"| {goal.score:.2f} | {priority} | {goal.health} | {_fmt(goal.title)} | {task} |"
            )
    return "\n".join(lines)


def direction_from_records(
    decisions: DecisionStore, strategy: StrategyStore
) -> list[DecisionState]:
    """Build the direction read model from horizon's own stores alone (offline; uses cached titles)."""
    by_goal = {record.goal_id: record for record in strategy.all()}
    states: list[DecisionState] = []
    for decision in decisions.all():
        goals: list[Goal] = []
        for goal_id in decision.goal_ids:
            record = by_goal.get(goal_id)
            if record is None:
                continue
            goals.append(
                Goal(
                    id=record.goal_id,
                    title=record.title or record.goal_id,
                    decision_id=record.decision_id,
                    status="done" if record.done else "active",
                    score=record.score,
                    health=record.health,
                    metric=record.metric,
                    target=record.target,
                    evidence=list(record.evidence),
                    task_id=record.task_id,
                )
            )
        states.append(DecisionState(decision=decision, goals=goals))
    return states


__all__ = [
    "LoopReporter",
    "Submission",
    "Transition",
    "direction_from_records",
    "render_direction",
]
