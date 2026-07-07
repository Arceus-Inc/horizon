"""``Reasoner`` — the minimal LLM-completion port horizon reasons through (a subset of dream's Substrate).

horizon keeps the surface to the single method it needs (``complete``). Both dream's
``OpenAIChatSubstrate`` and a test fake satisfy it structurally, so the composition root wires the real
Azure/OpenAI-compatible substrate while unit tests pass a canned fake — no network, no chorus.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dream.api.substrate import CompletionResult


@runtime_checkable
class Reasoner(Protocol):
    """A single non-streaming LLM completion (the ``complete`` method of dream's ``Substrate``)."""

    def complete(self, prompt: str, params: dict[str, Any] | None = None) -> CompletionResult: ...


__all__ = ["CompletionResult", "Reasoner"]
