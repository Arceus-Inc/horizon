# M8 Product Report - Management, Hierarchy, and Delegation

_Acceptance completed 2026-07-13_

## Executive outcome

M8 turns a strategic goal into coordinated work for a real team without inventing a generic Manager
profession. An engineer, designer, product manager, analyst, or other specialist can lead when a human
has granted an appropriate management profile. The same person remains free to perform ordinary craft
work on a separate task.

The result is a bounded operating model across Horizon and Chorus:

1. Horizon describes the outcome, staffing needs, and strategic priority.
2. Chorus selects an eligible specialist lead or honors a valid user choice.
3. Chorus creates a durable mission Team for the goal.
4. The lead delegates only within the authority granted by the reporting line, Team, profile, and task.
5. Child owners deliver their work; the lead reacts, integrates, and accepts the combined result.
6. An independent reviewer verifies the parent outcome before it can complete.
7. Horizon folds the whole execution tree back into one strategic goal and updates its health and priority.

## What users gain

### Specialists can lead without losing their craft identity

Management is now a capability, not a profession. A specialist's role still determines their delivery
tools and standards. A separate, versioned management profile determines whether they may lead, how
deeply they may delegate, how large a Team they may coordinate, which professions they may assign, and
what spending ceiling applies.

This makes authority explicit, revocable, and auditable while preserving professional identity and work
history.

### One person can safely switch between delivery and leadership

Every task declares whether it is normal delivery work or delegation work. A delivery task exposes the
specialist's craft environment. A delegation task exposes a coordination-only environment for reading
the Team, decomposing work, assigning reports, reacting to results, and integrating the outcome.

The two modes cannot leak into each other. Holding management authority does not add management powers
to an ordinary delivery task, and a delegation task cannot conceal craft work inside the parent.

### Goals receive durable mission Teams

Each delegated root creates one mission Team with a stable identity, accountable lead, membership
history, and lifecycle. Membership is constrained to the lead's direct reports; a Team never becomes a
back door around the line organization. Nested leads create nested mission Teams from their own direct
reports.

Teams remain visible throughout delivery and are archived, not erased, after verified completion. This
preserves a clean record of who coordinated and delivered each goal.

### Delegation is least-privilege by construction

Effective authority is the narrowest intersection of company policy, the lead's profile, reporting
scope, Team membership, the parent grant, and the current task contract. A permissive layer cannot
override a restrictive one.

Nested delegation requires both a management profile and an explicit grant on the delegated child.
Peer, self, skip-level, unrelated, terminated, reviewer, over-depth, over-size, and over-budget targets
are refused before any partial work is written.

### One lead remains accountable for the combined result

Child owners own their deliverables. The delegated parent lead owns decomposition, bounded correction,
integration, and explicit acceptance of the whole result. Completion additionally requires an
independent objective gate. Exhausted correction cycles escalate for recovery rather than manufacturing
success.

This separates accountability from verification: the lead cannot approve their own integrated result.

### Strategy sees the whole outcome, not one assignee

Horizon can now request team-shaped work without naming people or designing a task graph. It records the
root task, all observed tasks, the Team, the lead, and per-task outcomes. Child results may update a
goal's health, but only the root subtree outcome can declare the goal complete.

Outcome folding is replay-safe and order-independent. Late, duplicated, or out-of-order child events do
not override an authoritative root result.

### Priority reflects the organization's ability to execute

Strategic priority now combines the raw goal score with observed load and budget headroom. Horizon
publishes both the adjusted priority and a reason, including explicit staffing or budget blockage.

This observes Chorus's existing task, run, wake, and budget facts. It does not create a competing slot or
reservation scheduler.

### Governance and migration are explicit

Profile grants, profile revocation, Team changes, delegation creation, lead acceptance, parent
verification, Team archival, and refused reorganizations are durable audit events. Authority changes are
human-governed and transactional: if the audit cannot be recorded, the authority mutation does not land.

Existing generic Manager employees have an explicit specialization path. The operator chooses the
person's real profession and grants a management profile while preserving identity and history. An
unmigrated Manager is blocked before execution with a diagnostic naming the migration action; there is
no silent conversion.

## Failure behavior

| Situation | Product behavior |
|---|---|
| No eligible specialist lead | Return a typed staffing-blocked result; create no stalled or unassigned work. |
| Unauthorized assignment or forged management call | Refuse the entire mutation with no partial children or Team changes. |
| Active-work reorganization | Block reporting, termination, or profile changes that would invalidate an active contract. |
| Child delivery failure | Mark strategy as drifting and allow one bounded, auditable corrective response. |
| Parent verification failure | Return the parent to integration; never force completion. |
| Retry, concurrent intake, or process restart | Resume or return the existing durable work; do not create duplicate roots, Teams, contracts, members, or audit events. |
| Events arrive late or out of order | Fold idempotently; the root subtree result remains authoritative. |

## Product boundaries

M8 intentionally does not add cross-line borrowing, matrix reporting, standing squads, autonomous org
changes, unlimited recursive delegation, or craft work inside a delegation parent. Those choices keep
authority understandable and make each mission Team a clear audit boundary.

## Acceptance

All eight M8 epics are implemented: shared contracts, authority persistence, execution-mode resolution,
mission Teams, authorized delegation, deterministic lead selection and adapters, Horizon aggregation
and effective priority, and migration/observability.

The difficult end-to-end scenario and full validation evidence are recorded in
[M8 Capstone Test Report](m8-capstone-test-report.md).
