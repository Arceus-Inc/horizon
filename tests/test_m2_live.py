"""Live decomposition smoke — one real Azure completion turning a decision into goals.

Skips cleanly (no failure) when ``AZURE_OPENAI_*`` are unset or the ``openai`` extra is missing. Run
with ``uv run pytest -m live`` after exporting the creds (they live in ``../chorus/.env``). Asserts
*structural* quality only (goal count, non-empty titles, scores in range) — never exact content.
"""

from __future__ import annotations

import os

import pytest

from horizon.model import Decision
from horizon.planning import Decomposer, Reasoner
from horizon.store import DecisionStore, StrategyStore
from tests.fakes import FakeGoalStore

pytestmark = pytest.mark.live


def _live_substrate() -> Reasoner:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and deployment):
        pytest.skip("set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
    try:
        from dream.api.openai import OpenAIChatSubstrate

        return OpenAIChatSubstrate(name="azure", api_key=key, model=deployment, base_url=base)
    except ImportError as exc:  # openai extra not installed
        pytest.skip(f"openai extra not installed: {exc}")


def test_live_decompose_produces_quality_goals(tmp_path):
    substrate = _live_substrate()
    decisions = DecisionStore(tmp_path / "decisions.json")
    strategy = StrategyStore(tmp_path / "strategy.json")
    decomposer = Decomposer(
        goals=FakeGoalStore(),
        strategy=strategy,
        decisions=decisions,
        reasoner=substrate,
        max_output_tokens=16000,
    )
    decisions.put(
        Decision(
            id="dec_live",
            statement="Build an AI note-taker for working professionals",
            owner="moe",
        )
    )

    out = decomposer.decompose("dec_live")

    assert 1 <= len(out) <= 6
    assert all(g.title.strip() for g in out)
    assert all(0.0 <= g.score <= 1.0 for g in out)
    assert all(r.decision_id == "dec_live" for r in strategy.all())
