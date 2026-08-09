"""Postgres DecisionRepository contract tests, including real FORCE RLS isolation."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path
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

_PG_BIN = Path(
    os.environ.get("HORIZON_PG_BIN", os.environ.get("CHORUS_PG_BIN", "/opt/homebrew/opt/postgresql@18/bin"))
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def postgres_dsn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A real local Postgres cluster, following Chorus's integration-test convention."""
    if not _PG_BIN.exists():
        pytest.skip(f"PostgreSQL not found at {_PG_BIN} (set HORIZON_PG_BIN)")
    data = tmp_path_factory.mktemp("horizon_pgdata")
    env = {**os.environ, "LC_ALL": "C"}
    subprocess.run(
        [
            str(_PG_BIN / "initdb"),
            "-D",
            str(data),
            "-U",
            "postgres",
            "--auth=trust",
            "--encoding=UTF8",
            "--locale=C",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    port = _free_port()
    subprocess.run(
        [
            str(_PG_BIN / "pg_ctl"),
            "-D",
            str(data),
            "-o",
            f"-p {port} -c listen_addresses=127.0.0.1 "
            "-c unix_socket_directories=''",
            "-l",
            str(data / "log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    dsn = f"host=127.0.0.1 port={port} user=postgres dbname=postgres"
    try:
        yield dsn
    finally:
        subprocess.run(
            [str(_PG_BIN / "pg_ctl"), "-D", str(data), "-w", "stop"],
            capture_output=True,
            env=env,
        )
        shutil.rmtree(data, ignore_errors=True)


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

    assert [migration.id for migration in load_migrations()] == ["0001_decisions"]
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
    company_id = str(uuid4())
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
    connection = open_postgres_connection(app_dsn, company_id=str(uuid4()))
    try:
        repository = PostgresDecisionRepository(connection)
        repository.put(Decision(id="dec_2", statement="Second"))
        repository.put(Decision(id="dec_1", statement="First"))
        updated = Decision(id="dec_2", statement="Second, revised", status="paused")

        assert repository.put(updated) == updated
        assert repository.all() == [updated, Decision(id="dec_1", statement="First")]
    finally:
        connection.close()


def test_postgres_decisions_are_isolated_by_company_guc(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    connection_a = open_postgres_connection(app_dsn, company_id=str(uuid4()))
    connection_b = open_postgres_connection(app_dsn, company_id=str(uuid4()))
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
