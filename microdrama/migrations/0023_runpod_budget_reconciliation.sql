-- Budget-facing idempotency/evidence links; provider bucket rows stay in the billing ledger.
CREATE TABLE runpod_billing_budget_postings (
  allocation_id uuid PRIMARY KEY REFERENCES runpod_billing_allocations(allocation_id),
  account_id uuid REFERENCES budget_accounts(id),
  reservation_id uuid REFERENCES reservations(id),
  charge_id uuid REFERENCES charges(id),
  delta_micro_usd bigint NOT NULL,
  posting_state text NOT NULL CHECK (posting_state IN ('PROVIDER_REPORTED','NEGATIVE_EVIDENCE','RECOVERY_PENDING')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((posting_state='RECOVERY_PENDING') = (account_id IS NULL)),
  CHECK ((posting_state='PROVIDER_REPORTED') = (charge_id IS NOT NULL)),
  CHECK (charge_id IS NOT NULL OR reservation_id IS NULL)
);
CREATE TRIGGER runpod_billing_budget_postings_append_only
  BEFORE UPDATE OR DELETE ON runpod_billing_budget_postings
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_budget_postings_no_truncate
  BEFORE TRUNCATE ON runpod_billing_budget_postings
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_budget_postings_integer_numbers
  BEFORE INSERT OR UPDATE ON runpod_billing_budget_postings
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

CREATE TABLE runpod_billing_recovery_resolutions (
  allocation_id uuid PRIMARY KEY REFERENCES runpod_billing_allocations(allocation_id),
  assigned_episode_id uuid NOT NULL REFERENCES episodes(id),
  charge_id uuid REFERENCES charges(id),
  actor_ref text NOT NULL,
  reason text NOT NULL,
  resolved_at timestamptz NOT NULL
);
CREATE TRIGGER runpod_billing_recovery_resolutions_append_only
  BEFORE UPDATE OR DELETE ON runpod_billing_recovery_resolutions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_recovery_resolutions_no_truncate
  BEFORE TRUNCATE ON runpod_billing_recovery_resolutions
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_recovery_resolutions_integer_numbers
  BEFORE INSERT OR UPDATE ON runpod_billing_recovery_resolutions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

CREATE TABLE runpod_billing_budget_finalizations (
  bucket_observation_id uuid PRIMARY KEY REFERENCES runpod_billing_buckets(observation_id),
  verification_id uuid NOT NULL REFERENCES runpod_billing_invoice_verifications(verification_id),
  billed_amount_micro_usd bigint NOT NULL CHECK (billed_amount_micro_usd >= 0),
  recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER runpod_billing_budget_finalizations_append_only
  BEFORE UPDATE OR DELETE ON runpod_billing_budget_finalizations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_budget_finalizations_no_truncate
  BEFORE TRUNCATE ON runpod_billing_budget_finalizations
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_budget_finalizations_integer_numbers
  BEFORE INSERT OR UPDATE ON runpod_billing_budget_finalizations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
