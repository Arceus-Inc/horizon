-- Horizon strategy records preserve their typed scalar fields in one tenant-scoped row.

CREATE TABLE horizon_strategy_record (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    goal_id text NOT NULL,
    title text NOT NULL DEFAULT '',
    score double precision NOT NULL DEFAULT 0,
    health text NOT NULL DEFAULT 'unknown',
    metric text,
    target text,
    decision_id text,
    task_id text,
    root_task_id text,
    team_id text,
    lead_id text,
    delivery_shape text NOT NULL DEFAULT 'single',
    passes integer NOT NULL DEFAULT 0,
    fails integer NOT NULL DEFAULT 0,
    last_outcome_at timestamptz,
    done boolean NOT NULL DEFAULT false,
    attempts integer NOT NULL DEFAULT 0,
    needs_recovery boolean NOT NULL DEFAULT false,
    last_diagnostic text NOT NULL DEFAULT '',
    position bigint GENERATED ALWAYS AS IDENTITY,
    PRIMARY KEY (company_id, goal_id),
    CONSTRAINT horizon_strategy_record_health_check
        CHECK (health IN ('on_track', 'drifting', 'blocked', 'unknown')),
    CONSTRAINT horizon_strategy_record_delivery_shape_check
        CHECK (delivery_shape IN ('single', 'team'))
);

CREATE TABLE horizon_strategy_evidence (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    goal_id text NOT NULL,
    position bigint NOT NULL,
    value text NOT NULL,
    PRIMARY KEY (company_id, goal_id, position),
    FOREIGN KEY (company_id, goal_id)
        REFERENCES horizon_strategy_record (company_id, goal_id) ON DELETE CASCADE
);

CREATE TABLE horizon_strategy_task (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    goal_id text NOT NULL,
    position bigint NOT NULL,
    task_id text NOT NULL,
    PRIMARY KEY (company_id, goal_id, position),
    FOREIGN KEY (company_id, goal_id)
        REFERENCES horizon_strategy_record (company_id, goal_id) ON DELETE CASCADE
);

CREATE TABLE horizon_strategy_task_outcome (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    goal_id text NOT NULL,
    task_id text NOT NULL,
    outcome text,
    revision integer,
    PRIMARY KEY (company_id, goal_id, task_id),
    FOREIGN KEY (company_id, goal_id)
        REFERENCES horizon_strategy_record (company_id, goal_id) ON DELETE CASCADE
);

CREATE TABLE horizon_strategy_outcome_event (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    goal_id text NOT NULL,
    position bigint NOT NULL,
    event_id text NOT NULL,
    PRIMARY KEY (company_id, goal_id, position),
    FOREIGN KEY (company_id, goal_id)
        REFERENCES horizon_strategy_record (company_id, goal_id) ON DELETE CASCADE
);

CREATE TABLE horizon_strategy_lead_profession (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    goal_id text NOT NULL,
    position bigint NOT NULL,
    profession text NOT NULL,
    PRIMARY KEY (company_id, goal_id, position),
    FOREIGN KEY (company_id, goal_id)
        REFERENCES horizon_strategy_record (company_id, goal_id) ON DELETE CASCADE
);

CREATE TABLE horizon_strategy_staffing_requirement (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    goal_id text NOT NULL,
    position bigint NOT NULL,
    profession text NOT NULL,
    count integer NOT NULL,
    coverage text NOT NULL,
    outcome_area text,
    PRIMARY KEY (company_id, goal_id, position),
    FOREIGN KEY (company_id, goal_id)
        REFERENCES horizon_strategy_record (company_id, goal_id) ON DELETE CASCADE,
    CONSTRAINT horizon_strategy_staffing_requirement_count_check CHECK (count >= 1),
    CONSTRAINT horizon_strategy_staffing_requirement_coverage_check
        CHECK (coverage IN ('direct', 'subtree'))
);

ALTER TABLE horizon_strategy_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_strategy_record FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_strategy_record_company_isolation ON horizon_strategy_record
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_strategy_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_strategy_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_strategy_evidence_company_isolation ON horizon_strategy_evidence
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_strategy_task ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_strategy_task FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_strategy_task_company_isolation ON horizon_strategy_task
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_strategy_task_outcome ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_strategy_task_outcome FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_strategy_task_outcome_company_isolation ON horizon_strategy_task_outcome
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_strategy_outcome_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_strategy_outcome_event FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_strategy_outcome_event_company_isolation ON horizon_strategy_outcome_event
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_strategy_lead_profession ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_strategy_lead_profession FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_strategy_lead_profession_company_isolation ON horizon_strategy_lead_profession
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

ALTER TABLE horizon_strategy_staffing_requirement ENABLE ROW LEVEL SECURITY;
ALTER TABLE horizon_strategy_staffing_requirement FORCE ROW LEVEL SECURITY;
CREATE POLICY horizon_strategy_staffing_requirement_company_isolation ON horizon_strategy_staffing_requirement
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX horizon_strategy_record_company_position
    ON horizon_strategy_record (company_id, position);
