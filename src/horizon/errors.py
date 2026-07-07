"""horizon error types."""

from __future__ import annotations


class HorizonError(Exception):
    """Base class for all horizon errors."""


class UnknownDecision(HorizonError):
    """Raised when a decision id is not found in the store."""


class UnknownGoal(HorizonError):
    """Raised when a goal id is not found (neither in the seam skeleton nor the strategy store)."""
