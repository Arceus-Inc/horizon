"""Postgres ProposalRepository contract tests, including real FORCE RLS isolation."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest

from horizon.generation import CandidateGoal, DirectionBrief, Proposal
from horizon.ports import ProposalRepository
from horizon.store.postgres import (
    PostgresProposalRepository,
    apply_migrations,
    open_postgres_connection,
)

_PROPOSAL_TABLES = (
    "horizon_proposal",
    "horizon_proposal_brief",
    "horizon_proposal_brief_risk",
    "horizon_proposal_brief_goal",
    "horizon_proposal_brief_evidence_ref",
)


def _migrate(postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        apply_migrations(connection)


def _app_dsn(postgres_dsn: str) -> str:
    with psycopg.connect(postgres_dsn, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = "
            "'horizon_proposal_app') THEN CREATE ROLE horizon_proposal_app "
            "LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO horizon_proposal_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON " + ", ".join(_PROPOSAL_TABLES) + " "
            "TO horizon_proposal_app"
        )
    return postgres_dsn.replace("user=postgres", "user=horizon_proposal_app")


def _brief() -> DirectionBrief:
    return DirectionBrief(
        candidate_id="candidate_1",
        recommendation="Concentrate investment in the top region",
        rationale="Renewals and expansion support it.",
        confidence=0.85,
        risks=["Data may be stale", "Expansion could slow"],
        candidate_goals=[
            CandidateGoal(
                title="Quantify retained revenue",
                metric="Net revenue retention",
                target="120%",
                rationale="Tie the investment to the durable outcome.",
                score=0.9,
            ),
            CandidateGoal(
                title="Improve expansion conversion",
                metric="Conversion rate",
                target="40%",
                rationale="Turn the investment into repeatable growth.",
                score=0.7,
            ),
        ],
        evidence_refs=["evidence_1", "evidence_2"],
    )


def _proposal(proposal_id: str = "proposal_1") -> Proposal:
    return Proposal(
        id=proposal_id,
        status="approved",
        brief=_brief(),
        decision_statement="Concentrate investment in the top region",
        decision_rationale="The evidence supports durable expansion.",
        created_at="2026-08-09T10:11:12+00:00",
        decided_by="ceo_1",
        decided_at="2026-08-10T10:11:12+00:00",
        linked_decision_id="decision_1",
        note="Approved after finance review.",
    )


def test_postgres_proposals_round_trip_every_field_after_restart(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    company_id = uuid4()
    proposal = _proposal()

    first_connection = open_postgres_connection(app_dsn, company_id=company_id)
    try:
        repository: ProposalRepository = PostgresProposalRepository(first_connection)
        assert repository.put(proposal) == proposal
    finally:
        first_connection.close()

    second_connection = open_postgres_connection(app_dsn, company_id=company_id)
    try:
        repository = PostgresProposalRepository(second_connection)
        assert repository.get(proposal.id) == proposal
    finally:
        second_connection.close()


def test_postgres_proposals_keep_insert_order_and_exact_upsert_behavior(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    connection = open_postgres_connection(_app_dsn(postgres_dsn), company_id=uuid4())
    try:
        repository = PostgresProposalRepository(connection)
        second = Proposal(id="proposal_2", decision_statement="Second")
        first = Proposal(id="proposal_1", decision_statement="First")
        updated = Proposal(id="proposal_2", status="rejected", note="Not now")

        assert repository.put(second) is second
        assert repository.put(first) is first
        assert repository.put(updated) is updated
        assert repository.all() == [updated, first]
    finally:
        connection.close()


def test_postgres_proposal_replacement_removes_stale_child_rows(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    company_id = uuid4()
    original = _proposal()
    replacement = replace(
        original,
        brief=DirectionBrief(
            candidate_id="candidate_2",
            recommendation="Fund the renewal automation",
            rationale="It removes the renewal bottleneck.",
            confidence=0.75,
            risks=["Adoption may lag"],
            candidate_goals=[
                CandidateGoal(
                    title="Launch renewal automation",
                    metric="Automated renewals",
                    target="80%",
                    rationale="Focus on the operational bottleneck.",
                    score=0.8,
                )
            ],
            evidence_refs=["evidence_new"],
        ),
    )

    connection = open_postgres_connection(app_dsn, company_id=company_id)
    try:
        repository = PostgresProposalRepository(connection)
        repository.put(original)
        assert repository.put(replacement) == replacement
        assert repository.get(replacement.id) == replacement
    finally:
        connection.close()

    with psycopg.connect(postgres_dsn) as admin:
        counts = [
            admin.execute(
                f"SELECT count(*) FROM {table} WHERE company_id = %s AND proposal_id = %s",
                (company_id, replacement.id),
            ).fetchone()
            for table in _PROPOSAL_TABLES[1:]
        ]
    assert counts == [(1,), (1,), (1,), (1,)]


@pytest.mark.parametrize(
    "proposal",
    [
        pytest.param(Proposal(id="bad_status", status="pending"), id="status"),
        pytest.param(
            Proposal(id="bad_confidence", brief=replace(_brief(), confidence=1.1)),
            id="brief-confidence",
        ),
        pytest.param(
            Proposal(
                id="bad_goal_score",
                brief=replace(
                    _brief(),
                    candidate_goals=[replace(_brief().candidate_goals[0], score=-0.1)],
                ),
            ),
            id="candidate-goal-score",
        ),
    ],
)
def test_postgres_proposals_reject_domain_constraint_violations(
    postgres_dsn: str, proposal: Proposal
) -> None:
    _migrate(postgres_dsn)
    connection = open_postgres_connection(_app_dsn(postgres_dsn), company_id=uuid4())
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            PostgresProposalRepository(connection).put(proposal)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "proposal",
    [
        pytest.param(Proposal(id="naive_created", created_at="2026-08-09T10:11:12"), id="created"),
        pytest.param(
            Proposal(id="non_utc_decided", decided_at="2026-08-09T10:11:12+05:30"),
            id="decided",
        ),
    ],
)
def test_postgres_proposals_reject_non_utc_timestamps_at_their_boundary(
    postgres_dsn: str, proposal: Proposal
) -> None:
    _migrate(postgres_dsn)
    connection = open_postgres_connection(_app_dsn(postgres_dsn), company_id=uuid4())
    try:
        with pytest.raises(ValueError, match="UTC RFC3339"):
            PostgresProposalRepository(connection).put(proposal)
    finally:
        connection.close()


def test_postgres_proposal_tables_force_company_rls(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    with psycopg.connect(postgres_dsn) as admin:
        rows = admin.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(%s) ORDER BY relname",
            (list(_PROPOSAL_TABLES),),
        ).fetchall()

    assert rows == [(table, True, True) for table in sorted(_PROPOSAL_TABLES)]


def test_postgres_proposals_are_isolated_by_company_guc(postgres_dsn: str) -> None:
    _migrate(postgres_dsn)
    app_dsn = _app_dsn(postgres_dsn)
    connection_a = open_postgres_connection(app_dsn, company_id=uuid4())
    connection_b = open_postgres_connection(app_dsn, company_id=uuid4())
    try:
        repository_a = PostgresProposalRepository(connection_a)
        repository_b = PostgresProposalRepository(connection_b)
        proposal_a = Proposal(id="proposal_shared", decision_statement="Company A")
        proposal_b = Proposal(id="proposal_shared", decision_statement="Company B")

        repository_a.put(proposal_a)
        repository_b.put(proposal_b)

        assert repository_a.get("proposal_shared") == proposal_a
        assert repository_b.get("proposal_shared") == proposal_b
        assert repository_a.all() == [proposal_a]
        assert repository_b.all() == [proposal_b]
    finally:
        connection_a.close()
        connection_b.close()
