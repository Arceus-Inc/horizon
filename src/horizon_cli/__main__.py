"""The ``horizon`` console entry point (v1 stub — the real tree-view / submit CLI lands in M3)."""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Print the horizon version, or a placeholder. The full CLI arrives in M3."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"-V", "--version", "version"}:
        from horizon import __version__

        print(f"horizon {__version__}")
        return 0
    print("horizon v1 (M1 seam). CLI arrives in M3 — use the SDK for now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
