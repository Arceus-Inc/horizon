"""``CeoChat`` — the CEO's conversational engine: a grounded, tool-using ReAct loop (D1).

Each turn the CEO assembles live company context, then reasons in steps. At every step the model returns
a strict-JSON decision: either **call a read tool** (to look something up) or **answer** (with the ids it
cites). The engine runs the tool, feeds the observation back, and loops until the model answers or the
step budget runs out. Read-only for now — directive (gated write) tools land in a later slice.

The step shape is deliberately flat + strict so the API enforces it: a non-empty ``tool`` means "act",
an empty ``tool`` means "the answer is in ``answer_text``". Tool args ride as a JSON string to keep the
schema closed. A tolerant fallback (drop the schema, retry once) covers the rare unparseable reply.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from horizon._jsonio import extract_json
from horizon.chat._actions import ActionExecutor, PendingAction
from horizon.chat._context import ContextAssembler
from horizon.chat._memory import CeoMemory, render_memories
from horizon.chat._tools import (
    READ_TOOLS,
    WRITE_TOOLS,
    ToolResult,
    ToolSpec,
    WriteSpec,
    make_memory_tools,
    render_tool_specs,
    render_write_specs,
)
from horizon.errors import ChatError
from horizon.facade import Horizon
from horizon.planning._reasoner import Reasoner

_PERSONA = """You are the CEO of an autonomous software company. A human executive is talking to you.

Answer their question about the company using ONLY the tools and the COMPANY STATE provided — never
invent facts, numbers, ids, decisions, or outcomes. If the state does not contain the answer, say so
plainly. Be concise, direct, and executive: lead with the answer, then the why.

Ground every claim: when you answer, list the ids you relied on (goal ids, proposal ids, decision ids)
in `citations`. If you need to look something up, call a tool first.

You work in reasoning steps. At EACH step return STRICT JSON only — no prose, no code fences — matching:
  {"thought": "...", "tool": "", "args_json": "", "answer_text": "", "citations": []}
- To CALL A TOOL: set `tool` to the tool name and `args_json` to a JSON object string of its args
  (e.g. "{\\"goal_id\\": \\"goal_123\\"}"), leave `answer_text` empty.
- To ANSWER: leave `tool` empty, put your reply in `answer_text`, and list `citations`.

GATED WRITES: some tools (marked GATED) do NOT take effect when you call them — they PREPARE an action
for the human to confirm. Never claim a gated change is done; say you've prepared it and it awaits their
confirmation. Prepare only what the human actually asked for.

AVAILABLE TOOLS:
__TOOLS__
"""

_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous reply could not be parsed. Reply with STRICT JSON ONLY matching "
    '{"thought": "...", "tool": "", "args_json": "", "answer_text": "", "citations": []} — no prose, '
    "no markdown, no code fences."
)

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "ceo_step",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["thought", "tool", "args_json", "answer_text", "citations"],
            "properties": {
                "thought": {"type": "string"},
                "tool": {"type": "string"},
                "args_json": {"type": "string"},
                "answer_text": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


@dataclass(frozen=True)
class ChatStep:
    """One step of the CEO's reasoning — a tool call and what it observed (for the audit trail)."""

    thought: str
    tool: str
    args: dict[str, Any]
    observation: str
    citations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Answer:
    """The CEO's grounded reply: the text, the ids it cited, the steps, and any prepared writes."""

    text: str
    citations: list[str] = field(default_factory=list)
    steps: list[ChatStep] = field(default_factory=list)
    pending_actions: list[PendingAction] = field(default_factory=list)


@dataclass(frozen=True)
class Turn:
    """A prior exchange, for multi-turn conversations (memory plugs in here later)."""

    question: str
    answer: str


class CeoChat:
    """A grounded, tool-using CEO conversation over a :class:`Reasoner`."""

    def __init__(
        self,
        *,
        reasoner: Reasoner,
        horizon: Horizon,
        tools: dict[str, ToolSpec] | None = None,
        memory: CeoMemory | None = None,
        directive: bool = False,
        model: str | None = None,
        max_steps: int = 6,
        max_output_tokens: int = 4000,
        structured: bool = True,
    ) -> None:
        self._reasoner = reasoner
        self._horizon = horizon
        self._memory = memory
        base_tools = dict(tools) if tools is not None else dict(READ_TOOLS)
        if memory is not None:
            base_tools.update(make_memory_tools(memory))
        self._tools = base_tools
        self._write_tools: dict[str, WriteSpec] = dict(WRITE_TOOLS) if directive else {}
        self._executor = ActionExecutor(horizon, memory=memory) if directive else None
        self._model = model
        self._max_steps = max_steps
        self._max_output_tokens = max_output_tokens
        self._structured = structured

    def confirm(self, action: PendingAction, *, by: str) -> str:
        """Apply a prepared action (the human confirm). Requires directive mode."""
        if self._executor is None:
            raise ChatError("this chat is read-only; no executor to confirm writes")
        return self._executor.apply(action, by=by)

    def discard(self, action: PendingAction) -> None:
        """Reject a prepared action without applying it."""
        if self._executor is not None:
            self._executor.discard(action)

    @property
    def horizon(self) -> Horizon:
        """The live horizon this chat reads/writes — used by the beat's autonomy check."""
        return self._horizon

    def ask(self, question: str, *, history: Sequence[Turn] = ()) -> Answer:
        """Answer one question, grounding it in live company state via tool calls."""
        context = ContextAssembler(self._horizon).assemble()
        tools_block = render_tool_specs(self._tools)
        if self._write_tools:
            tools_block += "\n\nGATED WRITE TOOLS (prepare an action; human confirms):\n" + render_write_specs(
                self._write_tools
            )
        system = _PERSONA.replace("__TOOLS__", tools_block)
        transcript: list[str] = []
        if self._memory is not None:
            recalled = render_memories(self._memory.recall(question, limit=4))
            if recalled:
                transcript.append(recalled)
        if history:
            transcript.append("EARLIER IN THIS CONVERSATION:")
            for turn in history:
                transcript.append(f"  Q: {turn.question}\n  A: {turn.answer}")
        transcript.append(f"\n{context.render()}")
        transcript.append(f"\nQUESTION: {question}")

        steps: list[ChatStep] = []
        pending: list[PendingAction] = []
        answer: Answer | None = None
        for _ in range(self._max_steps):
            prompt = system + "\n\n" + "\n".join(transcript)
            step = self._reason(prompt)
            tool = step["tool"].strip()
            if not tool:
                answer = Answer(
                    text=step["answer_text"].strip(),
                    citations=[str(c) for c in step["citations"]],
                    steps=steps,
                    pending_actions=pending,
                )
                break
            observation, args, cites = self._dispatch(tool, step["args_json"], pending)
            steps.append(
                ChatStep(
                    thought=step["thought"], tool=tool, args=args,
                    observation=observation, citations=cites,
                )
            )
            transcript.append(
                f"\nSTEP: called {tool}({json.dumps(args)})\nOBSERVATION:\n{observation}"
            )
        if answer is None:
            gathered = [c for s in steps for c in s.citations]
            answer = Answer(
                text="I could not fully resolve that within my step budget. Here is what I found: "
                + (steps[-1].observation if steps else "nothing conclusive."),
                citations=list(dict.fromkeys(gathered)),
                steps=steps,
                pending_actions=pending,
            )
        self._remember(question, answer)
        return answer

    def _remember(self, question: str, answer: Answer) -> None:
        """Persist the exchange to the conversation layer so the CEO recalls it later."""
        if self._memory is None:
            return
        self._memory.write(
            "conversation",
            f"Q: {question}\nA: {answer.text}",
            tags=answer.citations,
            importance=0.3,
        )

    def _dispatch(
        self, tool: str, args_json: str, pending: list[PendingAction]
    ) -> tuple[str, dict[str, Any], list[str]]:
        args = _parse_args(args_json)
        if tool in self._write_tools:
            action = self._write_tools[tool].prepare(self._horizon, args)
            pending.append(action)
            obs = (
                f"Prepared {action.kind} [{action.id}] — PENDING your confirmation (not applied). "
                f"Preview:\n{action.preview}"
            )
            return obs, args, list(action.evidence)
        spec = self._tools.get(tool)
        if spec is None:
            known = ", ".join([*self._tools, *self._write_tools])
            return f"Unknown tool {tool!r}. Available: {known}.", args, []
        result: ToolResult = spec.run(self._horizon, args)
        return result.observation, args, result.citations

    def _reason(self, prompt: str) -> dict[str, Any]:
        params: dict[str, Any] = {"max_tokens": self._max_output_tokens}
        if self._model is not None:
            params["model"] = self._model
        if self._structured:
            params["response_format"] = _RESPONSE_FORMAT
        result = self._reasoner.complete(prompt, params)
        try:
            return _parse_step(result.text)
        except ChatError:
            fallback = {k: v for k, v in params.items() if k != "response_format"}
            retry = self._reasoner.complete(prompt + _RETRY_SUFFIX, fallback)
            return _parse_step(retry.text)


def _parse_args(args_json: str) -> dict[str, Any]:
    if not args_json.strip():
        return {}
    try:
        parsed = json.loads(args_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_step(text: str) -> dict[str, Any]:
    try:
        data = json.loads(extract_json(text))
    except json.JSONDecodeError as exc:
        raise ChatError(f"chat step was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ChatError("chat step was not a JSON object")
    return {
        "thought": str(data.get("thought", "")),
        "tool": str(data.get("tool", "")),
        "args_json": str(data.get("args_json", "")),
        "answer_text": str(data.get("answer_text", "")),
        "citations": list(data.get("citations", []) or []),
    }
