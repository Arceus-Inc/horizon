"""Postgres DecisionRepository contract tests, including real FORCE RLS isolation."""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from horizon.model import Decision
from horizon.ports import DecisionRepository
from horizon.store.postgres import (
    PostgresDecisionRepository,
    apply_migrations,
    load_migrations,
    open_postgres_connection,
)


def _migrate(postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        apply_migrations(connection)


def _app_dsn(postgres_dsn: str) -> str:
    with psycopg.connect(postgres_dsn, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'horizon_app') "
            "THEN CREATE ROLE horizon_app LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO horizon_app")
        admin.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON horizon_decision TO horizon_app")
    return postgres_dsn.replace("user=postgres", "user=horizon_app")


def test_migration_exports_the_versioned_decision_schema(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)

    assert [migration.id for migration in load_migrations()] == [
        "0001_decisions",
        "0002_decision_status",
        "0003_strategy_records",
    ]
    with psycopg.connect(postgres_dsn) as admin:
        rls = admin.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'horizon_decision'::regclass"
        ).fetchone()
        columns = {
            row[0]: row[1]
            for row in admin.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'horizon_decision'"
            ).fetchall()
        }

    assert rls == (True, True)
    assert columns == {
        "company_id": "uuid",
        "id": "text",
        "statement": "text",
        "status": "text",
        "owner": "text",
        "rationale": "text",
        "goal_ids": "ARRAY",
        "position": "bigint",
    }


def test_postgres_decisions_round_trip_after_restart(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    company_id = uuid4()
    decision = Decision(
        id="dec_1",
        statement="Focus the roadmap",
        status="proposed",
        owner="ceo",
        rationale="Customer demand",
        goal_ids=["goal_1", "goal_2"],
    )

    first_connection = open_postgres_connection(app_dsn, company_id=company_id)
    try:
        repository: DecisionRepository = PostgresDecisionRepository(first_connection)
        assert repository.put(decision) == decision
    finally:
        first_connection.close()

    second_connection = open_postgres_connection(app_dsn, company_id=company_id)
    try:
        repository = PostgresDecisionRepository(second_connection)
        assert repository.get(decision.id) == decision
    finally:
        second_connection.close()


def test_postgres_decisions_keep_insert_order_and_upsert_in_place(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    connection = open_postgres_connection(app_dsn, company_id=uuid4())
    try:
        repository = PostgresDecisionRepository(connection)
        repository.put(Decision(id="dec_2", statement="Second"))
        repository.put(Decision(id="dec_1", statement="First"))
        updated = Decision(id="dec_2", statement="Second, revised", status="paused")

        assert repository.put(updated) == updated
        assert repository.all() == [updated, Decision(id="dec_1", statement="First")]
    finally:
        connection.close()


def test_postgres_decisions_reject_unknown_statuses(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    connection = open_postgres_connection(app_dsn, company_id=uuid4())
    try:
        repository = PostgresDecisionRepository(connection)
        with pytest.raises(psycopg.errors.CheckViolation):
            repository.put(Decision(id="dec_invalid", statement="Invalid", status="unknown"))
    finally:
        connection.close()


def test_postgres_decisions_are_isolated_by_company_guc(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    connection_a = open_postgres_connection(app_dsn, company_id=uuid4())
    connection_b = open_postgres_connection(app_dsn, company_id=uuid4())
    try:
        repository_a = PostgresDecisionRepository(connection_a)
        repository_b = PostgresDecisionRepository(connection_b)
        decision_a = Decision(id="dec_shared", statement="Company A direction")
        decision_b = Decision(id="dec_shared", statement="Company B direction")

        repository_a.put(decision_a)
        repository_b.put(decision_b)

        assert repository_a.get("dec_shared") == decision_a
        assert repository_b.get("dec_shared") == decision_b
        assert repository_a.all() == [decision_a]
        assert repository_b.all() == [decision_b]
    finally:
        connection_a.close()
        connection_b.close()
