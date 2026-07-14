"""intake — push a **Goal** into chorus as work (the ``IntakePort`` side of the seam).

The ``Submitter`` turns a leaf goal into one idempotent ``IntakePort.submit`` (fingerprinted on
``goal_id`` + a normalized-intent hash, so re-deriving the same goal is a no-op). The ``Prioritiser``
maps a goal's numeric ``score`` to chorus's coarse ``Priority`` via ``IntakePort.set_priority``. Both
bind only to horizon's ports — never to chorus.

Lands in M2: ``_submitter.py``, ``_prioritiser.py``, ``_fingerprint.py``.
"""

from __future__ import annotations

from horizon.intake._delegated import DelegatedSubmitter
from horizon.intake._fingerprint import fingerprint, normalize_intent
from horizon.intake._prioritiser import Prioritiser, ScorePolicy
from horizon.intake._submitter import Submitter

__all__ = [
    "DelegatedSubmitter",
    "Prioritiser",
    "ScorePolicy",
    "Submitter",
    "fingerprint",
    "normalize_intent",
]
