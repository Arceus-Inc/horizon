"""``GovernanceGate`` — the egress guard for external evidence sources (C-1a).

Internal + human-seeded sources need no gate (no egress). The web/market adapter does: it must pass an
**allow-list** (which hosts it may reach), present a **credential**, and stay under a **size cap** before
any content becomes evidence. The gate is pure policy — deterministic, network-free, and unit-testable —
so the external adapter physically cannot fetch outside what governance permits.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlparse

from horizon.errors import EgressBlocked


class GovernanceGate:
    """Allow-list + credential + size policy for external egress; raises :class:`EgressBlocked`."""

    def __init__(
        self,
        *,
        allowed_hosts: Sequence[str],
        require_credential: bool = True,
        max_bytes: int = 1_000_000,
    ) -> None:
        self._allowed = tuple(h.strip().lower() for h in allowed_hosts if h.strip())
        self._require_credential = require_credential
        self._max_bytes = max_bytes

    def authorize(self, url: str, *, credential: str | None = None) -> None:
        """Pre-fetch check: the host is on the allow-list and (if required) a credential is present."""
        host = (urlparse(url).hostname or "").lower()
        if not self._host_allowed(host):
            raise EgressBlocked(f"host not on the egress allow-list: {host or url!r}")
        if self._require_credential and not credential:
            raise EgressBlocked(f"missing credential for egress to {host}")

    def guard_size(self, size_bytes: int) -> None:
        """Post-fetch check: the response is within the size cap."""
        if size_bytes > self._max_bytes:
            raise EgressBlocked(f"response {size_bytes}B exceeds the {self._max_bytes}B cap")

    def _host_allowed(self, host: str) -> bool:
        if not host:
            return False
        return any(host == a or host.endswith("." + a) for a in self._allowed)
