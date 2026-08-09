"""Postgres direction-store primitives and the production ``DecisionRepository``.

This module is optional: install ``horizon[postgres]`` to use it.  The default JSON stores remain
available without psycopg.  Migrations are Horizon-owned and reusable by the planned strategy and
proposal repositories; application connections are separately opened with Chorus's company GUC.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from typing import Literal
from uuid import UUID

import psycopg
from dream.contracts import StaffingRequirement
from psycopg import Connection
from psycopg.rows import class_row

from horizon.model import Decision, StrategyRecord

_MIGRATIONS_TABLE = "horizon_schema_migrations"


class MigrationAheadError(RuntimeError):
    """The database has a Horizon migration this SDK does not ship."""


class MigrationDriftError(RuntimeError):
    """A shipped Horizon migration differs from the applied immutable version."""


@dataclass(frozen=True)
class Migration:
    """One immutable Horizon schema delta."""

    id: str
    sql: str

    @property
    def checksum(self) -> str:
        """The immutable migration contents' checksum."""
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _MigrationRow:
    id: str
    checksum: str


@dataclass(frozen=True)
class _DecisionRow:
    id: str
    statement: str
    status: str
    owner: str | None
    rationale: str
    goal_ids: list[str]

    def as_decision(self) -> Decision:
        return Decision(
            id=self.id,
            statement=self.statement,
            status=self.status,
            owner=self.owner,
            rationale=self.rationale,
            goal_ids=list(self.goal_ids),
        )


@dataclass(frozen=True)
class _StrategyRow:
    goal_id: str
    title: str
    score: float
    health: str
    metric: str | None
    target: str | None
    decision_id: str | None
    task_id: str | None
    root_task_id: str | None
    team_id: str | None
    lead_id: str | None
    delivery_shape: str
    passes: int
    fails: int
    last_outcome_at: datetime | None
    done: bool
    attempts: int
    needs_recovery: bool
    last_diagnostic: str


@dataclass(frozen=True)
class _EvidenceRow:
    position: int
    value: str


@dataclass(frozen=True)
class _TaskRow:
    position: int
    task_id: str


@dataclass(frozen=True)
class _TaskOutcomeRow:
    task_id: str
    outcome: str | None
    revision: int | None


@dataclass(frozen=True)
class _OutcomeEventRow:
    position: int
    event_id: str


@dataclass(frozen=True)
class _LeadProfessionRow:
    position: int
    profession: str


@dataclass(frozen=True)
class _StaffingRequirementRow:
    position: int
    profession: str
    count: int
    coverage: Literal["direct", "subtree"]
    outcome_area: str | None


def load_migrations() -> list[Migration]:
    """Load Horizon's immutable migration stream in version order."""
    directory = files("horizon.store.migrations")
    migrations = [
        Migration(id=entry.name.removesuffix(".sql"), sql=entry.read_text(encoding="utf-8"))
        for entry in directory.iterdir()
        if entry.name.endswith(".sql")
    ]
    return sorted(migrations, key=lambda migration: migration.id)


def open_postgres_connection(
    dsn: str, *, company_id: UUID
) -> Connection[tuple[object, ...]]:
    """Open one application connection pinned to a company for FORCE RLS."""
    connection: Connection[tuple[object, ...]] = psycopg.connect(dsn, autocommit=True)
    connection.execute("SET TIME ZONE 'UTC'")
    connection.execute("SELECT set_config('app.company_id', %s, false)", (str(company_id),))
    return connection


def apply_migrations(connection: Connection[tuple[object, ...]]) -> None:
    """Apply Horizon's immutable migration stream with checksum and ahead-of-SDK guards."""
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} ("
        "id text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    migrations = load_migrations()
    with connection.transaction():
        connection.execute(f"LOCK TABLE {_MIGRATIONS_TABLE} IN EXCLUSIVE MODE")
        with connection.cursor(row_factory=class_row(_MigrationRow)) as cursor:
            applied = {
                row.id: row.checksum
                for row in cursor.execute(
                    f"SELECT id, checksum FROM {_MIGRATIONS_TABLE}"
                ).fetchall()
            }
        shipped = {migration.id for migration in migrations}
        ahead = sorted(set(applied) - shipped)
        if ahead:
            raise MigrationAheadError(
                "database has Horizon migrations this SDK does not ship: " + ", ".join(ahead)
            )
        for migration in migrations:
            checksum = applied.get(migration.id)
            if checksum is not None:
                if checksum != migration.checksum:
                    raise MigrationDriftError(
                        f"migration {migration.id} differs from its applied immutable version"
                    )
                continue
            connection.execute(migration.sql)
            connection.execute(
                f"INSERT INTO {_MIGRATIONS_TABLE} (id, checksum) VALUES (%s, %s)",
                (migration.id, migration.checksum),
            )


class PostgresDecisionRepository:
    """Company-scoped, Postgres-backed implementation of Horizon's ``DecisionRepository``."""

    def __init__(self, connection: Connection[tuple[object, ...]]) -> None:
        self._connection = connection

    def get(self, decision_id: str) -> Decision | None:
        with self._connection.cursor(row_factory=class_row(_DecisionRow)) as cursor:
            row = cursor.execute(
                "SELECT id, statement, status, owner, rationale, goal_ids "
                "FROM horizon_decision WHERE id = %s",
                (decision_id,),
            ).fetchone()
        return row.as_decision() if row is not None else None

    def put(self, decision: Decision) -> Decision:
        self._connection.execute(
            "INSERT INTO horizon_decision (id, statement, status, owner, rationale, goal_ids) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (company_id, id) DO UPDATE SET "
            "statement = EXCLUDED.statement, status = EXCLUDED.status, owner = EXCLUDED.owner, "
            "rationale = EXCLUDED.rationale, goal_ids = EXCLUDED.goal_ids",
            (
                decision.id,
                decision.statement,
                decision.status,
                decision.owner,
                decision.rationale,
                decision.goal_ids,
            ),
        )
        return decision

    def all(self) -> list[Decision]:
        with self._connection.cursor(row_factory=class_row(_DecisionRow)) as cursor:
            rows = cursor.execute(
                "SELECT id, statement, status, owner, rationale, goal_ids "
                "FROM horizon_decision ORDER BY position"
            ).fetchall()
        return [row.as_decision() for row in rows]


class PostgresStrategyRepository:
    """Company-scoped, Postgres-backed implementation of Horizon's ``StrategyRepository``."""

    def __init__(self, connection: Connection[tuple[object, ...]]) -> None:
        self._connection = connection

    def get(self, goal_id: str) -> StrategyRecord | None:
        with self._connection.cursor(row_factory=class_row(_StrategyRow)) as cursor:
            row = cursor.execute(
                "SELECT goal_id, title, score, health, metric, target, decision_id, task_id, "
                "root_task_id, team_id, lead_id, delivery_shape, passes, fails, last_outcome_at, "
                "done, attempts, needs_recovery, last_diagnostic "
                "FROM horizon_strategy_record WHERE goal_id = %s",
                (goal_id,),
            ).fetchone()
        return self._record_from_row(row) if row is not None else None

    def put(self, record: StrategyRecord) -> StrategyRecord:
        last_outcome_at = (
            datetime.fromisoformat(record.last_outcome_at)
            if record.last_outcome_at is not None
            else None
        )
        with self._connection.transaction():
            self._connection.execute(
                "INSERT INTO horizon_strategy_record ("
                "goal_id, title, score, health, metric, target, decision_id, task_id, root_task_id, "
                "team_id, lead_id, delivery_shape, passes, fails, last_outcome_at, done, attempts, "
                "needs_recovery, last_diagnostic) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (company_id, goal_id) DO UPDATE SET "
                "title = EXCLUDED.title, score = EXCLUDED.score, health = EXCLUDED.health, "
                "metric = EXCLUDED.metric, target = EXCLUDED.target, decision_id = EXCLUDED.decision_id, "
                "task_id = EXCLUDED.task_id, root_task_id = EXCLUDED.root_task_id, "
                "team_id = EXCLUDED.team_id, lead_id = EXCLUDED.lead_id, "
                "delivery_shape = EXCLUDED.delivery_shape, passes = EXCLUDED.passes, "
                "fails = EXCLUDED.fails, last_outcome_at = EXCLUDED.last_outcome_at, "
                "done = EXCLUDED.done, attempts = EXCLUDED.attempts, "
                "needs_recovery = EXCLUDED.needs_recovery, "
                "last_diagnostic = EXCLUDED.last_diagnostic",
                (
                    record.goal_id,
                    record.title,
                    record.score,
                    record.health,
                    record.metric,
                    record.target,
                    record.decision_id,
                    record.task_id,
                    record.root_task_id,
                    record.team_id,
                    record.lead_id,
                    record.delivery_shape,
                    record.passes,
                    record.fails,
                    last_outcome_at,
                    record.done,
                    record.attempts,
                    record.needs_recovery,
                    record.last_diagnostic,
                ),
            )
            self._connection.execute(
                "DELETE FROM horizon_strategy_evidence WHERE goal_id = %s", (record.goal_id,)
            )
            self._connection.execute(
                "DELETE FROM horizon_strategy_task WHERE goal_id = %s", (record.goal_id,)
            )
            self._connection.execute(
                "DELETE FROM horizon_strategy_task_outcome WHERE goal_id = %s", (record.goal_id,)
            )
            self._connection.execute(
                "DELETE FROM horizon_strategy_outcome_event WHERE goal_id = %s", (record.goal_id,)
            )
            self._connection.execute(
                "DELETE FROM horizon_strategy_lead_profession WHERE goal_id = %s", (record.goal_id,)
            )
            self._connection.execute(
                "DELETE FROM horizon_strategy_staffing_requirement WHERE goal_id = %s",
                (record.goal_id,),
            )
            for position, evidence in enumerate(record.evidence):
                self._connection.execute(
                    "INSERT INTO horizon_strategy_evidence (goal_id, position, value) "
                    "VALUES (%s, %s, %s)",
                    (record.goal_id, position, evidence),
                )
            for position, task_id in enumerate(record.task_ids):
                self._connection.execute(
                    "INSERT INTO horizon_strategy_task (goal_id, position, task_id) "
                    "VALUES (%s, %s, %s)",
                    (record.goal_id, position, task_id),
                )
            outcome_task_ids = list(record.task_outcomes)
            for task_id in record.task_outcome_revisions:
                if task_id not in record.task_outcomes:
                    outcome_task_ids.append(task_id)
            for task_id in outcome_task_ids:
                self._connection.execute(
                    "INSERT INTO horizon_strategy_task_outcome (goal_id, task_id, outcome, revision) "
                    "VALUES (%s, %s, %s, %s)",
                    (
                        record.goal_id,
                        task_id,
                        record.task_outcomes.get(task_id),
                        record.task_outcome_revisions.get(task_id),
                    ),
                )
            for position, event_id in enumerate(record.outcome_event_ids):
                self._connection.execute(
                    "INSERT INTO horizon_strategy_outcome_event (goal_id, position, event_id) "
                    "VALUES (%s, %s, %s)",
                    (record.goal_id, position, event_id),
                )
            for position, profession in enumerate(record.lead_professions):
                self._connection.execute(
                    "INSERT INTO horizon_strategy_lead_profession (goal_id, position, profession) "
                    "VALUES (%s, %s, %s)",
                    (record.goal_id, position, profession),
                )
            for position, requirement in enumerate(record.staffing_requirements):
                self._connection.execute(
                    "INSERT INTO horizon_strategy_staffing_requirement ("
                    "goal_id, position, profession, count, coverage, outcome_area) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        record.goal_id,
                        position,
                        requirement.profession,
                        requirement.count,
                        requirement.coverage,
                        requirement.outcome_area,
                    ),
                )
        return record

    def all(self) -> list[StrategyRecord]:
        with self._connection.cursor(row_factory=class_row(_StrategyRow)) as cursor:
            rows = cursor.execute(
                "SELECT goal_id, title, score, health, metric, target, decision_id, task_id, "
                "root_task_id, team_id, lead_id, delivery_shape, passes, fails, last_outcome_at, "
                "done, attempts, needs_recovery, last_diagnostic "
                "FROM horizon_strategy_record ORDER BY position"
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def _record_from_row(self, row: _StrategyRow) -> StrategyRecord:
        goal_id = row.goal_id
        with self._connection.cursor(row_factory=class_row(_EvidenceRow)) as cursor:
            evidence_rows = cursor.execute(
                "SELECT position, value FROM horizon_strategy_evidence "
                "WHERE goal_id = %s ORDER BY position",
                (goal_id,),
            ).fetchall()
        with self._connection.cursor(row_factory=class_row(_TaskRow)) as cursor:
            task_rows = cursor.execute(
                "SELECT position, task_id FROM horizon_strategy_task "
                "WHERE goal_id = %s ORDER BY position",
                (goal_id,),
            ).fetchall()
        with self._connection.cursor(row_factory=class_row(_TaskOutcomeRow)) as cursor:
            task_outcome_rows = cursor.execute(
                "SELECT task_id, outcome, revision FROM horizon_strategy_task_outcome "
                "WHERE goal_id = %s ORDER BY task_id",
                (goal_id,),
            ).fetchall()
        with self._connection.cursor(row_factory=class_row(_OutcomeEventRow)) as cursor:
            event_rows = cursor.execute(
                "SELECT position, event_id FROM horizon_strategy_outcome_event "
                "WHERE goal_id = %s ORDER BY position",
                (goal_id,),
            ).fetchall()
        with self._connection.cursor(row_factory=class_row(_LeadProfessionRow)) as cursor:
            profession_rows = cursor.execute(
                "SELECT position, profession FROM horizon_strategy_lead_profession "
                "WHERE goal_id = %s ORDER BY position",
                (goal_id,),
            ).fetchall()
        with self._connection.cursor(row_factory=class_row(_StaffingRequirementRow)) as cursor:
            requirement_rows = cursor.execute(
                "SELECT position, profession, count, coverage, outcome_area "
                "FROM horizon_strategy_staffing_requirement WHERE goal_id = %s ORDER BY position",
                (goal_id,),
            ).fetchall()

        task_outcomes: dict[str, str] = {}
        task_outcome_revisions: dict[str, int] = {}
        for task_outcome_row in task_outcome_rows:
            if task_outcome_row.outcome is not None:
                task_outcomes[task_outcome_row.task_id] = task_outcome_row.outcome
            if task_outcome_row.revision is not None:
                task_outcome_revisions[task_outcome_row.task_id] = task_outcome_row.revision
        return StrategyRecord(
            goal_id=row.goal_id,
            title=row.title,
            score=row.score,
            health=row.health,
            metric=row.metric,
            target=row.target,
            evidence=[evidence_row.value for evidence_row in evidence_rows],
            decision_id=row.decision_id,
            task_id=row.task_id,
            root_task_id=row.root_task_id,
            task_ids=[task_row.task_id for task_row in task_rows],
            team_id=row.team_id,
            lead_id=row.lead_id,
            task_outcomes=task_outcomes,
            task_outcome_revisions=task_outcome_revisions,
            outcome_event_ids=[event_row.event_id for event_row in event_rows],
            delivery_shape=row.delivery_shape,
            lead_professions=tuple(profession_row.profession for profession_row in profession_rows),
            staffing_requirements=tuple(
                StaffingRequirement(
                    profession=requirement_row.profession,
                    count=requirement_row.count,
                    coverage=requirement_row.coverage,
                    outcome_area=requirement_row.outcome_area,
                )
                for requirement_row in requirement_rows
            ),
            passes=row.passes,
            fails=row.fails,
            last_outcome_at=(
                row.last_outcome_at.isoformat() if row.last_outcome_at is not None else None
            ),
            done=row.done,
            attempts=row.attempts,
            needs_recovery=row.needs_recovery,
            last_diagnostic=row.last_diagnostic,
        )


__all__ = [
    "Migration",
    "MigrationAheadError",
    "MigrationDriftError",
    "PostgresDecisionRepository",
    "PostgresStrategyRepository",
    "apply_migrations",
    "load_migrations",
    "open_postgres_connection",
]
