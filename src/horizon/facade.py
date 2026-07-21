"""``Horizon`` — the strategy layer's public entry point, wiring the full Decision -> Goal -> Task loop.

horizon binds **only** to the ``dream.contracts`` strategy seam (``IntakePort`` / ``GoalStore`` /
``OutcomeFeed``) plus a ``Reasoner`` (an LLM ``complete``) — never to chorus. A consumer wires chorus's
concretes into those ports (see ``examples/chorus_bridge.py``) and a real substrate for the reasoner,
then drives the loop:

    seed_decision -> decompose (LLM) -> submit_decision -> start (listen) -> ... outcomes ... -> state

Each step is a small, independently-testable engine; the facade composes them and exposes a read model.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from horizon._ids import mint_id
from horizon.errors import HorizonError, RoadmapError, UnknownDecision, UnknownGoal
from horizon.feedback._health import HealthPolicy, staleness_health
from horizon.feedback._listener import Observer, OutcomeListener
from horizon.feedback._replan import ReplanSignal, detect_replan
from horizon.generation import (
    Analyst,
    Approvals,
    DirectionBrief,
    EvidenceBus,
    Proposal,
    ProposalStore,
    Reconciler,
    Scout,
    SourceAdapter,
    passes_evidence_gate,
)
from horizon.intake._delegated import DelegatedSubmitter
from horizon.intake._fingerprint import fingerprint
from horizon.intake._prioritiser import Prioritiser, ScorePolicy
from horizon.intake._submitter import Submitter
from horizon.model import Decision, Goal, StrategyRecord
from horizon.model._digest import RealityDigest, build_reality_digest
from horizon.model._state import DecisionState
from horizon.planning._authoring import author_goals
from horizon.planning._decomposer import Decomposer
from horizon.planning._effective_priority import EffectivePriorityPolicy, EffectiveResult
from horizon.planning._reasoner import Reasoner
from horizon.planning._roadmap import validate_roadmap
from horizon.ports import (
    CapacityPort,
    DelegatedIntakePort,
    DelegatedWorkRef,
    GoalNode,
    GoalStore,
    IntakePort,
    OutcomeEvent,
    OutcomeFeed,
    StaffingBlocked,
)
from horizon.store import DecisionStore, StrategyStore


class Horizon:
    """The strategy layer, composed over the seam ports + a reasoner + horizon's own stores."""

    def __init__(
        self,
        *,
        goals: GoalStore,
        intake: IntakePort,
        delegated_intake: DelegatedIntakePort | None = None,
        capacity: CapacityPort | None = None,
        outcomes: OutcomeFeed,
        reasoner: Reasoner | None = None,
        decisions: DecisionStore | None = None,
        strategy: StrategyStore | None = None,
        default_assignee: str | None = None,
        score_policy: ScorePolicy | None = None,
        effective_priority_policy: EffectivePriorityPolicy | None = None,
        health_policy: HealthPolicy | None = None,
        outcome_observer: Observer | None = None,
        model: str | None = None,
        decompose_context: str | None = None,
        proposals: ProposalStore | None = None,
    ) -> None:
        self._goals = goals
        self._intake = intake
        self._outcomes = outcomes
        self._decisions = decisions or DecisionStore()
        self._strategy = strategy or StrategyStore()
        self._proposals = proposals or ProposalStore()
        self._score_policy = score_policy or ScorePolicy()
        self._capacity = capacity
        self._effective_priority_policy = effective_priority_policy or EffectivePriorityPolicy(
            score_policy=self._score_policy
        )
        self._health_policy = health_policy or HealthPolicy()
        self._default_assignee = default_assignee

        self._prioritiser = Prioritiser(intake, policy=self._score_policy)
        self._submitter = Submitter(
            intake=intake,
            strategy=self._strategy,
            default_assignee=default_assignee,
            policy=self._score_policy,
        )
        self._delegated_submitter = (
            DelegatedSubmitter(
                intake=delegated_intake,
                strategy=self._strategy,
                policy=self._score_policy,
            )
            if delegated_intake is not None
            else None
        )
        self._decomposer: Decomposer | None = (
            Decomposer(
                goals=goals,
                strategy=self._strategy,
                decisions=self._decisions,
                reasoner=reasoner,
                model=model,
                context=decompose_context,
            )
            if reasoner is not None
            else None
        )
        self._listener = OutcomeListener(
            outcomes=outcomes,
            strategy=self._strategy,
            prioritiser=self._prioritiser,
            policy=self._health_policy,
            observer=outcome_observer,
        )
        self._reconciler = Reconciler(proposals=self._proposals, decisions=self._decisions)
        self._approvals = Approvals(proposals=self._proposals, promote=self._promote_proposal)
        self._evidence_bus = EvidenceBus()
        self._scout: Scout | None = Scout(reasoner=reasoner, model=model) if reasoner else None
        self._analyst: Analyst | None = Analyst(reasoner=reasoner, model=model) if reasoner else None

    # -- direction (writes) ---------------------------------------------------

    def seed_decision(self, decision: Decision) -> Decision:
        """Persist a (horizon-native) decision — the top of the spine."""
        return self._decisions.put(decision)

    def propose_roadmap(
        self,
        statement: str,
        specs: list[dict[str, object]],
        *,
        owner: str | None = None,
    ) -> Decision:
        """Author a CEO-reasoned roadmap deterministically: seed a *proposed* decision + its goals.

        The ledger's LLM-free accept-path (the deterministic mirror of :meth:`decompose`). It enforces
        the STRUCTURAL invariants (defense in depth — see :func:`horizon.planning._roadmap.validate_roadmap`)
        *before* writing anything, seeds a ``proposed`` decision, and authors the goals via the shared
        :func:`author_goals` writer. It is **author-only**: nothing reaches the intake port here —
        submission stays with :meth:`submit_decision` / on approval. Requires no reasoner. Raises
        :class:`~horizon.errors.RoadmapError` (leaving no partial writes) on any structural breach.
        """
        done_titles = [record.title for record in self._strategy.all() if record.done and record.title]
        validated = validate_roadmap(specs, done_titles=done_titles)
        decision = Decision(id=mint_id("dec"), statement=statement, status="proposed", owner=owner)
        self._decisions.put(decision)
        author_goals(
            decision,
            validated,
            goals=self._goals,
            strategy=self._strategy,
            decisions=self._decisions,
        )
        return decision

    def approve_roadmap(self, decision_id: str) -> list[str | StaffingBlocked]:
        """Approve a CEO-proposed roadmap: submit every goal to the workforce + activate the decision.

        The approval door's verb (the counterpart of :meth:`propose_roadmap`, which is author-only). It
        submits the decision's goals through the intake port (idempotent — the submitter fingerprints
        each goal and skips one already realized) and flips the decision ``proposed -> active``. A
        re-approve is a safe no-op. Raises :class:`~horizon.errors.UnknownDecision` for a missing id and
        :class:`~horizon.errors.RoadmapError` for a decision that is already ``done``/``archived``.
        """
        decision = self._decisions.get(decision_id)
        if decision is None:
            raise UnknownDecision(decision_id)
        if decision.status not in ("proposed", "active"):
            raise RoadmapError(
                f"decision {decision_id} is {decision.status!r}, not an approvable roadmap"
            )
        task_ids = self.submit_decision(decision_id)
        if decision.status != "active":
            decision.status = "active"
            self._decisions.put(decision)
        return task_ids


    def decompose(self, decision_id: str) -> list[Goal]:
        """Break a decision into goals via the LLM (requires a reasoner)."""
        if self._decomposer is None:
            raise HorizonError("Horizon was built without a reasoner; cannot decompose")
        return self._decomposer.decompose(decision_id)

    def submit_goal(self, goal: Goal) -> str | StaffingBlocked:
        """Submit one leaf goal to chorus (idempotent); returns the task id or a StaffingBlocked result."""
        return self._submit_goal(goal)

    def submit_decision(self, decision_id: str) -> list[str | StaffingBlocked]:
        """Submit every goal of a decision to chorus; returns the task ids (order preserved)."""
        decision = self._decisions.get(decision_id)
        if decision is None:
            raise UnknownDecision(decision_id)
        task_ids: list[str | StaffingBlocked] = []
        for goal_id in decision.goal_ids:
            goal = self.goal_view(goal_id)
            if goal is not None:
                task_ids.append(self._submit_goal(goal))
        return task_ids

    def _submit_goal(self, goal: Goal) -> str | StaffingBlocked:
        if goal.delivery_shape != "team":
            return self._submitter.submit(goal)
        if self._delegated_submitter is None:
            raise HorizonError("Horizon was built without delegated intake; cannot submit team goal")
        result = self._delegated_submitter.submit(goal)
        return result.root_task_id if isinstance(result, DelegatedWorkRef) else result

    # -- generation funnel (Theme C — evidence -> proposed decisions, human-gated) ------------

    def generate(
        self,
        sources: list[SourceAdapter],
        *,
        since: str | None = None,
        min_confidence: float = 0.6,
    ) -> list[Proposal]:
        """Run the funnel head->tail: collect evidence -> scout -> analyse -> gate -> reconcile.

        Reads the sources through the evidence bus (deduped), scouts candidate opportunities, has the
        analyst turn each into a brief, keeps only briefs that clear the evidence gate, and reconciles
        them into *proposed* decisions. Proposal-only — nothing reaches the live tree without approval.
        Returns the newly-created proposals. Requires a reasoner.
        """
        if self._scout is None or self._analyst is None:
            raise HorizonError("Horizon was built without a reasoner; cannot generate")
        fresh = self._evidence_bus.collect(sources, since=since)
        candidates = self._scout.survey(fresh)
        by_id = {p.id: p for p in self._evidence_bus.all()}
        briefs: list[DirectionBrief] = []
        for candidate in candidates:
            support = [by_id[i] for i in candidate.evidence_ids if i in by_id]
            brief = self._analyst.analyze(candidate, support or fresh)
            if passes_evidence_gate(brief, min_confidence=min_confidence):
                briefs.append(brief)
        return self._reconciler.reconcile(briefs)

    def reconcile(self, briefs: list[DirectionBrief]) -> list[Proposal]:
        """Fold analyst briefs into deduped, proposal-only records; returns the newly created ones."""
        return self._reconciler.reconcile(briefs)

    def list_proposals(self, *, status: str | None = "proposed") -> list[Proposal]:
        """List proposals awaiting (or past) a human decision — default: the open ones."""
        return self._approvals.list_proposals(status=status)

    def explain_proposal(self, proposal_id: str) -> str:
        """An auditable preview of what approving a proposal would create — no writes."""
        return self._approvals.explain(proposal_id)

    def approve_proposal(self, proposal_id: str, *, by: str) -> str:
        """Approve a proposal: seed a live decision from its brief, author its goals, submit them.

        The only path from a proposal to the live tree. Returns the new (live) decision id.
        """
        return self._approvals.approve(proposal_id, by=by)

    def reject_proposal(self, proposal_id: str, *, by: str, reason: str = "") -> None:
        """Close a proposal without promoting it — records who / when / why."""
        self._approvals.reject(proposal_id, by=by, reason=reason)

    def _promote_proposal(self, proposal: Proposal) -> str:
        """Turn an approved proposal into a real live decision + goals + submitted tasks."""
        if proposal.brief is None:
            raise HorizonError(f"proposal {proposal.id} has no brief to promote")
        decision = Decision(
            id=mint_id("dec"),
            statement=proposal.decision_statement,
            status="active",
            owner=self._default_assignee,
            rationale=proposal.decision_rationale,
        )
        specs = [
            {
                "title": cg.title,
                "metric": cg.metric or None,
                "target": cg.target or None,
                "rationale": cg.rationale,
                # the analyst's per-goal score when present, else the brief-level confidence
                "score": cg.score if cg.score > 0 else proposal.brief.confidence,
            }
            for cg in proposal.brief.candidate_goals
        ]
        author_goals(
            decision,
            specs,
            goals=self._goals,
            strategy=self._strategy,
            decisions=self._decisions,
        )
        self.submit_decision(decision.id)
        return decision.id

    def reprioritise(self, goal_id: str) -> str | None:
        """Re-apply a goal's current score to its task priority; returns the priority, or None."""
        record = self._strategy.get(goal_id)
        if record is None or record.task_id is None:
            return None
        return self._prioritiser.apply(record.task_id, record.score)

    def set_priority(self, goal_id: str, priority: str) -> str:
        """Set a goal's priority directly (a human/CEO override): move its score to that band + apply.

        Maps the coarse priority to a representative score (``high`` -> the high threshold, ``medium`` ->
        the medium threshold, ``low`` -> 0), writes it, and pushes it to the realizing task. Returns the
        priority set. A real strategy write — the CEO's directive lever over ranking.
        """
        record = self._strategy.get(goal_id)
        if record is None:
            raise UnknownGoal(goal_id)
        bands = {
            "high": self._score_policy.high,
            "medium": self._score_policy.medium,
            "low": 0.0,
        }
        if priority not in bands:
            raise HorizonError(f"unknown priority {priority!r}; expected high|medium|low")
        record.score = bands[priority]
        self._strategy.put(record)
        if record.task_id is not None:
            self._prioritiser.apply(record.task_id, record.score)
        return priority

    def archive_goal(self, goal_id: str) -> None:
        """Retire a goal from the active direction (a CEO override) — it stops being steered."""
        node = self._goals.get(goal_id)
        if node is not None:
            self._goals.upsert(
                GoalNode(
                    id=node.id,
                    title=node.title,
                    level=node.level,
                    status="archived",
                    parent_id=node.parent_id,
                    owner=node.owner,
                )
            )
        record = self._strategy.get(goal_id)
        if record is not None:
            record.needs_recovery = False
            record.done = False
            self._strategy.put(record)

    def sweep_staleness(self, *, now: datetime | None = None) -> list[str]:
        """Decay trust in goals verified long ago: drift stale ``on_track`` goals + resurface them.

        The drift clock made real — a goal whose last landed verdict has aged past the policy's
        ``stale_after_s`` is re-opened (``done=False``), marked ``drifting``, nudged up by ``stale_bump``
        so it resurfaces for re-verification, and re-prioritised. Returns the goal ids that drifted.
        Call it on a schedule (a cron/tick); horizon never runs its own loop.
        """
        drifted: list[str] = []
        for record in self._strategy.all():
            new_health = staleness_health(record, policy=self._health_policy, now=now)
            if new_health == record.health:
                continue
            record.health = new_health
            record.done = False
            record.score = round(min(1.0, record.score + self._health_policy.stale_bump), 4)
            self._strategy.put(record)
            if record.task_id is not None:
                self._prioritiser.apply(record.task_id, record.score)
            drifted.append(record.goal_id)
        return drifted

    def note_outcome(self, goal_id: str, *, passed: bool, diagnostic: str = "") -> None:
        """Record a terminal outcome that did NOT arrive as a bus verdict (e.g. a beat that errored).

        chorus only publishes a verdict on ``run.evaluated``; a beat that errors in the evaluate phase
        (a missing-verdict blip) leaves the task blocked with no bus signal. The composition root, which
        can read the ledger, calls this with the diagnostic it found so the failure still flows through
        the same fold — health/score/priority + the stored ``last_diagnostic`` all update uniformly.
        """
        self._listener.on_event(
            OutcomeEvent(kind="run.evaluated", goal_id=goal_id, passed=passed, detail=diagnostic)
        )

    def recover(self, *, max_attempts: int = 3) -> list[str]:
        """Re-submit failed goals, carrying the stored diagnostic into the next beat (the recovery loop).

        A goal flagged ``needs_recovery`` (a landed failure) with attempts remaining is re-opened as a
        NEW task whose intent includes *why the last attempt failed* — the diagnostic stored on the OKR
        node — so the employee sees it and the next beat is informed, not blind. Bounded by
        ``max_attempts``. Returns the re-submitted goal ids. Horizon runs no loop of its own; a consumer
        calls this each round (like ``sweep_staleness``).
        """
        recovered: list[str] = []
        for record in self._strategy.all():
            if not record.needs_recovery or record.attempts >= max_attempts:
                continue
            node = self._goals.get(record.goal_id)
            if node is None:
                continue
            intent = (
                f"{node.title}\n\n"
                f"This is retry #{record.attempts + 1}. The previous attempt did not pass. Reason:\n"
                f"{record.last_diagnostic}\n\n"
                "Your earlier work is still in your workspace — the files, scripts, data, and outputs you "
                "already produced. Review them first, keep what is correct, and build on them; do not start "
                "from scratch. Fix the specific issue above and complete the goal."
            )
            task_id = self._intake.submit(
                intent,
                assignee=node.owner or self._default_assignee,
                priority=self._score_policy.priority_for(record.score),
                goal_id=record.goal_id,
                origin_fingerprint=fingerprint(
                    record.goal_id, f"{node.title}::attempt{record.attempts + 1}"
                ),
            )
            record.task_id = task_id
            record.attempts += 1
            record.needs_recovery = False
            record.done = False
            record.health = "unknown"  # re-attempting — awaiting a fresh verdict
            self._strategy.put(record)
            recovered.append(record.goal_id)
        return recovered

    # -- back-pressure (reads / subscription) ---------------------------------

    def start(self) -> Callable[[], None]:
        """Start listening to outcomes (health + re-priority loop); returns the unsubscribe handle."""
        return self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def listener_stats(self) -> dict[str, int]:
        """The feedback listener's counters — proof the event wiring is live (handled/dropped/deferred)."""
        return {
            "handled": self._listener.handled,
            "dropped": self._listener.dropped,
            "deferred": self._listener.deferred,
        }

    def goal_view(self, goal_id: str) -> Goal | None:
        """Assemble the rich :class:`Goal` — chorus's skeleton merged with horizon's strategy record."""
        node = self._goals.get(goal_id)
        if node is None:
            return None
        record = self._strategy.get(goal_id)
        effective = self._effective_priority(record) if record is not None else None
        return Goal(
            id=node.id,
            title=node.title,
            decision_id=record.decision_id if record else None,
            parent_id=node.parent_id,
            status="done" if record and record.done else node.status,
            owner=node.owner,
            score=record.score if record else 0.0,
            health=record.health if record else "unknown",
            metric=record.metric if record else None,
            target=record.target if record else None,
            evidence=list(record.evidence) if record else [],
            task_id=record.task_id if record else None,
            root_task_id=record.root_task_id if record else None,
            task_ids=list(record.task_ids) if record else [],
            team_id=record.team_id if record else None,
            lead_id=record.lead_id if record else None,
            task_outcomes=dict(record.task_outcomes) if record else {},
            delivery_shape=record.delivery_shape if record else "single",
            lead_professions=record.lead_professions if record else (),
            staffing_requirements=record.staffing_requirements if record else (),
            effective_score=effective.score if effective else None,
            effective_priority=effective.priority if effective else None,
            priority_reason=effective.reason if effective else "",
        )

    def _effective_priority(self, record: StrategyRecord) -> EffectiveResult:
        if self._capacity is None:
            return EffectiveResult(
                score=record.score,
                priority=self._score_policy.priority_for(record.score),
                reason="capacity snapshot unavailable; raw score used",
            )
        return self._effective_priority_policy.evaluate(
            raw_score=record.score,
            requirements=record.staffing_requirements,
            capacities=self._capacity.snapshot(),
        )

    def state(self) -> list[DecisionState]:
        """The current direction: every decision with its assembled goals (the read model)."""
        states: list[DecisionState] = []
        for decision in self._decisions.all():
            goals = [
                goal
                for goal_id in decision.goal_ids
                if (goal := self.goal_view(goal_id)) is not None
            ]
            states.append(DecisionState(decision=decision, goals=goals))
        return states

    def digest(self) -> RealityDigest:
        """The deterministic reality digest the CEO plans against — no LLM.

        A bounded snapshot assembled from the read model (:meth:`state`, minus archived decisions) plus
        the optional :class:`~horizon.ports.CapacityPort` snapshot: goals grouped done / blocked /
        in_flight, a per-decision summary, a health histogram, and capacity by profession (degrading to
        ``capacity_available=False`` when no capacity port is wired).
        """
        live = [state for state in self.state() if state.decision.status != "archived"]
        capacity = self._capacity.snapshot() if self._capacity is not None else None
        return build_reality_digest(live, capacity=capacity)

    def detect_replan(self) -> ReplanSignal:
        """The deterministic re-plan signal (no LLM): should the CEO be woken to re-plan, and why.

        Folds the live reality digest (:meth:`digest`) through
        :func:`horizon.feedback._replan.detect_replan`. horizon never dispatches — the consumer turns a
        firing signal into a CEO wake, deduping so it does not re-wake while a re-plan is pending.
        """
        return detect_replan(self.digest())
