"""CEO read tools — the grounded lookups the chat calls to answer (D1).

Each tool takes the live ``Horizon`` + parsed args and returns a :class:`ToolResult` (an observation the
CEO reads back, plus the ids it should cite). Tools are registered in :data:`READ_TOOLS`; the chat engine
reflects their specs into the prompt and dispatches by name. Write/beat tools land in later slices behind
the confirm gate — these are read-only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from horizon.chat._context import ContextAssembler
from horizon.facade import Horizon


@dataclass(frozen=True)
class ToolResult:
    """What a tool hands back to the CEO: a text observation + the ids worth citing."""

    observation: str
    citations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolSpec:
    """A tool the CEO can call: name, one-line description, and its argument names."""

    name: str
    description: str
    args: dict[str, str]  # arg_name -> what it is
    run: Callable[[Horizon, dict[str, Any]], ToolResult]


def _query_direction(horizon: Horizon, _args: dict[str, Any]) -> ToolResult:
    ctx = ContextAssembler(horizon).assemble()
    cites: list[str] = []
    for d in ctx.decisions:
        cites.append(d.decision_id)
        cites.extend(g.goal_id for g in d.goals)
    cites.extend(p.proposal_id for p in ctx.proposals)
    obs = ctx.render() if not ctx.is_empty() else "The company has no active decisions or proposals yet."
    return ToolResult(observation=obs, citations=cites)


def _inspect_goal(horizon: Horizon, args: dict[str, Any]) -> ToolResult:
    goal_id = str(args.get("goal_id", "")).strip()
    if not goal_id:
        return ToolResult(observation="inspect_goal needs a 'goal_id' argument.", citations=[])
    goal = horizon.goal_view(goal_id)
    if goal is None:
        return ToolResult(observation=f"No goal found with id {goal_id!r}.", citations=[])
    lines = [
        f"GOAL [{goal.id}] {goal.title}",
        f"  decision: {goal.decision_id}",
        f"  score: {goal.score:.2f} · health: {goal.health} · status: {goal.status}",
        f"  metric: {goal.metric} -> target: {goal.target}",
        f"  realizing task: {goal.task_id or '—'}",
    ]
    if goal.evidence:
        lines.append("  rationale/evidence: " + " | ".join(goal.evidence[:3]))
    return ToolResult(observation="\n".join(lines), citations=[goal.id])


def _list_proposals(horizon: Horizon, args: dict[str, Any]) -> ToolResult:
    status = args.get("status")
    status = None if status in (None, "", "all") else str(status)
    proposals = horizon.list_proposals(status=status)
    if not proposals:
        return ToolResult(observation="No proposals match.", citations=[])
    lines = [
        f"- [{p.id}] ({p.status}) {p.decision_statement}" for p in proposals
    ]
    return ToolResult(observation="\n".join(lines), citations=[p.id for p in proposals])


def _explain_proposal(horizon: Horizon, args: dict[str, Any]) -> ToolResult:
    pid = str(args.get("proposal_id", "")).strip()
    if not pid:
        return ToolResult(observation="explain_proposal needs a 'proposal_id' argument.", citations=[])
    try:
        text = horizon.explain_proposal(pid)
    except Exception as exc:
        return ToolResult(observation=f"Could not explain {pid!r}: {exc}", citations=[])
    return ToolResult(observation=text, citations=[pid])


READ_TOOLS: dict[str, ToolSpec] = {
    "query_direction": ToolSpec(
        name="query_direction",
        description="The whole company direction: every decision with its goals (score, priority, "
        "health, status, task) and any open proposals.",
        args={},
        run=_query_direction,
    ),
    "inspect_goal": ToolSpec(
        name="inspect_goal",
        description="Full detail on one goal by id (metric/target, health, rationale, realizing task).",
        args={"goal_id": "the goal id to inspect"},
        run=_inspect_goal,
    ),
    "list_proposals": ToolSpec(
        name="list_proposals",
        description="List funnel proposals, optionally filtered by status "
        "(proposed | approved | rejected | all).",
        args={"status": "optional status filter; omit for open proposals"},
        run=_list_proposals,
    ),
    "explain_proposal": ToolSpec(
        name="explain_proposal",
        description="A preview of what approving a proposal would create (the brief, its goals, "
        "evidence) — read only.",
        args={"proposal_id": "the proposal id to explain"},
        run=_explain_proposal,
    ),
}


def render_tool_specs(tools: dict[str, ToolSpec]) -> str:
    """Reflect the tools into a prompt block the CEO reads to know what it can call."""
    lines: list[str] = []
    for spec in tools.values():
        argsig = ", ".join(f"{k}" for k in spec.args) or "(no args)"
        lines.append(f"- {spec.name}({argsig}): {spec.description}")
        for arg, desc in spec.args.items():
            lines.append(f"    · {arg}: {desc}")
    return "\n".join(lines)
