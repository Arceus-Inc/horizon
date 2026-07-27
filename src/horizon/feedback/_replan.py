"""``detect_replan`` — the deterministic re-plan signal that wakes the CEO (no LLM).

horizon never dispatches; it *signals*. This pure predicate reads the reality digest (A1) and decides
whether the company's direction needs the CEO's attention — the passive trigger the loop was missing.
It fires on the conditions the one-mind-one-ledger spec names, all derivable from the digest:

- **no in-flight goals** — the roadmap is exhausted (everything landed) or unstarted; plan the next slice;
- **free capacity** — building power sits idle beyond the in-flight pipeline; there is room for more work;
- **blocked goals** — direction has drifted and needs re-scoping.

The consumer (conductor/operator) turns a firing signal into a CEO wake, deduping so it does not
re-wake while a re-plan is already pending. Staleness/recovery keep their own deterministic sweeps; this
is the *direction*-level trigger that sits above them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from horizon.model._digest import RealityDigest


@dataclass(frozen=True)
class ReplanSignal:
    """Whether the CEO should be woken to re-plan, and the concrete reasons why."""

    should_replan: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)


def detect_replan(digest: RealityDigest) -> ReplanSignal:
    """Fold the reality digest into a re-plan signal — pure, deterministic, LLM-free."""
    reasons: list[str] = []

    if not digest.in_flight:
        reasons.append("no in-flight goals — the roadmap is exhausted or unstarted")

    free_slots = sum(max(0, cap.eligible - cap.assigned_nonterminal) for cap in digest.capacity)
    if free_slots > len(digest.in_flight):
        reasons.append(f"free capacity ({free_slots} slots) beyond the in-flight pipeline")

    if digest.blocked:
        reasons.append(f"{len(digest.blocked)} blocked goal(s) need re-scoping")

    return ReplanSignal(should_replan=bool(reasons), reasons=tuple(reasons))
