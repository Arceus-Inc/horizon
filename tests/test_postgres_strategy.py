"""Postgres StrategyRepository contract tests, including real FORCE RLS isolation."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from dream.contracts import StaffingRequirement

from horizon.model import StrategyRecord
from horizon.ports import StrategyRepository
from horizon.store.postgres import (
    PostgresStrategyRepository,
    apply_migrations,
    open_postgres_connection,
)

_STRATEGY_TABLES = (
    "horizon_strategy_record",
    "horizon_strategy_evidence",
    "horizon_strategy_task",
    "horizon_strategy_task_outcome",
    "horizon_strategy_outcome_event",
    "horizon_strategy_lead_profession",
    "horizon_strategy_staffing_requirement",
)


def _migrate(postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        apply_migrations(connection)


def _app_dsn(postgres_dsn: str) -> str:
    with psycopg.connect(postgres_dsn, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = "
            "'horizon_strategy_app') THEN CREATE ROLE horizon_strategy_app "
            "LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO horizon_strategy_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON " + ", ".join(_STRATEGY_TABLES) + " "
            "TO horizon_strategy_app"
        )
    return postgres_dsn.replace("user=postgres", "user=horizon_strategy_app")


def _record(goal_id: str = "goal_1") -> StrategyRecord:
    return StrategyRecord(
        goal_id=goal_id,
        title="Increase retained revenue",
        score=0.85,
        health="drifting",
        metric="Net revenue retention",
        target="120%",
        evidence=["Renewal cohort fell", "Expansion pipeline recovered"],
        decision_id="dec_1",
        task_id="task_retry",
        root_task_id="task_root",
        task_ids=["task_root", "task_child"],
        team_id="team_revenue",
        lead_id="lead_1",
        task_outcomes={"task_root": "passed", "task_child": "blocked"},
        task_outcome_revisions={"task_root": 2, "task_revision_only": 3},
        outcome_event_ids=["event_1", "event_2"],
        delivery_shape="team",
        lead_professions=("product", "engineering"),
        staffing_requirements=(
            StaffingRequirement(
                profession="product",
                count=1,
                coverage="direct",
                outcome_area="retention",
            ),
            StaffingRequirement(profession="engineering", count=2, coverage="subtree"),
        ),
        passes=4,
        fails=1,
        last_outcome_at="2026-08-09T10:11:12+00:00",
        done=True,
        attempts=3,
        needs_recovery=True,
        last_diagnostic="Retry after the integration fix.",
    )


def test_postgres_strategy_round_trips_every_field_after_restart(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    company_id = uuid4()
    record = _record()

    first_connection = open_postgres_connection(app_dsn, company_id=company_id)
    try:
        repository: StrategyRepository = PostgresStrategyRepository(first_connection)
        assert repository.put(record) == record
    finally:
        first_connection.close()

    second_connection = open_postgres_connection(app_dsn, company_id=company_id)
    try:
        repository = PostgresStrategyRepository(second_connection)
        assert repository.get(record.goal_id) == record
    finally:
        second_connection.close()


def test_postgres_strategy_keeps_insert_order_and_upserts_in_place(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    connection = open_postgres_connection(_app_dsn(postgres_dsn), company_id=uuid4())
    try:
        repository = PostgresStrategyRepository(connection)
        second = StrategyRecord(goal_id="goal_2", title="Second")
        first = StrategyRecord(goal_id="goal_1", title="First")
        updated = StrategyRecord(goal_id="goal_2", title="Second, revised", health="on_track")

        repository.put(second)
        repository.put(first)

        assert repository.put(updated) == updated
        assert repository.all() == [updated, first]
    finally:
        connection.close()


def test_postgres_strategy_replacement_removes_stale_child_rows(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    company_id = uuid4()
    original = _record()
    replacement = replace(
        original,
        evidence=["Fresh evidence"],
        task_ids=["task_new"],
        task_outcomes={"task_new": "passed"},
        task_outcome_revisions={"task_new": 7},
        outcome_event_ids=["event_new"],
        lead_professions=("operations",),
        staffing_requirements=(
            StaffingRequirement(
                profession="operations",
                count=3,
                coverage="direct",
                outcome_area="delivery",
            ),
        ),
    )

    connection = open_postgres_connection(app_dsn, company_id=company_id)
    try:
        repository = PostgresStrategyRepository(connection)
        repository.put(original)
        assert repository.put(replacement) == replacement
        assert repository.get(replacement.goal_id) == replacement
    finally:
        connection.close()

    with psycopg.connect(postgres_dsn) as admin:
        counts = [
            admin.execute(
                f"SELECT count(*) FROM {table} WHERE company_id = %s AND goal_id = %s",
                (company_id, replacement.goal_id),
            ).fetchone()
            for table in _STRATEGY_TABLES[1:]
        ]
    assert counts == [(1,), (1,), (1,), (1,), (1,), (1,)]


def test_postgres_strategy_rejects_closed_vocabulary_values(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    connection = open_postgres_connection(_app_dsn(postgres_dsn), company_id=uuid4())
    try:
        repository = PostgresStrategyRepository(connection)
        with pytest.raises(psycopg.errors.CheckViolation):
            repository.put(StrategyRecord(goal_id="goal_health", health="improving"))
        with pytest.raises(psycopg.errors.CheckViolation):
            repository.put(StrategyRecord(goal_id="goal_shape", delivery_shape="squad"))
    finally:
        connection.close()


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(replace(_record("goal_score"), score=-0.1), id="score-below-range"),
        pytest.param(replace(_record("goal_score_high"), score=1.1), id="score-above-range"),
        pytest.param(replace(_record("goal_passes"), passes=-1), id="negative-passes"),
        pytest.param(replace(_record("goal_fails"), fails=-1), id="negative-fails"),
        pytest.param(replace(_record("goal_attempts"), attempts=-1), id="negative-attempts"),
        pytest.param(
            replace(_record("goal_revision"), task_outcome_revisions={"task_root": -1}),
            id="negative-task-outcome-revision",
        ),
    ],
)
def test_postgres_strategy_rejects_domain_invariant_violations(
    postgres_dsn: str, record: StrategyRecord
) -> None:
    _migrate(postgres_dsn)
    connection = open_postgres_connection(_app_dsn(postgres_dsn), company_id=uuid4())
    try:
        repository = PostgresStrategyRepository(connection)
        with pytest.raises(psycopg.errors.CheckViolation):
            repository.put(record)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "last_outcome_at",
    [
        pytest.param("2026-08-09T10:11:12", id="naive"),
        pytest.param("2026-08-09T10:11:12+05:30", id="non-utc"),
    ],
)
def test_postgres_strategy_rejects_non_utc_timestamps_at_its_boundary(
    postgres_dsn: str, last_outcome_at: str
) -> None:
    _migrate(postgres_dsn)
    connection = open_postgres_connection(_app_dsn(postgres_dsn), company_id=uuid4())
    try:
        repository = PostgresStrategyRepository(connection)
        with pytest.raises(ValueError, match="UTC RFC3339"):
            repository.put(
                StrategyRecord(goal_id="goal_timestamp", last_outcome_at=last_outcome_at)
            )
    finally:
        connection.close()


def test_postgres_strategy_is_isolated_by_company_guc(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    connection_a = open_postgres_connection(app_dsn, company_id=uuid4())
    connection_b = open_postgres_connection(app_dsn, company_id=uuid4())
    try:
        repository_a = PostgresStrategyRepository(connection_a)
        repository_b = PostgresStrategyRepository(connection_b)
        record_a = StrategyRecord(goal_id="goal_shared", title="Company A", evidence=["A"])
        record_b = StrategyRecord(goal_id="goal_shared", title="Company B", evidence=["B"])

        repository_a.put(record_a)
        repository_b.put(record_b)

        assert repository_a.get("goal_shared") == record_a
        assert repository_b.get("goal_shared") == record_b
        assert repository_a.all() == [record_a]
        assert repository_b.all() == [record_b]
    finally:
        connection_a.close()
        connection_b.close()
