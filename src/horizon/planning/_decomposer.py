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

from horizon.errors import DecompositionError, UnknownDecision
from horizon.model import Decision, Goal
from horizon.planning._authoring import author_goals
from horizon.planning._reasoner import Reasoner
from horizon.ports import GoalStore
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

_MAX_GOALS = 12  # a defensive cap; the prompt asks for 2-6
_CONTEXT_BLOCK = (
    "\n\nAVAILABLE CONTEXT (the resources / data / constraints the team actually has — only propose "
    "goals achievable with these; do not invent data sources that are not listed):\n__CONTEXT__\n"
)
_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous reply could not be parsed. Reply with STRICT JSON ONLY — exactly "
    '{"goals": [{"title": "...", "metric": "...", "target": "...", "rationale": "...", "score": 0.0}]} '
    "— no prose, no markdown, no code fences."
)

# The TYPED contract for what the system parses: the model must return schema-valid JSON, enforced at
# the API boundary (structured outputs) — not coaxed via prose + a regex. strict + closed objects.
_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "decomposition",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["goals"],
            "properties": {
                "goals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "metric", "target", "rationale", "score"],
                        "properties": {
                            "title": {"type": "string"},
                            "metric": {"type": "string"},
                            "target": {"type": "string"},
                            "rationale": {"type": "string"},
                            "score": {"type": "number"},
                        },
                    },
                }
            },
        },
    },
}


def _build_prompt(decision: Decision, context: str | None = None) -> str:
    prompt = _PROMPT.replace("__STATEMENT__", decision.statement.strip())
    if context:
        prompt += _CONTEXT_BLOCK.replace("__CONTEXT__", context.strip())
    return prompt


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
    # take the outermost JSON value — an object {...} or a bare array [...]
    starts = [i for i in (start, stripped.find("[")) if i != -1]
    ends = [i for i in (end, stripped.rfind("]")) if i != -1]
    if starts and ends:
        start, end = min(starts), max(ends)
        if end > start:
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
    if isinstance(data, list):
        raw: object = data  # the model sometimes returns a bare [...] array
    elif isinstance(data, dict):
        raw = data.get("goals")
    else:
        raw = None
    if not isinstance(raw, list) or not raw:
        raise DecompositionError("model returned no 'goals' array")
    goals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        key = " ".join(title.lower().split())  # dedup by normalized title
        if key in seen:
            continue
        seen.add(key)
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
    return goals[:_MAX_GOALS]


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
        max_output_tokens: int = 8000,
        context: str | None = None,
        structured: bool = True,
    ) -> None:
        self._goals = goals
        self._strategy = strategy
        self._decisions = decisions
        self._reasoner = reasoner
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._context = context
        self._structured = structured

    def decompose(self, decision_id: str) -> list[Goal]:
        """Decompose one decision into goals; idempotent-ish (re-running appends fresh goals)."""
        decision = self._decisions.get(decision_id)
        if decision is None:
            raise UnknownDecision(decision_id)

        params: dict[str, Any] = {"max_tokens": self._max_output_tokens}
        if self._model is not None:
            params["model"] = self._model
        if self._structured:
            params["response_format"] = _RESPONSE_FORMAT  # typed output, enforced at the API boundary
        prompt = _build_prompt(decision, self._context)
        result = self._reasoner.complete(prompt, params)
        try:
            specs = _parse_goals(result.text)
        except DecompositionError:
            # structured output makes this near-impossible; fall back to a plain prompt + tolerant parse
            fallback = {k: v for k, v in params.items() if k != "response_format"}
            retry = self._reasoner.complete(prompt + _RETRY_SUFFIX, fallback)
            specs = _parse_goals(retry.text)

        return author_goals(
            decision,
            specs,
            goals=self._goals,
            strategy=self._strategy,
            decisions=self._decisions,
        )
