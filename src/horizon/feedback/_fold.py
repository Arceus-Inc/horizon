"""Root-authoritative aggregation of hierarchical task outcomes."""

from __future__ import annotations

from horizon.model import StrategyRecord
from horizon.ports import OutcomeEvent

_BLOCKED_STATUSES = frozenset({"blocked", "hard_blocked", "escalated", "human_escalation"})
_FAILED_STATUSES = frozenset({"failed", "rejected"})


class OutcomeFold:
    """Fold the latest task evidence into one strategic goal state."""

    def apply(self, record: StrategyRecord, event: OutcomeEvent) -> bool:
        """Apply one task outcome, returning whether its latest summary changed."""
        if event.task_id is None:
            return False
        if event.event_id is not None and event.event_id in record.outcome_event_ids:
            return False
        if event.task_revision is not None:
            current_revision = record.task_outcome_revisions.get(event.task_id)
            if current_revision is not None and event.task_revision <= current_revision:
                return False
        summary = self._summary(record, event)
        is_root = event.task_id == record.root_task_id
        root_pass = is_root and event.passed is True
        root_terminal = is_root and summary in {"blocked", "failed"}
        if summary is None or (
            record.task_outcomes.get(event.task_id) == summary
            and not (root_pass and not record.done)
        ):
            return False
        record.task_outcomes[event.task_id] = summary
        if event.task_revision is not None:
            record.task_outcome_revisions[event.task_id] = event.task_revision
        if event.event_id is not None:
            record.outcome_event_ids.append(event.event_id)
        if event.task_id not in record.task_ids:
            record.task_ids.append(event.task_id)
        if root_pass:
            record.done = True
        elif root_terminal:
            record.done = False
        self._recompute(record)
        return True

    @staticmethod
    def _summary(record: StrategyRecord, event: OutcomeEvent) -> str | None:
        status = (event.status or "").lower()
        if event.kind == "recovery.escalated":
            return "blocked"
        if status in _BLOCKED_STATUSES:
            return "blocked"
        if event.passed is True:
            return "passed"
        if event.passed is False or status in _FAILED_STATUSES:
            return "failed"
        return None

    @staticmethod
    def _recompute(record: StrategyRecord) -> None:
        """Recompute health from the CURRENT outcome set — clears as well as escalates."""
        outcomes = set(record.task_outcomes.values())
        if record.done:
            record.health = "on_track"
        elif "blocked" in outcomes:
            record.health = "blocked"
        elif "failed" in outcomes:
            record.health = "drifting"
        elif "passed" in outcomes:
            record.health = "on_track"
        else:
            record.health = "unknown"
