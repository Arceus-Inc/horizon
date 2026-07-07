"""The ``horizon`` console entry point — a thin operator surface over the SDK's stores.

Reads/writes horizon's own stores (``.horizon/`` by default), so it works without a live chorus:

    horizon seed "Build an AI note-taker for working professionals" --owner moe
    horizon decisions
    horizon show

Decompose + submit need a reasoner + the chorus bridge, so those run through the examples/demos, not
this thin CLI.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from horizon import __version__
from horizon._ids import mint_id
from horizon.model import Decision
from horizon.reporting import direction_from_records, render_direction
from horizon.store import DecisionStore, StrategyStore


def _stores(store_dir: str) -> tuple[DecisionStore, StrategyStore]:
    root = Path(store_dir)
    return DecisionStore(root / "decisions.json"), StrategyStore(root / "strategy.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="horizon", description="horizon — the strategy layer CLI")
    parser.add_argument(
        "--store", default=".horizon", help="horizon store directory (default .horizon)"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("version", help="print the horizon version")
    seed = sub.add_parser("seed", help="create a decision")
    seed.add_argument("statement", help="the decision statement")
    seed.add_argument("--owner", default=None, help="owner slug")
    sub.add_parser("decisions", help="list decisions")
    sub.add_parser("show", help="render the current direction (decisions -> goals)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "version"
    decisions, strategy = _stores(args.store)

    if command == "version":
        print(f"horizon {__version__}")
        return 0
    if command == "seed":
        decision = Decision(id=mint_id("dec"), statement=args.statement, owner=args.owner)
        decisions.put(decision)
        print(f"seeded {decision.id}: {decision.statement}")
        return 0
    if command == "decisions":
        rows = decisions.all()
        if not rows:
            print("(no decisions)")
        for decision in rows:
            print(
                f"{decision.id}  [{decision.status}]  goals={len(decision.goal_ids)}  "
                f"{decision.statement}"
            )
        return 0
    if command == "show":
        print(render_direction(direction_from_records(decisions, strategy)))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
