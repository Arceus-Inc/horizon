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

from horizon.errors import HorizonError, UnknownDecision
from horizon.feedback._health import HealthPolicy, staleness_health
from horizon.feedback._listener import Observer, OutcomeListener
from horizon.intake._prioritiser import Prioritiser, ScorePolicy
from horizon.intake._submitter import Submitter
from horizon.model import Decision, Goal
from horizon.model._state import DecisionState
from horizon.planning._decomposer import Decomposer
from horizon.planning._reasoner import Reasoner
from horizon.ports import GoalStore, IntakePort, OutcomeFeed
from horizon.store import DecisionStore, StrategyStore


class Horizon:
    """The strategy layer, composed over the seam ports + a reasoner + horizon's own stores."""

    def __init__(
        self,
        *,
        goals: GoalStore,
        intake: IntakePort,
        outcomes: OutcomeFeed,
        reasoner: Reasoner | None = None,
        decisions: DecisionStore | None = None,
        strategy: StrategyStore | None = None,
        default_assignee: str | None = None,
        score_policy: ScorePolicy | None = None,
        health_policy: HealthPolicy | None = None,
        outcome_observer: Observer | None = None,
        model: str | None = None,
    ) -> None:
        self._goals = goals
        self._intake = intake
        self._outcomes = outcomes
        self._decisions = decisions or DecisionStore()
        self._strategy = strategy or StrategyStore()
        self._score_policy = score_policy or ScorePolicy()
        self._health_policy = health_policy or HealthPolicy()

        self._prioritiser = Prioritiser(intake, policy=self._score_policy)
        self._submitter = Submitter(
            intake=intake,
            strategy=self._strategy,
            default_assignee=default_assignee,
            policy=self._score_policy,
        )
        self._decomposer: Decomposer | None = (
            Decomposer(
                goals=goals,
                strategy=self._strategy,
                decisions=self._decisions,
                reasoner=reasoner,
                model=model,
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

    # -- direction (writes) ---------------------------------------------------

    def seed_decision(self, decision: Decision) -> Decision:
        """Persist a (horizon-native) decision — the top of the spine."""
        return self._decisions.put(decision)

    def decompose(self, decision_id: str) -> list[Goal]:
        """Break a decision into goals via the LLM (requires a reasoner)."""
        if self._decomposer is None:
            raise HorizonError("Horizon was built without a reasoner; cannot decompose")
        return self._decomposer.decompose(decision_id)

    def submit_goal(self, goal: Goal) -> str:
        """Submit one leaf goal to chorus (idempotent); returns the task id."""
        return self._submitter.submit(goal)

    def submit_decision(self, decision_id: str) -> list[str]:
        """Submit every goal of a decision to chorus; returns the task ids (order preserved)."""
        decision = self._decisions.get(decision_id)
        if decision is None:
            raise UnknownDecision(decision_id)
        task_ids: list[str] = []
        for goal_id in decision.goal_ids:
            goal = self.goal_view(goal_id)
            if goal is not None:
                task_ids.append(self._submitter.submit(goal))
        return task_ids

    def reprioritise(self, goal_id: str) -> str | None:
        """Re-apply a goal's current score to its task priority; returns the priority, or None."""
        record = self._strategy.get(goal_id)
        if record is None or record.task_id is None:
            return None
        return self._prioritiser.apply(record.task_id, record.score)

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

    # -- back-pressure (reads / subscription) ---------------------------------

    def start(self) -> Callable[[], None]:
        """Start listening to outcomes (health + re-priority loop); returns the unsubscribe handle."""
        return self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def goal_view(self, goal_id: str) -> Goal | None:
        """Assemble the rich :class:`Goal` — chorus's skeleton merged with horizon's strategy record."""
        node = self._goals.get(goal_id)
        if node is None:
            return None
        record = self._strategy.get(goal_id)
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
