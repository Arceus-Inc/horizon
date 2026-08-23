"""Pin horizon's public surface — a change here must be a deliberate export edit (SDK version signal)."""

from __future__ import annotations

from types import ModuleType

import horizon
import horizon.feedback as feedback
import horizon.intake as intake
import horizon.model as model
import horizon.planning as planning
import horizon.ports as ports
import horizon.store as store
from horizon.generation import Proposal, ProposalStore
from horizon.model import Decision, StrategyRecord
from horizon.ports import DecisionRepository, ProposalRepository, StrategyRepository
from horizon.store import DecisionStore, StrategyStore


def _all(module: ModuleType) -> set[str]:
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
        "CapacityPort",
        "DecisionRepository",
        "DelegatedIntakePort",
        "DelegatedWorkRef",
        "DelegatedWorkRequest",
        "GoalNode",
        "GoalStore",
        "IntakePort",
        "OutcomeEvent",
        "OutcomeFeed",
        "Priority",
        "ProfessionCapacity",
        "ProposalRepository",
        "StaffingBlocked",
        "StaffingRequirement",
        "StrategyRepository",
    }


def test_planning_surface_is_pinned():
    assert _all(planning) == {
        "CapabilityFailureEvidence",
        "CapabilityGap",
        "CapabilityGapDetector",
        "CapabilityGapPolicy",
        "CapabilitySeverity",
        "CompletionResult",
        "Decomposer",
        "EffectivePriorityPolicy",
        "EffectiveResult",
        "Reasoner",
    }


def test_intake_surface_is_pinned():
    assert _all(intake) == {
        "DelegatedSubmitter",
        "Prioritiser",
        "ScorePolicy",
        "Submitter",
        "fingerprint",
        "normalize_intent",
    }


def test_feedback_surface_is_pinned():
    assert _all(feedback) == {
        "HealthPolicy",
        "OutcomeFold",
        "OutcomeListener",
        "ReplanSignal",
        "apply_outcome",
        "detect_replan",
        "staleness_health",
    }


def test_model_surface_is_pinned():
    assert _all(model) == {
        "Decision",
        "DecisionDigest",
        "DecisionState",
        "Goal",
        "GoalDigest",
        "RealityDigest",
        "StrategyRecord",
        "build_reality_digest",
    }


def test_store_surface_is_pinned():
    assert _all(store) == {"DecisionStore", "StrategyStore"}


def test_json_stores_implement_direction_repository_ports(tmp_path) -> None:
    decisions: DecisionRepository = DecisionStore(tmp_path / "decisions.json")
    strategy: StrategyRepository = StrategyStore(tmp_path / "strategy.json")
    proposals: ProposalRepository = ProposalStore(tmp_path / "proposals.json")

    decision = Decision(id="dec_1", statement="Focus the roadmap")
    record = StrategyRecord(goal_id="goal_1", title="Ship the first slice")
    proposal = Proposal(id="prop_1", decision_statement="Focus the roadmap")

    assert decisions.put(decision) == decision
    assert strategy.put(record) == record
    assert proposals.put(proposal) == proposal
    assert decisions.all() == [decision]
    assert strategy.all() == [record]
    assert proposals.all() == [proposal]


def test_horizon_facade_exposes_the_loop_methods():
    for method in (
        "seed_decision",
        "propose_roadmap",
        "digest",
        "detect_replan",
        "decompose",
        "submit_goal",
        "submit_decision",
        "reprioritise",
        "set_priority",
        "archive_goal",
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
