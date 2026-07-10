"""chat — the CEO's conversational surface (Theme D).

The CEO is a chattable executive: you ask it about the whole company and it answers, grounded in
horizon's live read model + the funnel queue, citing the ids it used. This package holds the context
assembler (what the CEO knows), the read tools (how it looks things up), and the ReAct chat engine.
Memory, gated write tools, and the CEO-as-employee beat land in later slices.
"""

from __future__ import annotations

from horizon.chat._chat import Answer, CeoChat, ChatStep, Turn
from horizon.chat._context import (
    CompanyContext,
    ContextAssembler,
    DecisionLine,
    GoalLine,
    ProposalLine,
)
from horizon.chat._tools import READ_TOOLS, ToolResult, ToolSpec, render_tool_specs

__all__ = [
    "READ_TOOLS",
    "Answer",
    "CeoChat",
    "ChatStep",
    "CompanyContext",
    "ContextAssembler",
    "DecisionLine",
    "GoalLine",
    "ProposalLine",
    "ToolResult",
    "ToolSpec",
    "Turn",
    "render_tool_specs",
]
