"""Postgres direction-store primitives and the production ``DecisionRepository``.

This module is optional: install ``horizon[postgres]`` to use it.  The default JSON stores remain
available without psycopg.  Migrations are Horizon-owned and reusable by the planned strategy and
proposal repositories; application connections are separately opened with Chorus's company GUC.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import files
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import class_row

from horizon.model import Decision

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


__all__ = [
    "Migration",
    "MigrationAheadError",
    "MigrationDriftError",
    "PostgresDecisionRepository",
    "apply_migrations",
    "load_migrations",
    "open_postgres_connection",
]
