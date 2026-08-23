-- Horizon decisions are tenant-scoped through the same company GUC and FORCE RLS convention as Chorus.

CREATE TABLE horizon_decision (
    company_id uuid NOT NULL DEFAULT (NULLIF(current_setting('app.company_id', true), ''))::uuid,
    id text NOT NULL,
    statement text NOT NULL,
    status text NOT NULL,
    owner text,
    rationale text NOT NULL,
    goal_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
    position bigint GENERATED ALWAYS AS IDENTITY,
    PRIMARY KEY (company_id, id)
);

ALTER TABLE horizon_decision ENABLE ROW LEVEL SECURITY;

ALTER TABLE horizon_decision FORCE ROW LEVEL SECURITY;

CREATE POLICY horizon_decision_company_isolation ON horizon_decision
    USING (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid))
    WITH CHECK (company_id = (SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));

CREATE INDEX horizon_decision_company_position ON horizon_decision (company_id, position);
