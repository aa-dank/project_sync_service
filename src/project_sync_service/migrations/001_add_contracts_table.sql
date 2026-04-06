-- Migration 001: Create contracts table
-- Idempotent: safe to re-run (uses IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS contracts (
    id                                  SERIAL PRIMARY KEY,
    fmp_id_primary                      INTEGER UNIQUE,                -- FileMaker ID_Primary
    contract_number                     INTEGER,
    project_id                          INTEGER REFERENCES projects(id),
    -- Dates
    contract_date                       DATE,
    ntp_start_date                      DATE,                          -- Notice to Proceed start
    beneficial_occupancy_date           DATE,
    substantial_completion_date         DATE,
    certificate_of_occupancy_date       DATE,                          -- NOTE: source is Text in FM
    noc_completion_date                 DATE,                          -- Notice of Completion
    noc_recorded_date                   DATE,
    termination_date                    DATE,
    bid_date                            DATE,
    change_order_revised_expected_end   DATE,                          -- calculated in FM
    -- Financial
    cost_estimate                       NUMERIC(14,2),
    original_contract_cost              NUMERIC(14,2),
    change_order_total                  NUMERIC(14,2),                 -- calculated in FM
    change_order_revised_cost           NUMERIC(14,2),                 -- calculated in FM
    account_number                      VARCHAR,
    funding_number                      VARCHAR,                       -- CFRNumber in FM
    -- Duration (days)
    original_project_duration           INTEGER,
    change_order_time_total             INTEGER,                       -- calculated in FM
    change_order_revised_duration       INTEGER,                       -- calculated in FM
    -- Parties & description
    contractor_org_name                 VARCHAR,
    executive_design_org_name           VARCHAR,                       -- from related "Contracts Architect" TO
    scope_description                   TEXT,                          -- BFDescriptionofWork in FM
    -- Sync metadata
    last_synced_at                      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contracts_project_id ON contracts(project_id);
CREATE INDEX IF NOT EXISTS idx_contracts_fmp_id ON contracts(fmp_id_primary);
