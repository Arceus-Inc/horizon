"""``author_goals`` — write goal specs into the live tree (GoalStore + StrategyStore + decision link).

The shared authoring step used by **both** the LLM :class:`~horizon.planning._decomposer.Decomposer` and
the generation funnel's approval promote. Given a decision and a list of goal specs
(``title`` / ``metric`` / ``target`` / ``rationale`` / ``score``), it mints goal ids, upserts the
chorus-seam ``GoalNode``s, writes the horizon ``StrategyRecord``s, records the decision -> goal edges, and
returns the rich :class:`~horizon.model.Goal` views. No LLM here — just the write — so the decomposer and
the funnel author goals **identically**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from horizon._ids import mint_id
from horizon.model import Decision, Goal
from horizon.model._strategy import StrategyRecord
from horizon.ports import GoalNode, GoalStore
from horizon.store import DecisionStore, StrategyStore


def author_goals(
    decision: Decision,
    specs: Sequence[Mapping[str, Any]],
    *,
    goals: GoalStore,
    strategy: StrategyStore,
    decisions: DecisionStore,
) -> list[Goal]:
    """Author each spec as a live goal under ``decision``; returns the created :class:`Goal` views."""
    made: list[Goal] = []
    new_ids: list[str] = []
    for spec in specs:
        goal_id = mint_id("goal")
        goals.upsert(
            GoalNode(
                id=goal_id,
                title=spec["title"],
                level="goal",
                status="active",
                owner=decision.owner,
            )
        )
        rationale = spec.get("rationale") or ""
        record = StrategyRecord(
            goal_id=goal_id,
            title=spec["title"],
            score=spec["score"],
            metric=spec.get("metric"),
            target=spec.get("target"),
            evidence=[rationale] if rationale else [],
            decision_id=decision.id,
            delivery_shape=spec.get("delivery_shape", "single"),
            lead_professions=tuple(spec.get("lead_professions", ())),
            staffing_requirements=tuple(spec.get("staffing_requirements", ())),
        )
        strategy.put(record)
        made.append(
            Goal(
                id=goal_id,
                title=spec["title"],
                decision_id=decision.id,
                status="active",
                owner=decision.owner,
                score=record.score,
                metric=record.metric,
                target=record.target,
                evidence=list(record.evidence),
                delivery_shape=record.delivery_shape,
                lead_professions=record.lead_professions,
                staffing_requirements=record.staffing_requirements,
            )
        )
        new_ids.append(goal_id)

    decision.goal_ids = list(dict.fromkeys([*decision.goal_ids, *new_ids]))
    decisions.put(decision)
    return made
