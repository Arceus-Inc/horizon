"""The Decomposer — turn a **Decision** into a small set of executable **Goals** via an LLM.

horizon's core job (*"Decisions ko Goals banaye"*). Given a horizon-native :class:`Decision`, ask a
:class:`Reasoner` (dream's substrate, or a fake) for a strict-JSON breakdown, validate it, and author
the goal tree: each goal becomes a ``GoalNode`` on the chorus seam (level ``goal``) plus a
:class:`StrategyRecord` holding the strategy-only fields (score / metric / target / rationale) and the
decision link. The decision's ``goal_ids`` are updated so the (horizon-only) decision -> goal edges are
recorded. v1 is **flat** — a decision yields leaf goals, each of which the intake layer submits as one
task; nested goal-trees arrive with the manager.
"""

from __future__ import annotations

import json
from typing import Any

from horizon._ids import mint_id
from horizon.errors import DecompositionError, UnknownDecision
from horizon.model import Decision, Goal
from horizon.model._strategy import StrategyRecord
from horizon.planning._reasoner import Reasoner
from horizon.ports import GoalNode, GoalStore
from horizon.store import DecisionStore, StrategyStore

_PROMPT = """You are the strategy decomposer for an autonomous software company.

A DECISION is a high-level strategic intent. Break it into a small set of concrete,
independently-executable GOALS. If every goal is completed, the decision is achieved.

Rules:
- Produce 2 to 6 goals; fewer is better for a small decision.
- Each goal is ONE deliverable a single engineer can complete whole (never a whole team's worth).
- Titles are concrete and imperative ("Build the note-capture REST API", not "Backend work").
- For each goal give: `metric` (how we know it is done), `target` (the concrete bar), a short
  `rationale`, and a `score` in [0,1] for relative priority (1 = do first).
- Order goals by score, highest first.
- Output STRICT JSON only — no prose, no code fences — matching exactly:
  {"goals": [{"title": "...", "metric": "...", "target": "...", "rationale": "...", "score": 0.0}]}

DECISION:
__STATEMENT__
"""


def _build_prompt(decision: Decision) -> str:
    return _PROMPT.replace("__STATEMENT__", decision.statement.strip())


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a model reply that may be fenced or wrapped in prose."""
    stripped = text.strip()
    if "```" in stripped:
        for chunk in stripped.split("```"):
            candidate = chunk[4:].strip() if chunk.startswith("json") else chunk.strip()
            if candidate.startswith("{"):
                stripped = candidate
                break
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clamp_score(value: object) -> float:
    if isinstance(value, bool):
        return 0.5
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    if isinstance(value, str):
        try:
            return min(1.0, max(0.0, float(value)))
        except ValueError:
            return 0.5
    return 0.5


def _parse_goals(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(_extract_json(text))
    except json.JSONDecodeError as exc:
        raise DecompositionError(f"model output was not valid JSON: {exc}") from exc
    raw = data.get("goals") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise DecompositionError("model returned no 'goals' array")
    goals: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        goals.append(
            {
                "title": title,
                "metric": _opt_str(item.get("metric")),
                "target": _opt_str(item.get("target")),
                "rationale": _opt_str(item.get("rationale")) or "",
                "score": _clamp_score(item.get("score")),
            }
        )
    if not goals:
        raise DecompositionError("model output contained no valid goals (all missing a title)")
    return goals


class Decomposer:
    """Decision -> Goals via an LLM, writing the goal tree + strategy records + the decision link."""

    def __init__(
        self,
        *,
        goals: GoalStore,
        strategy: StrategyStore,
        decisions: DecisionStore,
        reasoner: Reasoner,
        model: str | None = None,
        max_output_tokens: int = 1500,
    ) -> None:
        self._goals = goals
        self._strategy = strategy
        self._decisions = decisions
        self._reasoner = reasoner
        self._model = model
        self._max_output_tokens = max_output_tokens

    def decompose(self, decision_id: str) -> list[Goal]:
        """Decompose one decision into goals; idempotent-ish (re-running appends fresh goals)."""
        decision = self._decisions.get(decision_id)
        if decision is None:
            raise UnknownDecision(decision_id)

        params: dict[str, Any] = {"max_tokens": self._max_output_tokens}
        if self._model is not None:
            params["model"] = self._model
        result = self._reasoner.complete(_build_prompt(decision), params)
        specs = _parse_goals(result.text)

        goals: list[Goal] = []
        new_ids: list[str] = []
        for spec in specs:
            goal_id = mint_id("goal")
            self._goals.upsert(
                GoalNode(
                    id=goal_id,
                    title=spec["title"],
                    level="goal",
                    status="active",
                    owner=decision.owner,
                )
            )
            rationale = spec["rationale"]
            record = StrategyRecord(
                goal_id=goal_id,
                score=spec["score"],
                metric=spec["metric"],
                target=spec["target"],
                evidence=[rationale] if rationale else [],
                decision_id=decision.id,
            )
            self._strategy.put(record)
            goals.append(
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
                )
            )
            new_ids.append(goal_id)

        decision.goal_ids = list(dict.fromkeys([*decision.goal_ids, *new_ids]))
        self._decisions.put(decision)
        return goals
