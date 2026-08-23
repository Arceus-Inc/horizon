-- Decision.status is a closed Horizon model vocabulary.

ALTER TABLE horizon_decision
    ADD CONSTRAINT horizon_decision_status_check
    CHECK (status IN ('proposed', 'active', 'paused', 'done', 'archived'));
