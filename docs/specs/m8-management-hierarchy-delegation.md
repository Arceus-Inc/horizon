# Spec - M8: Management, Hierarchy, and Delegation

> **Scope:** v2 Theme B / milestone **M8** in [`v2-plan.md`](../v2-plan.md) - **B1 goal to
> multi-task execution** + **B3 capacity- and budget-aware prioritisation**.
> **Status:** implemented; deterministic acceptance complete, full regression evidence recorded in the
> M8 capstone report. **Cross-repo:** yes (`dream`, `chorus`,
> `horizon`). **Primary owner:** `chorus` for people, teams, authority, delegation, and execution;
> `horizon` for goals, strategic priority, and aggregated outcomes.
>
> **Core thesis:** `manager` is not a profession. An engineer, designer, PM, analyst, or other
> specialist may hold a management profile and may lead a delegation-mode task. Profession answers
> *what craft this employee practices*; management answers *what authority and accountability this
> employee has for coordinating other people*.

---

## 0. Workshop outcome

This spec records the architecture decisions made interactively on 2026-07-13. The cofounder selected a
per-goal mission Team: one durable Team is created for a delegated root and archived when that root
closes. Section 6 preserves the rejected standing-team alternative and the rationale for the decision.

### Locked decisions

| Question | Decision | Consequence |
|---|---|---|
| Is Manager a profession? | **No.** Keep specialist roles; management is composable. | Remove `manager` from the default profession registry after an explicit migration. |
| What grants management authority? | **Management profile + reporting relationships.** | A profile grants powers and limits; `reports_to` defines the people in scope. Neither alone is sufficient. |
| How does one person switch between craft and management? | **Explicit task execution mode.** | `delivery` uses the profession contract; `delegation` uses a management execution contract. |
| Permanent hierarchy vs temporary teams | **Human-governed line org + Chorus-managed teams.** | Users control `reports_to` and management profiles. Chorus forms teams only inside those boundaries. |
| Cross-line staffing in M8 | **Not allowed.** | A lead delegates only to direct reports. Cross-functional work crosses lines manager-to-manager. |
| Nested delegation | **Profile + explicit task grant.** | A report may sub-delegate only when its profile and its delegated child contract both allow it. |
| Who owns the combined result? | **The task lead.** | Child owners own deliverables; one lead owns decomposition, integration, reaction, and parent acceptance. |
| May the lead also build inside the parent task? | **No.** | A delegation-mode beat is coordination-only. The same person may do specialist work on a separate delivery task, but not hide craft work inside the parent. |
| Team persistence | **A durable `Team` entity.** | Team identity, lead, membership, and lifecycle are auditable instead of inferred from child rows. |
| Capacity | **Observe existing work; reuse existing gates.** | No second reservation/slot system. Use running/queued work and budget headroom; beats and budget gates remain authoritative. |
| Team reuse | **Lead proposes; Chorus policy validates.** | No automatic reuse and no user-only bottleneck. Reuse is checked against current hierarchy, status, load, and budget. |
| Root lead selection | **Chorus policy, with explicit user override.** | Horizon supplies needs, not employee names. A valid user-selected lead always wins. |
| Management grant shape | **A policy profile, not a boolean.** | Authority carries explicit limits: lead/subdelegate, depth, team size, professions, and optional spend. |
| Parent completion | **Lead acceptance + independent objective gate.** | Passing child tasks is necessary but not sufficient; the integrated result is independently verified. |
| Reorganisation during active work | **Blocked.** | Reporting/profile changes affecting an active delegated contract fail closed until that contract is terminal. |

### Resolved cofounder decision

**RD-1 - Team lifetime:** implement per-goal mission Teams in M8.

- **Chosen: mission team** - a durable Team is created for one delegated root and archived when its root
  contract closes.
- **Rejected: standing team** - a named reusable squad would persist across goals.

Mission Teams match the existing delegated-parent lifecycle, provide one clean authority and audit
boundary per goal, and avoid introducing a second durable org structure before cross-goal reuse is
proven. The shared tables, authority rules, task modes, delegation lifecycle, and ports remain reusable
if standing teams are revisited later.

---

## 1. Why M8 is the structural unlock

Today Horizon can choose a goal and Chorus can execute a task, but the handoff still compresses a company
into one assignee. The existing Chorus manager loop proved the hard mechanics - exact-once fan-out,
parent-waits-on-children, fresh-session reintegration, direct-report enforcement, nested depth caps, and
recovery - but packages them as a separate `manager` employee who is forbidden to practice a craft.

That model breaks down in a real company:

- an engineering lead is still an engineer;
- a design lead is still a designer;
- authority changes without changing a person's profession;
- one specialist may lead one mission and contribute as an individual on another;
- a director delegates an area to another management-capable specialist, not to a generic Manager;
- line accountability and project execution are related, but not the same graph;
- strategy should request capabilities and outcomes, not schedule named people.

M8 turns the existing walking skeleton into a company operating model:

```text
Horizon goal
    |
    | DelegatedWorkRequest (needs, priority, constraints; no schedule)
    v
Chorus lead selection
    |
    | specialist + ManagementProfile + direct-report scope
    v
Delegation-mode root task ------> durable Team
    |
    | lead decomposes and assigns direct reports
    v
delivery children + delegated area children
    |
    | each child uses its own profession + task mode
    v
lead integrates --> independent parent gate --> landed subtree outcome
    |
    v
Horizon folds the whole goal and re-prioritises the portfolio
```

The milestone succeeds when the system can run that loop without any employee whose profession is
`manager`.

---

## 2. Goals and non-goals

### Goals

- Preserve every employee's profession while making management authority composable and revocable.
- Keep permanent line hierarchy, management profiles, teams, delegation, and capacity facts in Chorus.
- Make task mode explicit so one employee can run a normal craft task and a coordination-only lead task.
- Dynamically form a team from the lead's direct reports, with no cross-line reach in M8.
- Support bounded manager-to-manager delegation through explicit nested grants.
- Keep one accountable lead for every delegated subtree.
- Give delegated parents a typed completion contract: structural closure, lead acceptance, and an
  independent objective gate.
- Replace static role-based manager tool exposure, DoD selection, and landing with authorization-aware
  task-mode resolution.
- Let Horizon submit team-shaped work without choosing people or task topology.
- Let Horizon aggregate many task outcomes into one goal and adjust effective priority using observed
  Chorus load and budget headroom.
- Preserve exact-once decomposition, bounded beats, worktree isolation, auditability, and recovery.
- Prove the result with deterministic tests, adversarial authorization tests, and a monitored live
  capstone that records every management tool call.

### Non-goals

- Chorus autonomously changing `reports_to`, promoting employees, or granting management profiles.
- Cross-line borrowing, matrix reporting, or an org-wide talent marketplace in M8.
- A lead writing code/design/content inside a delegation-mode parent beat.
- Horizon naming employees, building a task DAG, dispatching beats, or changing team membership.
- Replacing the beat scheduler with a separate capacity scheduler.
- Unlimited recursive delegation or an unbounded agent tree.
- Silently converting existing `manager` employees to engineers. Migration requires an explicit
  profession choice.
- Standing-team reuse, persistent squad membership, or shipping both Team lifetime policies in M8.

---

## 3. Existing Chorus foundation: preserve vs replace

The stale abstraction is smaller than the name suggests. Most of the current kernel is reusable.

### Preserve

| Existing seam | Why it stays |
|---|---|
| `employee.reports_to` adjacency list | Already a cycle-safe, durable chain of command used by invokability, escalation, DoD revision, and direct-report validation. |
| `CapabilityService.decompose/submit_one/reassign` | Already provides exact-once child creation, deterministic IDs, sibling dependencies, direct-child checks, and depth caps. |
| `DecomposeTool`, `SubmitTaskTool`, `AssignTaskTool` | The operations are valid management moves. Their authorization and input contracts must become task/profile/team aware. |
| `Task.parent_id`, dependency DAG, `request_depth` | Already separates task hierarchy from ordering dependencies and bounds recursive delegation. |
| `children_done` wake and park/react/integrate scheduler loop | Correct non-blocking delegation model: the lead does not hold a beat open while reports work. |
| `IntegrateContextPacket` | Correct durable fresh-session context. It should become team- and contract-aware. |
| per-employee beat serialization and org-wide run cap | The authoritative execution-capacity mechanism. |
| budget enforcer | The authoritative hard money gate. |
| worktree sync before integrate | Lets the lead inspect the assembled, landed result. |
| subtree artifact lander | Correct outcome shape for a delegated parent, once selected by task mode rather than profession. |

### Replace or generalise

| Current assumption | M8 replacement |
|---|---|
| `employee.role == "manager"` means management | `ManagementProfile` authorizes management; `Task.execution_mode == "delegation"` activates it. |
| Manager manifest statically owns delegation tools | `ExecutionProfileResolver` adds a sealed management surface only after profile + task + team authorization. |
| Manager DoD always applies to a manager employee | A persisted `DelegationContract` supplies the parent verifier independent of profession. |
| Lander selected by employee role | Lander selected by the task's persisted execution contract. |
| Director detection checks whether a report's role is `manager` | Nested delegation checks report profile + child mode + explicit `can_subdelegate` grant. |
| Team is inferred from `reports_to` and child assignees | A durable `Team` and memberships are recorded; line scope remains the authority boundary. |
| Integrate iteration cap may mechanically accept | Exhaustion escalates; it never manufactures success. Independent verification remains mandatory. |
| Horizon goal stores one `task_id` | A strategy record tracks one root and the task set/outcome evidence associated with the goal. |

---

## 4. The model: profession, authority, assignment, execution

These four concepts must remain separate.

| Concept | Stored in | Answers |
|---|---|---|
| **Profession** | `employee.role` / role plugin | What craft can this employee perform? |
| **Management authority** | `management_profile` + `reports_to` | May this employee lead, and who is inside the authority scope? |
| **Team assignment** | `team` + `team_member` | Which durable delivery group is attached to this work? |
| **Execution contract** | `task.execution_mode` + `delegation_contract` | Is this task craft delivery or coordination, and what must pass? |

No field is allowed to stand in for another. In particular:

- direct reports do not automatically grant management tools;
- a management profile does not permit reaching outside the reporting line;
- team membership does not change `reports_to`;
- profession does not determine whether the current task may delegate;
- creating child rows does not retroactively change a delivery task into a delegation task.

---

## 5. Chorus data model

### 5.1 Employee remains a specialist

`Employee.role` continues to name a registered specialist plugin (`engineer`, `designer`, `pm`,
`analyst`, `marketer`, and so on). No `manager` profession is required by the new runtime.

The role plugin remains the source of the delivery contract:

```text
profession role = delivery prompt + craft tools + delivery DoD + delivery outcome lander
```

An employee may hold no management profile, an inactive profile, or one active profile. Profile changes
are human-governed and audited.

### 5.2 `ManagementProfile`

New Chorus-owned row, keyed by employee:

| Field | Type | Meaning |
|---|---|---|
| `employee_id` | `str` PK/FK | The specialist receiving management authority. |
| `active` | `bool` | Master grant switch. Inactive profiles authorize nothing. |
| `can_lead` | `bool` | May own a root delegation-mode task. |
| `can_subdelegate` | `bool` | May own a nested delegation-mode child when explicitly granted. |
| `max_delegation_depth` | `int` | Profile ceiling, additionally bounded by the global request-depth cap. |
| `max_team_size` | `int` | Maximum active members this lead may coordinate for one team. |
| `allowed_professions` | `tuple[str, ...]` | Direct-report professions this lead may assign; empty means any non-review-only deliverer. |
| `spend_limit_cents` | `int | None` | Optional management-scope ceiling; existing employee/company budget gates still apply. |
| `version` | `int` | Monotonic policy revision pinned into new delegation contracts. |
| `granted_by_user_id` | `str` | Human authority that granted or changed the profile. |
| `created_at/updated_at` | timestamps | Audit and replay. |

`ManagementProfile` is policy, not identity. It never changes the employee's role manifest globally.

### 5.3 Line hierarchy

`employee.reports_to` remains the canonical line graph. Existing invariants continue:

- no self-edge;
- no cycle;
- every referenced manager exists;
- a broken or terminated ancestor makes a report uninvokable;
- recovery escalates up this chain;
- M8 delegation targets direct reports only.

M8 adds an active-contract guard. Any operation that changes `reports_to`, terminates an affected
employee, or deactivates/weakens a pinned management profile checks for active delegation contracts in
the affected line. If any exist, it raises `ActiveDelegationConflict` and writes no partial change.

This is intentionally strict. Emergency forced reorganisation is a future governance feature, not a
hidden bypass in M8.

### 5.4 Durable `Team`

The selected mission-Team policy uses these durable fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | `str` | Stable team identity. |
| `name` | `str` | Human-readable name. |
| `lead_employee_id` | `str` | Accountable specialist lead. Must have an active profile. |
| `goal_id` | `str | None` | Goal association; required for mission teams, optional for standing teams. |
| `parent_team_id` | `str | None` | Nested area team created by a sub-delegating lead. |
| `status` | `forming | active | blocked | archived` | Team lifecycle. |
| `policy_version` | `int` | Team policy used to create or validate it. |
| `created_by` | `str` | Lead/user/policy provenance. |
| timestamps | | Creation, activation, and archival trail. |

`TeamMember` records are not reporting edges:

| Field | Type | Meaning |
|---|---|---|
| `team_id` + `employee_id` | composite key | One durable membership. |
| `membership_role` | `lead | member` | Team responsibility, not profession. |
| `can_subdelegate` | `bool` | Explicit per-team grant; effective only with a compatible profile. |
| `source_manager_id` | `str` | The direct manager whose line scope authorized membership. |
| `joined_at/left_at` | timestamps | Full membership history. |

In M8, every active non-lead member must be a direct report of the team's lead. A nested lead forms a
child team from that nested lead's direct reports. No team row may be used to bypass the line graph.

### 5.5 Explicit task execution mode

Add a required enum with a safe default:

```python
class ExecutionMode(StrEnum):
    DELIVERY = "delivery"      # profession contract
    DELEGATION = "delegation"  # coordination-only management contract
```

New tasks default to `delivery`. Horizon's team intake explicitly creates a `delegation` root. A nested
area child is `delegation` only when the parent lead deliberately grants it; all other children are
`delivery`.

Add to `Task` and its persistence:

| Field | Type | Meaning |
|---|---|---|
| `execution_mode` | `ExecutionMode` | Stable task behavior; never inferred from whether children happen to exist. |
| `team_id` | `str | None` | Team executing the task; required for delegation mode. |

### 5.6 Persisted `DelegationContract`

One row per delegation-mode task freezes the authority and completion semantics used for replay:

| Field | Meaning |
|---|---|
| `task_id` | Delegated parent task. |
| `team_id` | Durable team. |
| `lead_employee_id` | Must equal the task's employee assignee. |
| `management_profile_version` | Profile version authorized at creation. |
| `parent_contract_task_id` | Parent delegation contract for a nested area; null at root. |
| `can_subdelegate` | Explicit task-level grant, intersected with the profile. |
| `max_depth/max_team_size/spend_limit_cents` | Pinned effective limits (minimum of global, profile, parent, and request). |
| `objective_rubric` | What the integrated parent must accomplish. |
| `status` | `forming | delegated | integrating | verifying | done | blocked`. |
| `accepted_run_id/accepted_at` | Lead's explicit acceptance evidence. |

The effective authority is always the intersection:

```text
global policy
  intersect management profile
  intersect reporting scope
  intersect team membership
  intersect parent delegation contract (when nested)
  intersect current task contract
```

Any missing layer fails closed.

---

## 6. Team lifetime decision

Both proposals use the same `Team`, `TeamMember`, `DelegationContract`, tool, and scheduler interfaces.
Only the `TeamPolicy` implementation differs.

### Rejected alternative - reusable standing teams

**Definition.** A Team is a named squad that survives individual goals. Membership changes are deliberate;
new delegated goals select an existing eligible team.

**Flow**

1. A user establishes the line org and standing team.
2. Chorus selects an eligible lead for a new goal.
3. The lead proposes an existing team.
4. `StandingTeamPolicy.validate_for_goal` rechecks lead, direct-report membership, active status,
   professions, observed load, and budget.
5. The goal creates a new delegation contract against that team; the team itself remains active after
   completion.

**Strengths**

- stable team memory, norms, and identity;
- less repeated team formation work;
- easier capacity and portfolio reporting by squad;
- natural fit for product/engineering squads that own an area over time.

**Costs / risks**

- staffing is less dynamic;
- stale membership needs explicit maintenance;
- a standing team may become a second org chart unless line-vs-team semantics stay strict;
- selecting a whole team can queue work behind overloaded members.

### Selected policy - per-goal mission teams

**Definition.** A Team is created for one delegated root goal, remains durable for audit/replay, and is
archived when its root contract closes.

**Flow**

1. Chorus selects an eligible lead.
2. A forming team is created with the lead.
3. The lead decomposes and chooses direct reports from the policy-filtered roster.
4. The exact-once decomposition transaction adds memberships and child tasks together.
5. The team remains active through integration and verification, then archives with the parent outcome.

**Strengths**

- team composition follows the work;
- no long-lived membership drift;
- clean one-goal audit boundary;
- matches dynamic company operation and the current parent-task lifecycle.

**Costs / risks**

- repeated formation cost and more team rows;
- weaker durable team identity and memory;
- follow-up goals need explicit reuse logic;
- frequent reshuffling may reduce coherence.

### Decision matrix

| Criterion | Standing team | Mission team |
|---|---:|---:|
| Stable identity / memory | Strong | Weak unless linked to prior teams |
| Dynamic staffing | Moderate | Strong |
| Simple goal audit | Moderate | Strong |
| User control | Strong | Policy-led |
| Risk of duplicate org structure | Higher | Lower |
| Fit with current manager loop | Moderate | Strong |

**Implementation decision:** Slice 4 MUST implement `MissionTeamPolicy` only. Standing-team reuse,
cross-goal membership maintenance, and persistent squad memory remain deferred.

---

## 7. Execution profile resolution

The current factory resolves a beat entirely from `employee.role`. M8 resolves from profession plus the
task's persisted contract:

```text
ExecutionProfileResolver.resolve(employee, task)
    |
    +-- task.mode == delivery
    |      -> existing profession manifest + profession DoD + profession lander
    |
    +-- task.mode == delegation
           -> verify active ManagementProfile pinned by DelegationContract
           -> verify employee is contract lead and team lead
           -> verify team membership and reporting scope
           -> sealed management prompt/tools/memory posture
           -> DelegatedSubtree verifier + subtree lander
```

This is **not** the existing generic role overlay rule. A management surface widens beyond an engineer's
craft tools, so it may only be constructed by the trusted resolver after authorization. Callers cannot
request it by naming tools.

### Delivery mode

Unchanged behavior. An engineer still gets engineer tools, reviewed-build DoD, and PR lander. A designer
still gets design tools, design DoD, and design artifact lander. Holding a management profile changes
nothing.

### Delegation mode

Coordination-only behavior:

- read the goal, team, roster, child outcomes, and integrated workspace;
- call `decompose` once on kickoff;
- on integrate, accept or make one bounded `submit_task` / `assign_task` reaction;
- no craft write/run tools from the profession manifest;
- team memory scope;
- subtree outcome kind;
- independent parent verification after lead acceptance.

The management brief becomes profession-neutral. It says "You are the accountable lead" rather than
"You are an engineering manager" and receives the lead's profession only as context.

### First vertical proof

One management-capable engineer receives two tasks:

1. a `delivery` task - exact existing engineer tools, DoD, and PR lander;
2. a `delegation` task - only management tools, delegated verifier, and subtree lander.

If either contract leaks into the other, M8's core hypothesis is false and the slice does not proceed.

---

## 8. Delegation lifecycle

### 8.1 Root intake and lead selection

Horizon submits a typed delegated-work request containing the goal, outcome constraints, requested
professions, strategic priority, and optional preferred lead. It does not name a team or task DAG.

Chorus `LeadSelector`:

1. If a user supplied `preferred_lead`, validate it; a valid override wins.
2. Otherwise consider only invokable specialists with active profiles and `can_lead=True`.
3. Require a direct-report line capable of covering the requested professions.
4. Exclude hard budget-blocked candidates.
5. Rank deterministically by profession fit, required-report coverage, lower observed work load, greater
   budget headroom, then employee id as a stable tie-break.
6. Create the delegation root, Team association, and contract atomically/idempotently on the request
   fingerprint.

No eligible lead means a typed `staffing_blocked` result, not an unassigned task that silently stalls.

### 8.2 Kickoff

The lead's fresh delegation beat receives:

- parent intent and objective rubric;
- management limits;
- direct reports filtered by status, allowed profession, and team policy;
- each report's observed load and budget state;
- mission-Team formation state and the legal direct-report roster;
- the global and remaining delegation depth.

The lead chooses the task shape and assignees, then calls `decompose` exactly once. Chorus validates the
whole proposed wave before writing any child.

Each child declares:

```text
label + intent + assignee + depends_on + execution_mode
```

Rules:

- `delivery` is the default;
- `delegation` requires the assignee to be a direct report with an active profile,
  `can_subdelegate=True`, and an explicit team/task subdelegation grant;
- the lead cannot assign a child to themselves;
- a read-only reviewer cannot own a deliverable child;
- the full wave must fit team-size/depth/spend limits;
- child and membership writes share the exact-once decomposition transaction;
- no partial team or partial wave survives a rejection.

After creation, the parent parks and releases its beat. Children run independently through the existing
scheduler.

### 8.3 Nested delegation

A delegated area child creates a child `DelegationContract` and child Team linked to the parent Team.
The nested lead may choose only their own direct reports. Effective depth and spend are narrowed from the
parent contract; they can never be reset or widened at the child.

This replaces role-string director logic. A director is simply a lead whose authorized child is another
management-capable specialist running a delegation-mode task.

### 8.4 Integration and acceptance

When all direct children are terminal, `children_done` wakes the lead. The integration packet includes:

- Team and contract identity;
- parent objective and lead acceptance history;
- each child mode, status, DoD, artifact, latest outcome, and blockers;
- nested subtree summaries;
- current observed load for legal reroutes;
- a kernel recommendation: `accept` or `react`.

The lead may do exactly one of:

- **accept** the assembled result;
- `submit_task` one required corrective child;
- `assign_task` one unfinished/rejected direct child to another legal team member.

Acceptance moves the contract to `verifying`; it does not finish the task. An independent typed parent
gate then evaluates the integrated result against `objective_rubric` in the assembled workspace:

```text
all required descendants passed
    AND lead explicitly accepted
    AND independent objective verifier passed
        -> land subtree artifact -> root done
```

A failed objective gate returns the contract to `integrating`, records evidence, and wakes the lead to
react. The same bounded integrate iteration counter remains, but exhaustion opens recovery/human
escalation. It never force-accepts or manufactures a passing outcome.

### 8.5 Reorganisation guard

While a contract is non-terminal:

- changing `reports_to` for its lead or active members is refused;
- terminating those employees is refused;
- deactivating or narrowing the pinned management profile is refused;
- changing standing-team membership that would invalidate the contract is refused.

The operation returns the blocking contract/team/task ids so the user can finish, cancel, or explicitly
resolve the work first.

---

## 9. Management tools and authority

Tool names may remain stable; semantics become generic and authorization-aware.

| Tool | Phase | Purpose | Required authority |
|---|---|---|---|
| `team_read` | kickoff/integrate | Read team candidates/members, legal direct reports, load, budget, and limits. | Contract lead; read-only. |
| `decompose` | kickoff only | Atomically form/select the team and create the first child wave. | Root/nested lead; profile + contract + reporting scope. |
| `submit_task` | integrate only | Add one corrective child. | Contract lead; same limits as decomposition. |
| `assign_task` | integrate only | Reroute one direct non-terminal child to a legal team member. | Contract lead; direct-child + direct-report checks. |

Required service checks on every mutation:

1. Beat employee equals task assignee and contract lead.
2. Task is `delegation` mode and contract is active in the expected phase.
3. Pinned management profile exists and authorizes the operation.
4. Team exists, lead matches, and membership is active.
5. Target is a direct report and allowed by profile/team/task policy.
6. Nested delegation grant and depth are valid when requested.
7. Child/task state permits the operation.
8. Idempotency key has not already committed a different mutation.

Prompt discipline is never an authorization boundary. Illegal tools are absent from the harness, and the
service independently rejects forged or stale calls.

---

## 10. Shared contracts in Dream

No sibling imports are introduced. Cross-repo DTOs and Protocols live in `dream.contracts`.

### 10.1 Delegated intake

Add a focused contract rather than making Horizon depend on Chorus workforce types:

```python
@dataclass(frozen=True)
class StaffingRequirement:
    profession: str
    count: int = 1


@dataclass(frozen=True)
class DelegatedWorkRequest:
    intent: str
    goal_id: str
    priority: Priority = "medium"
    requirements: tuple[StaffingRequirement, ...] = ()
    preferred_lead: str | None = None      # explicit user override only
    max_team_size: int | None = None
    spend_limit_cents: int | None = None
    origin_fingerprint: str = ""


@dataclass(frozen=True)
class DelegatedWorkRef:
    root_task_id: str
    team_id: str
    lead_id: str


class DelegatedIntakePort(Protocol):
    def submit_delegated(self, request: DelegatedWorkRequest) -> DelegatedWorkRef: ...
```

This port is direction, not scheduling: it creates one durable root assignment through Chorus policy.
Every child and dependency remains Chorus-owned.

### 10.2 Capacity read model

Capacity reuses existing runtime facts; it does not reserve slots:

```python
@dataclass(frozen=True)
class ProfessionCapacity:
    profession: str
    eligible: int
    running: int
    assigned_nonterminal: int
    queued_wakes: int
    budget_blocked: int
    budget_headroom_cents: int | None


class CapacityPort(Protocol):
    def snapshot(self) -> tuple[ProfessionCapacity, ...]: ...
```

The composition-root adapter derives this from Chorus tasks, runs, wakes, workforce, and cost/budget
rows. Horizon sees aggregate capacity, not org internals or employee names.

### 10.3 Outcome hierarchy

Extend `OutcomeEvent` additively with optional hierarchy fields:

- `parent_task_id`;
- `root_task_id`;
- `team_id`;
- `execution_mode`;
- `is_root_outcome`.

Existing single-task events remain valid with defaults. The adapter populates the hierarchy from Chorus
ledger state.

---

## 11. Horizon changes

### 11.1 Goal execution shape

The decomposer may mark a leaf goal as:

```text
delivery_shape = single | team
staffing_requirements = [(profession, count), ...]
```

`single` keeps the existing `IntakePort`. `team` uses `DelegatedIntakePort`. Horizon specifies desired
capabilities and outcome constraints, never a task list.

### 11.2 Strategy record

Replace the one-task ceiling with explicit root and evidence tracking:

| Field | Meaning |
|---|---|
| `root_task_id` | The single Chorus root representing the goal. |
| `task_ids` | Every observed descendant task id for evidence/debugging. |
| `team_id` | Durable execution team reference. |
| `lead_id` | Read-only attribution from Chorus selection; Horizon does not mutate it. |
| `task_outcomes` | Latest outcome summary per task. |

Keep a compatibility accessor for `task_id` during migration, returning `root_task_id`.

### 11.3 Outcome fold

Child events enrich health evidence but do not independently close the strategic goal.

- any hard-blocked required child -> goal `blocked`;
- failed/rejected child while the root remains active -> goal `drifting` or `blocked` by policy;
- all child passes without root verification -> still active;
- only a passing root subtree outcome -> goal `done`;
- root recovery/human escalation -> goal `blocked` with the root evidence.

The fold is idempotent by event/task identity and handles out-of-order child/root events.

### 11.4 B3 effective priority

Raw strategic score remains Horizon-owned. Capacity and budget alter **effective** priority, not the
underlying value judgment.

Initial policy inputs:

- required professions from the goal;
- eligible lead/team coverage from `CapacityPort`;
- running plus assigned non-terminal load;
- queued wakes;
- budget-blocked headcount and budget headroom;
- dependency readiness.

The report must show both values and a reason:

```text
raw score 0.86 -> effective high
capacity: 1 eligible lead; engineer load 2 active / 3 assigned; budget healthy
```

No capacity means a visible `staffing_blocked` state, not silent low priority. The exact numeric weighting
is a policy object with table-driven tests; it is not embedded in the adapter.

---

## 12. Migration from the stale Manager employee

### 12.1 No silent profession guess

An existing `role="manager"` row does not reveal whether the person is fundamentally an engineer,
designer, PM, or something else. Migration therefore requires an explicit map:

```text
chorus workforce specialize-manager <employee_id> --profession engineer --profile <policy>
```

The transaction:

1. validates the target profession plugin;
2. rejects active work until it is resolved;
3. updates the employee profession;
4. creates the management profile;
5. preserves employee id, reporting edges, budgets, memory, history, and audit lineage.

### 12.2 Package changes

- Extract the profession-neutral management brief, verifier, lander selection, and profile resolver from
  `chorus_employee/manager` into Chorus management modules.
- Keep model-callable tools in `chorus_tools`; rename comments/types from manager-specific to lead/
  delegation terminology where public behavior is unchanged.
- Remove `manager_plugin()` from `default_roles()` only after every fixture/example and live org has an
  explicit migration path.
- Retain a fail-fast compatibility diagnostic for unmigrated `role="manager"` rows; do not run them under
  an ambiguous default profession.
- Replace tests that hire a Manager with specialist + profile + reports.
- Replace `role == "manager"` director checks with management-profile and delegation-contract checks.

### 12.3 Backward compatibility

- Existing delivery tasks default to `execution_mode="delivery"`.
- Existing decomposed tasks are migrated to a delegation contract only when their assignee is explicitly
  mapped and the tree is internally consistent; otherwise migration reports them for manual resolution.
- Existing `IntakePort` remains unchanged for single-person work.
- Existing Horizon `task_id` reads continue through the compatibility accessor during one deprecation
  window.

---

## 13. Failure modes and invariants

| Failure | Required behavior |
|---|---|
| Specialist has direct reports but no profile | No management tools; delegated intake cannot select them. |
| Specialist has profile but no legal reports | Not eligible to lead requested team work. |
| Delivery task tries to call `decompose` | Tool absent; service also rejects forged calls. |
| Delegation task assigned to unprofiled employee | Intake/assignment fails atomically. |
| Lead assigns outside direct reports | Entire wave refused; no child/team partial writes. |
| Lead assigns themselves | Refused in M8. |
| Nested child lacks both grants | Forced to delivery or refused; never silently delegates. |
| Depth/team/spend limit exceeded | Refuse before fan-out; parent remains visible and recoverable. |
| Two retries repeat decomposition | Deterministic claim reuses the same Team/members/children. |
| Report is overloaded | Visible in roster and capacity snapshot; assignment may queue under existing beats. |
| Budget becomes exhausted | Existing budget gate withholds beats; root surfaces blocked capacity evidence. |
| Child fails independent DoD | Child becomes rejected/blocked; lead receives integrate/react wake. |
| All children pass but integrated goal fails | Parent remains non-terminal; lead reacts to independent gate evidence. |
| Integrate iteration cap reached | Escalate/recovery; never force pass. |
| Reorg touches active contract | `ActiveDelegationConflict`; no org mutation. |
| Root event arrives before child events | Horizon folds idempotently; root is authoritative for completion. |
| Process crashes mid-team creation | Exact-once claim resumes or rolls back; no duplicate Team/task wave. |

Non-negotiable invariants:

1. Every delegated task has exactly one accountable lead and one active delegation contract.
2. Every lead is a registered specialist with an active compatible management profile.
3. Every M8 child assignee is the lead's direct report; Team never widens line authority.
4. Every delegation mutation is authorized by profile, line, team, parent contract, and task contract.
5. Delivery and delegation execution surfaces never coexist in one parent beat.
6. Parent completion requires descendant closure, lead acceptance, and independent verification.
7. Strategy does not schedule; execution does not rewrite strategic intent.
8. Beats and existing budget gates remain the only hard runtime capacity controls.
9. Every fan-out and retry is exact-once and audit-visible.
10. No bounded-loop escape path may claim success without the objective gate.

---

## 14. Build plan

### Slice 0 - contracts and characterization

**Purpose:** pin current behavior before changing identity.

- Add characterization tests for the existing park/react/integrate loop, depth cap, direct-report guard,
  and exact-once claims.
- Add the first vertical test scaffold: one engineer identity, one delivery task, one future delegation
  task.
- Add Dream DTO/Protocol contract tests for delegated intake, capacity, and hierarchy outcome fields.
- Record RD-1 and characterize the mission-Team lifecycle boundary.

**Exit:** current manager loop is fully characterized; new contracts are additive and import-cycle free.

### Slice 1 - Chorus authority model

- Add `ManagementProfile`, repository, migrations, facade/query APIs, audit events, and human-only mutation
  boundary.
- Add `ExecutionMode` to Task with `delivery` default.
- Add `DelegationContract` and active-contract reorganisation guards.
- Add `Team`/`TeamMember` common persistence without choosing lifetime behavior.
- Add model/property tests for cycles, profile limits, pinning, and reorg conflicts.

**Exit:** Chorus can represent the model but does not yet expose management tools to specialists.

### Slice 2 - execution profile resolver

- Introduce `ExecutionProfileResolver` used by runner, DoD, lease/policy, and lander resolution.
- Materialize a sealed management surface for authorized delegation tasks.
- Generalise the manager brief and roster packet to lead/team terminology.
- Replace static role-based manager tool registration.
- Prove the same engineer gets exact delivery behavior on one task and exact management behavior on the
  other.

**Exit:** `manager` role is no longer required to run the management harness.

### Slice 3 - authorized delegation lifecycle

- Extend child plan with explicit execution mode.
- Enforce actor, profile, line, Team, nested grant, depth, team-size, and spend checks atomically.
- Persist child contracts/teams for nested delegation.
- Generalise integrate packet and director logic.
- Add independent subtree verification and replace force-accept-at-cap with escalation.
- Preserve exact-once creation and one bounded mutation per integrate beat.

**Exit:** specialist leads execute one- and multi-level delegated trees safely.

### Slice 4 - mission Team policy

- Implement `MissionTeamPolicy` to create/form/archive one Team per delegated root.
- Add current-policy validation for lead, direct-report membership, status, load, and budget.
- Keep standing-team selection, cross-goal reuse, and long-lived membership maintenance out of M8.

**Exit:** the mission Team lifecycle is explicit, tested, and observable.

### Slice 5 - lead selection and shared adapter

- Add deterministic Chorus `LeadSelector` with user override.
- Implement composition-root `DelegatedIntakePort` adapter.
- Return typed `staffing_blocked` failures.
- Add `team_read` and capacity-enriched roster context.

**Exit:** a team-shaped goal can enter Chorus without Horizon naming a person.

### Slice 6 - Horizon B1 aggregation

- Add `delivery_shape` and staffing requirements to goal/decomposer output.
- Add `root_task_id`, task set, Team/lead attribution, and per-task outcomes to strategy records.
- Route single goals through existing intake and team goals through delegated intake.
- Fold child evidence while making the passing root outcome authoritative for completion.
- Update direction/governance/report views.

**Exit:** one strategic goal truthfully represents a multi-person execution tree.

### Slice 7 - B3 observed capacity and budget

- Implement Chorus capacity projection from existing tasks/runs/wakes/budgets.
- Implement `CapacityPort` adapter.
- Add Horizon effective-priority policy and reason strings.
- Surface staffing/budget blocks without creating a second scheduler or reservation system.

**Exit:** strategic ordering reflects the org's actual ability to take work now.

### Slice 8 - migration, observability, and removal

- Add explicit Manager specialization migration and diagnostics.
- Remove `manager_plugin` from defaults after fixtures and examples migrate.
- Add org + Team + task-tree inspection views and CLI/report surfaces.
- Add activity verbs for profile grants, Team lifecycle, delegation grants, lead acceptance, verification,
  and reorg refusal.
- Update docs and the Horizon roadmap terminology from "the manager" to management/hierarchy/delegation.

**Exit:** no production path or default test fixture depends on `role="manager"`.

---

## 15. Verification strategy

### Unit and property tests

- `ManagementProfile` validation and version pinning.
- org cycle/self-edge/unknown-manager invariants remain green.
- active-contract reorg refusal is atomic.
- Team lead/member hierarchy invariants.
- effective authority intersection never widens parent/global limits.
- lead selection deterministic tie-break and explicit override.
- capacity projection from running, assigned, queued, and budget facts.
- Horizon out-of-order multi-task fold and root-authoritative completion.

### Authorization/adversarial tests

- profiled employee on a delivery task cannot see/call management tools;
- unprofiled employee on a forged delegation task is refused;
- lead cannot assign a peer, skip-level report, self, reviewer, terminated report, or unrelated Team
  member;
- nested lead without either profile or task grant cannot decompose;
- stale profile version/team membership cannot mutate an active contract;
- forged BeatContext actor cannot act for the real lead;
- repeated tool calls are idempotent and do not duplicate membership or tasks.

### Scheduler lifecycle tests

- specialist lead kickoff -> park -> children run -> integrate -> independent verify -> subtree done;
- delivery and delegation tasks for the same employee resolve different contracts;
- failed/rejected child wakes lead to react;
- nested specialist lead delegates an area and rolls up to the root;
- independent parent failure prevents completion after every child passed;
- integrate cap escalates rather than force-accepting;
- crash/retry at each write boundary resumes exactly once;
- existing per-employee beat serialization and budget gates remain unchanged.

### Cross-repo contract tests

- Dream Protocol runtime conformance for both adapters;
- Horizon never imports Chorus;
- delegated request idempotency returns the same root/Team/lead;
- child and root outcome hierarchy survives adapter mapping;
- capacity snapshot contains no employee scheduling controls;
- goal remains active until the root subtree outcome passes.

### Regression scope

- full Chorus workforce, lifecycle, heartbeat, harness, outcome, recovery, governance, and observability
  suites;
- full Dream contract/tool projection suite;
- full Horizon intake, feedback, health, recovery, governance, and report suites;
- known unrelated failures remain documented rather than being fixed opportunistically.

---

## 16. Live capstone: a real company loop

The milestone is not accepted on unit tests alone. Run a unique-company live probe and a full capstone.

### Org

- no employee with profession `manager`;
- one management-capable specialist root lead;
- at least two direct reports with different professions;
- one management-capable report with their own direct reports for nested delegation;
- one reviewer/independent verifier outside deliverable ownership.

### Scenario

1. CEO approves a Horizon decision.
2. Horizon creates a team-shaped goal with profession requirements and no named assignee.
3. Chorus selects the lead (then a second run proves explicit user override).
4. Lead forms/selects a Team and delegates whole areas.
5. Nested specialist lead sub-delegates one area.
6. Delivery children land profession-specific artifacts.
7. One injected child failure forces a bounded lead reaction.
8. Root lead accepts the assembled result.
9. Independent parent verification passes only after the corrective work.
10. Horizon folds the root subtree outcome and shows raw vs effective priority with capacity reasoning.

### Monitor every action

Capture and assert:

- every beat/run/wake and employee identity;
- every tool offered per task mode;
- every management tool input/result;
- every Team/member/contract/task/dependency write;
- every direct-report/profile/team authorization decision;
- every DoD and independent parent verdict;
- every worktree sync/landing result;
- every capacity and budget input used for prioritisation;
- every Horizon outcome fold and state transition;
- zero hard tool-manifest errors, unauthorized successful mutations, duplicate children, orphan tasks,
  unresolved active contracts, or false-positive root completions.

Repeat the probe enough times to expose model variance. A single successful run is demonstration, not
reliability evidence.

---

## 17. Definition of done

M8 is complete when all of the following are true:

- [ ] The same specialist identity can execute delivery and delegation tasks with no contract leakage.
- [ ] No default workforce role named `manager` is required at runtime.
- [ ] Management authority is explicit, bounded, versioned, human-governed, and audited in Chorus.
- [ ] Team identity and membership are durable and cannot widen the line hierarchy.
- [ ] Root and nested delegation are exact-once, direct-report scoped, and depth bounded.
- [ ] A delegation lead cannot perform hidden craft work inside the parent beat.
- [ ] Parent completion requires lead acceptance and independent objective verification.
- [ ] Integration-loop exhaustion escalates and never force-passes.
- [ ] Active delegated work blocks affected reorganisation atomically.
- [ ] Horizon submits capabilities/constraints rather than people/task topology.
- [ ] Horizon tracks and folds a multi-task goal without closing on child completion alone.
- [ ] Capacity uses existing beat/task/budget facts and introduces no parallel runtime scheduler.
- [ ] Raw and effective priority plus the capacity/budget reason are observable.
- [ ] The stale Manager migration is explicit and preserves identity/history.
- [ ] Deterministic, adversarial, crash/retry, cross-repo, and repeated live tests pass.

---

## 18. Cofounder decision record

```text
Decision: Team lifetime
Chosen: mission team
Why: It matches the delegated-root lifecycle, gives each goal a clean authority and audit boundary, and avoids a second durable org structure in M8.
Rejected alternative: standing team
Required changes to this spec: Implement MissionTeamPolicy in Slice 4; defer standing-team reuse and persistent squad membership.
Approved by: cofounder
Date: 2026-07-13
```

The selected policy does not change the shared management core: management as a capability, explicit
task modes, profile and line authority, durable Team primitives, delegation contracts, execution
resolution, and the specialist-lead lifecycle remain policy-independent.