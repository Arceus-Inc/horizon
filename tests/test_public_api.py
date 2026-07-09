"""Pin horizon's public surface — a change here must be a deliberate export edit (SDK version signal)."""

from __future__ import annotations

import horizon
import horizon.feedback as feedback
import horizon.intake as intake
import horizon.model as model
import horizon.planning as planning
import horizon.ports as ports
import horizon.store as store


def _all(module) -> set[str]:
    return set(module.__all__)


def test_top_level_surface_is_pinned():
    assert _all(horizon) == {
        "Decision",
        "DecisionState",
        "DecisionStore",
        "Goal",
        "HealthPolicy",
        "Horizon",
        "LoopReporter",
        "ScorePolicy",
        "StrategyRecord",
        "StrategyStore",
        "__version__",
        "render_direction",
    }
    assert horizon.__version__ == "0.1.0"


def test_ports_surface_is_pinned():
    assert _all(ports) == {
        "GoalNode",
        "GoalStore",
        "IntakePort",
        "OutcomeEvent",
        "OutcomeFeed",
        "Priority",
    }


def test_planning_surface_is_pinned():
    assert _all(planning) == {"CompletionResult", "Decomposer", "Reasoner"}


def test_intake_surface_is_pinned():
    assert _all(intake) == {"Prioritiser", "ScorePolicy", "Submitter", "fingerprint", "normalize_intent"}


def test_feedback_surface_is_pinned():
    assert _all(feedback) == {"HealthPolicy", "OutcomeListener", "apply_outcome", "staleness_health"}


def test_model_surface_is_pinned():
    assert _all(model) == {"Decision", "DecisionState", "Goal", "StrategyRecord"}


def test_store_surface_is_pinned():
    assert _all(store) == {"DecisionStore", "StrategyStore"}


def test_horizon_facade_exposes_the_loop_methods():
    for method in (
        "seed_decision",
        "decompose",
        "submit_goal",
        "submit_decision",
        "reprioritise",
        "sweep_staleness",
        "note_outcome",
        "recover",
        "listener_stats",
        "start",
        "stop",
        "goal_view",
        "state",
        "generate",
        "reconcile",
        "list_proposals",
        "explain_proposal",
        "approve_proposal",
        "reject_proposal",
    ):
        assert callable(getattr(horizon.Horizon, method))
