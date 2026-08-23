-- Horizon proposals retain their approval state and optional typed analyst brief.

CREATE TABLE horizon_proposal (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id text NOT NULL,
    status text NOT NULL DEFAULT 'proposed',
    decision_statement text NOT NULL DEFAULT '',
    decision_rationale text NOT NULL DEFAULT '',
    created_at timestamptz,
    decided_by text,
    decided_at timestamptz,
    linked_decision_id text,
    note text NOT NULL DEFAULT '',
    position bigint GENERATED ALWAYS AS IDENTITY,
    PRIMARY KEY (company_id, id),
    CONSTRAINT horizon_proposal_status_check
        CHECK (status IN ('proposed', 'approved', 'rejected', 'superseded')),
    CONSTRAINT horizon_proposal_state_proof_check CHECK (
        (status = 'approved' AND decided_by IS NOT NULL AND decided_at IS NOT NULL
            AND linked_decision_id IS NOT NULL)
        OR (status = 'rejected' AND decided_by IS NOT NULL AND decided_at IS NOT NULL
            AND linked_decision_id IS NULL)
        OR (status = 'proposed' AND decided_by IS NULL AND decided_at IS NULL
            AND linked_decision_id IS NULL)
        OR status = 'superseded'
    ),
    FOREIGN KEY (company_id, linked_decision_id)
        REFERENCES horizon_decision (company_id, id)
);

CREATE TABLE horizon_proposal_brief (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    proposal_id text NOT NULL,
    candidate_id text NOT NULL,
    recommendation text NOT NULL,
    rationale text NOT NULL,
    confidence double precision NOT NULL,
    PRIMARY KEY (company_id, proposal_id),
    FOREIGN KEY (company_id, proposal_id)
        REFERENCES horizon_proposal (company_id, id) ON DELETE CASCADE,
    CONSTRAINT horizon_proposal_brief_confidence_check CHECK (confidence BETWEEN 0 AND 1)
);

CREATE TABLE horizon_proposal_brief_risk (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    proposal_id text NOT NULL,
    position bigint NOT NULL,
    value text NOT NULL,
    PRIMARY KEY (company_id, proposal_id, position),
    FOREIGN KEY (company_id, proposal_id)
        REFERENCES horizon_proposal_brief (company_id, proposal_id) ON DELETE CASCADE
);

CREATE TABLE horizon_proposal_brief_goal (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    proposal_id text NOT NULL,
    position bigint NOT NULL,
    title text NOT NULL,
    metric text NOT NULL,
    target text NOT NULL,
    rationale text NOT NULL,
    score double precision NOT NULL,
    PRIMARY KEY (company_id, proposal_id, position),
    FOREIGN KEY (company_id, proposal_id)
        REFERENCES horizon_proposal_brief (company_id, proposal_id) ON DELETE CASCADE,
    CONSTRAINT horizon_proposal_brief_goal_score_check CHECK (score BETWEEN 0 AND 1)
);

CREATE TABLE horizon_proposal_brief_evidence_ref (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    proposal_id text NOT NULL,
    position bigint NOT NULL,
    evidence_ref text NOT NULL,
    PRIMARY KEY (company_id, proposal_id, position),
    FOREIGN KEY (company_id, proposal_id)
        REFERENCES horizon_proposal_brief (company_id, proposal_id) ON DELETE CASCADE
);

ALTER TABLE horizon_proposal ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_proposal FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_proposal_company_isolation ON horizon_proposal
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_proposal_brief ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_proposal_brief FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_proposal_brief_company_isolation ON horizon_proposal_brief
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_proposal_brief_risk ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_proposal_brief_risk FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_proposal_brief_risk_company_isolation ON horizon_proposal_brief_risk
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_proposal_brief_goal ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_proposal_brief_goal FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_proposal_brief_goal_company_isolation ON horizon_proposal_brief_goal
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_proposal_brief_evidence_ref ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_proposal_brief_evidence_ref FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_proposal_brief_evidence_ref_company_isolation
    ON horizon_proposal_brief_evidence_ref
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX horizon_proposal_company_position ON horizon_proposal (company_id, position);
