"""Host-runner contract tests for Horizon's immutable Postgres migrations."""

from __future__ import annotations

import hashlib

import psycopg
import pytest

from horizon.store.postgres import (
    Migration,
    MigrationAheadError,
    MigrationDriftError,
    apply_migrations,
    load_migrations,
)


def test_migration_statements_strip_comments_and_keep_checksum_over_raw_sql() -> None:
    sql = """-- First statement comment; semicolons here are not SQL.
CREATE TABLE horizon_host_first (id text PRIMARY KEY);
-- Second statement comment.
ALTER TABLE horizon_host_first ADD COLUMN note text;
"""
    migration = Migration(id="host_contract", sql=sql)

    assert migration.statements() == [
        "CREATE TABLE horizon_host_first (id text PRIMARY KEY)",
        "ALTER TABLE horizon_host_first ADD COLUMN note text",
    ]
    assert migration.table_names() == ["horizon_host_first"]
    assert migration.sql == sql
    assert migration.checksum == hashlib.sha256(sql.encode("utf-8")).hexdigest()


def test_shipped_migrations_keep_order_and_exact_created_table_names() -> None:
    migrations = load_migrations()

    assert [(migration.id, migration.table_names()) for migration in migrations] == [
        ("0001_decisions", ["horizon_decision"]),
        (
            "0002_decision_status",
            [],
        ),
        (
            "0003_strategy_records",
            [
                "horizon_strategy_record",
                "horizon_strategy_evidence",
                "horizon_strategy_task",
                "horizon_strategy_task_outcome",
                "horizon_strategy_outcome_event",
                "horizon_strategy_lead_profession",
                "horizon_strategy_staffing_requirement",
            ],
        ),
        (
            "0004_proposals",
            [
                "horizon_proposal",
                "horizon_proposal_brief",
                "horizon_proposal_brief_risk",
                "horizon_proposal_brief_goal",
                "horizon_proposal_brief_evidence_ref",
            ],
        ),
    ]
    assert all(migration.statements() for migration in migrations)
    assert all(
        migration.checksum == hashlib.sha256(migration.sql.encode("utf-8")).hexdigest()
        for migration in migrations
    )


def test_apply_migrations_rejects_a_database_ahead_of_the_sdk(postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO horizon_schema_migrations (id, checksum) VALUES (%s, %s)",
            ("9999_future", "future-checksum"),
        )
        try:
            with pytest.raises(MigrationAheadError, match="9999_future"):
                apply_migrations(connection)
        finally:
            connection.execute(
                "DELETE FROM horizon_schema_migrations WHERE id = %s", ("9999_future",)
            )


def test_apply_migrations_rejects_edited_applied_sql(postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        apply_migrations(connection)
        row = connection.execute(
            "SELECT checksum FROM horizon_schema_migrations WHERE id = %s", ("0001_decisions",)
        ).fetchone()
        assert row is not None
        original_checksum = row[0]
        connection.execute(
            "UPDATE horizon_schema_migrations SET checksum = %s WHERE id = %s",
            ("edited-checksum", "0001_decisions"),
        )
        try:
            with pytest.raises(MigrationDriftError, match="0001_decisions"):
                apply_migrations(connection)
        finally:
            connection.execute(
                "UPDATE horizon_schema_migrations SET checksum = %s WHERE id = %s",
                (original_checksum, "0001_decisions"),
            )
