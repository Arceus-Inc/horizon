"""Reporting — render horizon's direction (decisions -> goals -> execution) to markdown.

Stdlib-only readers over horizon's public model types: ``render_direction`` renders the direction
read model, and ``direction_from_records`` builds that read model from horizon's own stores alone,
so the CLI and tests can emit the same insight offline.
"""

from __future__ import annotations

from horizon.intake._prioritiser import ScorePolicy
from horizon.model import DecisionState, Goal
from horizon.store import DecisionStore, StrategyStore


def _fmt(value: object) -> str:
    return "—" if value is None or value == "" else str(value)


def render_direction(states: list[DecisionState]) -> str:
    """Render direction with raw/effective priority and execution attribution."""
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
        lines.append("\n| raw -> effective | priority | health | goal | execution | reason |")
        lines.append("|------------------|----------|--------|------|-----------|--------|")
        for goal in sorted(state.goals, key=lambda g: g.score, reverse=True):
            effective_score = (
                goal.effective_score if goal.effective_score is not None else goal.score
            )
            priority = goal.effective_priority or policy.priority_for(effective_score)
            execution = _execution_summary(goal)
            lines.append(
                f"| {goal.score:.2f} -> {effective_score:.2f} | {priority} | {goal.health} | "
                f"{_fmt(goal.title)} | {execution} | {_fmt(goal.priority_reason)} |"
            )
    return "\n".join(lines)


def _execution_summary(goal: Goal) -> str:
    root = goal.root_task_id or goal.task_id
    parts = [goal.delivery_shape]
    if root:
        parts.append(f"root `{root}`")
    if goal.team_id:
        parts.append(f"team `{goal.team_id}`")
    if goal.lead_id:
        parts.append(f"lead `{goal.lead_id}`")
    if goal.task_ids:
        parts.append(f"{len(goal.task_ids)} tasks")
    return "; ".join(parts)


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
                    root_task_id=record.root_task_id,
                    task_ids=list(record.task_ids),
                    team_id=record.team_id,
                    lead_id=record.lead_id,
                    task_outcomes=dict(record.task_outcomes),
                    delivery_shape=record.delivery_shape,
                    lead_professions=record.lead_professions,
                    staffing_requirements=record.staffing_requirements,
                    effective_score=record.score,
                    effective_priority=ScorePolicy().priority_for(record.score),
                    priority_reason="capacity snapshot unavailable; raw score used",
                )
            )
        states.append(DecisionState(decision=decision, goals=goals))
    return states


__all__ = [
    "direction_from_records",
    "render_direction",
]
