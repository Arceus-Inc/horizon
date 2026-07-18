"""The thin CLI over horizon's stores (seed / decisions / show / version)."""

from __future__ import annotations

from horizon.model import Decision
from horizon.model._strategy import StrategyRecord
from horizon.store import DecisionStore, StrategyStore
from horizon_cli.__main__ import main


def test_version(capsys):
    assert main(["version"]) == 0
    assert "horizon 0.1.0" in capsys.readouterr().out


def test_no_command_defaults_to_version(tmp_path, capsys):
    assert main(["--store", str(tmp_path)]) == 0
    assert "horizon 0.1.0" in capsys.readouterr().out


def test_seed_creates_a_decision(tmp_path, capsys):
    assert main(["--store", str(tmp_path), "seed", "Build a thing", "--owner", "moe"]) == 0
    assert "seeded dec_" in capsys.readouterr().out

    stored = DecisionStore(tmp_path / "decisions.json").all()
    assert len(stored) == 1
    assert stored[0].statement == "Build a thing"
    assert stored[0].owner == "moe"


def test_decisions_lists_seeded(tmp_path, capsys):
    main(["--store", str(tmp_path), "seed", "Alpha"])
    main(["--store", str(tmp_path), "seed", "Beta"])
    capsys.readouterr()

    assert main(["--store", str(tmp_path), "decisions"]) == 0
    out = capsys.readouterr().out
    assert "Alpha" in out and "Beta" in out


def test_show_renders_direction_offline(tmp_path, capsys):
    DecisionStore(tmp_path / "decisions.json").put(
        Decision(id="dec_1", statement="Ship it", goal_ids=["g1"])
    )
    StrategyStore(tmp_path / "strategy.json").put(
        StrategyRecord(
            goal_id="g1", title="Build API", score=0.9, health="on_track", decision_id="dec_1"
        )
    )

    assert main(["--store", str(tmp_path), "show"]) == 0
    out = capsys.readouterr().out
    assert "Ship it" in out
    assert "Build API" in out
    assert "high" in out  # score 0.9 -> high
