"""``ContextAssembler`` + ``CompanyContext`` — the bounded snapshot the CEO reasons over (D1).

Before every turn the assembler gathers a ranked, trimmed view of the company from horizon's read model
(the Decision -> Goal tree) and the funnel's proposal queue, and renders it into a compact text block the
CEO's LLM can read. This is the difference between an executive and a chatbot: the answer is grounded in
live state, not vibes. Chorus-ledger and ops context plug in later (D4) via the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from horizon.facade import Horizon
from horizon.intake import ScorePolicy


@dataclass(frozen=True)
class GoalLine:
    """One goal in the CEO's context — the rich view plus its derived priority."""

    goal_id: str
    title: str
    score: float
    priority: str
    health: str
    status: str
    task_id: str | None
    metric: str | None
    target: str | None


@dataclass(frozen=True)
class DecisionLine:
    """One decision with its goals."""

    decision_id: str
    statement: str
    status: str
    goals: list[GoalLine] = field(default_factory=list)


@dataclass(frozen=True)
class ProposalLine:
    """One funnel proposal awaiting a human decision."""

    proposal_id: str
    statement: str
    status: str


@dataclass(frozen=True)
class CompanyContext:
    """The whole bounded snapshot: decisions + goals + open proposals, at a point in time."""

    decisions: list[DecisionLine]
    proposals: list[ProposalLine]
    generated_at: str

    def is_empty(self) -> bool:
        return not self.decisions and not self.proposals

    def render(self) -> str:
        """A compact, id-annotated text block for the CEO's prompt (what it may cite)."""
        lines: list[str] = [f"COMPANY STATE (as of {self.generated_at})"]
        if not self.decisions:
            lines.append("\nDecisions: (none active)")
        for d in self.decisions:
            lines.append(f"\nDECISION [{d.decision_id}] ({d.status}): {d.statement}")
            if not d.goals:
                lines.append("  goals: (none)")
            for g in d.goals:
                task = g.task_id or "—"
                mt = f" · metric: {g.metric} -> {g.target}" if g.metric else ""
                lines.append(
                    f"  - GOAL [{g.goal_id}] {g.title} "
                    f"(score {g.score:.2f}, priority {g.priority}, health {g.health}, "
                    f"status {g.status}, task {task}){mt}"
                )
        if self.proposals:
            lines.append("\nOPEN PROPOSALS (awaiting approval):")
            for p in self.proposals:
                lines.append(f"  - PROPOSAL [{p.proposal_id}] ({p.status}): {p.statement}")
        return "\n".join(lines)


class ContextAssembler:
    """Assemble a :class:`CompanyContext` from horizon's read model + the proposal queue."""

    def __init__(self, horizon: Horizon, *, score_policy: ScorePolicy | None = None) -> None:
        self._horizon = horizon
        self._score_policy = score_policy or ScorePolicy()

    def assemble(self) -> CompanyContext:
        decisions: list[DecisionLine] = []
        for st in self._horizon.state():
            goals = [
                GoalLine(
                    goal_id=g.id,
                    title=g.title,
                    score=g.score,
                    priority=self._score_policy.priority_for(g.score),
                    health=g.health,
                    status=g.status,
                    task_id=g.task_id,
                    metric=g.metric,
                    target=g.target,
                )
                for g in sorted(st.goals, key=lambda g: g.score, reverse=True)
            ]
            decisions.append(
                DecisionLine(
                    decision_id=st.decision.id,
                    statement=st.decision.statement,
                    status=st.decision.status,
                    goals=goals,
                )
            )
        proposals = [
            ProposalLine(proposal_id=p.id, statement=p.decision_statement, status=p.status)
            for p in self._horizon.list_proposals(status="proposed")
        ]
        return CompanyContext(
            decisions=decisions,
            proposals=proposals,
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
