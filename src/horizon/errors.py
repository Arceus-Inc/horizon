"""horizon error types."""

from __future__ import annotations


class HorizonError(Exception):
    """Base class for all horizon errors."""


class UnknownDecision(HorizonError):
    """Raised when a decision id is not found in the store."""


class UnknownGoal(HorizonError):
    """Raised when a goal id is not found (neither in the seam skeleton nor the strategy store)."""


class DecompositionError(HorizonError):
    """Raised when the LLM decomposition output cannot be parsed into at least one valid goal."""


class UnknownProposal(HorizonError):
    """Raised when a proposal id is not found in the store."""


class ProposalNotOpen(HorizonError):
    """Raised when approving/rejecting a proposal that is no longer 'proposed'."""


class EgressBlocked(HorizonError):
    """Raised when the governance gate refuses an external fetch (host / credential / size)."""


class GenerationError(HorizonError):
    """Raised when a scout/analyst LLM reply cannot be parsed into the expected structured output."""
