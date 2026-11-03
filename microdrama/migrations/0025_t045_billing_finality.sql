-- T045 finality (R0): durable lease timing, close-once storage ownership, widened
-- bucket replay keys, per-observation invoice uniques, and the period-evidence and
-- skipped-bucket tables (R4/R5). Persistence only; no guardian contract change.

-- Lease timing (G13): each timestamp is written at most once by the application and
-- guarded here. The write itself (e.g. create_requested_at committed before create_pod)
-- lives in the rendering services.
ALTER TABLE pod_leases
  ADD COLUMN create_requested_at timestamptz,
  ADD COLUMN compute_window_start_at timestamptz,
  ADD COLUMN compute_window_end_at timestamptz,
  ADD COLUMN terminate_verified_at timestamptz,
  ADD COLUMN provider_account_ref text,
  ADD COLUMN next_finality_check_at timestamptz;

CREATE FUNCTION md_pod_leases_timestamps_set_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.create_requested_at IS NOT NULL
     AND NEW.create_requested_at IS DISTINCT FROM OLD.create_requested_at THEN
    RAISE EXCEPTION 'pod_leases.create_requested_at is set once'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.compute_window_start_at IS NOT NULL
     AND NEW.compute_window_start_at IS DISTINCT FROM OLD.compute_window_start_at THEN
    RAISE EXCEPTION 'pod_leases.compute_window_start_at is set once'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.compute_window_end_at IS NOT NULL
     AND NEW.compute_window_end_at IS DISTINCT FROM OLD.compute_window_end_at THEN
    RAISE EXCEPTION 'pod_leases.compute_window_end_at is set once'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.terminate_verified_at IS NOT NULL
     AND NEW.terminate_verified_at IS DISTINCT FROM OLD.terminate_verified_at THEN
    RAISE EXCEPTION 'pod_leases.terminate_verified_at is set once'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER pod_leases_timestamps_set_once BEFORE UPDATE ON pod_leases
  FOR EACH ROW EXECUTE FUNCTION md_pod_leases_timestamps_set_once();

-- Storage ownership (G3/S8): the creating lease is recorded when the row is written and
-- never rewritten; the row closes (valid_until NULL -> instant) exactly once (S5).
ALTER TABLE pod_storage_ownership
  ADD COLUMN creating_lease_id uuid REFERENCES pod_leases(id);
CREATE TRIGGER pod_storage_ownership_creating_lease_immutable BEFORE UPDATE ON pod_storage_ownership
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('creating_lease_id');
CREATE FUNCTION md_storage_ownership_close_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.valid_until IS NOT NULL AND NEW.valid_until IS DISTINCT FROM OLD.valid_until THEN
    RAISE EXCEPTION 'pod_storage_ownership.valid_until closes exactly once'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER pod_storage_ownership_close_once BEFORE UPDATE ON pod_storage_ownership
  FOR EACH ROW EXECUTE FUNCTION md_storage_ownership_close_once();

-- Bucket replay keys (B3): an internally written INVOICE_VERIFIED revision repeats the
-- provider's raw hash on purpose; the uniqueness now includes the finality state. The
-- real constraint name is resolved from the catalog, not assumed.
DO $$
DECLARE cname text;
BEGIN
  SELECT conname INTO cname FROM pg_constraint
  WHERE conrelid = 'runpod_billing_buckets'::regclass AND contype = 'u'
    AND pg_get_constraintdef(oid)
        = 'UNIQUE (bucket_identity_sha256, raw_response_sha256)';
  IF cname IS NULL THEN
    RAISE EXCEPTION 'runpod_billing_buckets unique(bucket_identity_sha256, raw_response_sha256) not found';
  END IF;
  EXECUTE format('ALTER TABLE runpod_billing_buckets DROP CONSTRAINT %I', cname);
END $$;
ALTER TABLE runpod_billing_buckets
  ADD CONSTRAINT runpod_billing_buckets_identity_raw_finality_unique
  UNIQUE (bucket_identity_sha256, raw_response_sha256, finality_state);

-- Invoice evidence (G6): one verification per bucket observation, and one use of an
-- evidence hash per bucket identity. These are the replay backstops behind R6.
-- T045-FIX A-N6: the identity column carries the verified bucket's identity from the
-- start — pre-existing rows are backfilled from their bucket row, and the blanket ''
-- default is dropped so a future insert cannot silently claim the empty identity.
ALTER TABLE runpod_billing_invoice_verifications
  ADD COLUMN bucket_identity_sha256 text NOT NULL DEFAULT '';
-- The table is append-only (0022), so the one-time backfill runs with its mutation
-- guard disabled; the guard is restored immediately after.
ALTER TABLE runpod_billing_invoice_verifications
  DISABLE TRIGGER runpod_billing_invoice_append_only;
UPDATE runpod_billing_invoice_verifications v
SET bucket_identity_sha256 = b.bucket_identity_sha256
FROM runpod_billing_buckets b
WHERE b.observation_id = v.bucket_observation_id
  AND v.bucket_identity_sha256 = '';
ALTER TABLE runpod_billing_invoice_verifications
  ENABLE TRIGGER runpod_billing_invoice_append_only;
ALTER TABLE runpod_billing_invoice_verifications
  ALTER COLUMN bucket_identity_sha256 DROP DEFAULT;
ALTER TABLE runpod_billing_invoice_verifications
  ADD CONSTRAINT runpod_billing_invoice_verifications_observation_unique
  UNIQUE (bucket_observation_id);
ALTER TABLE runpod_billing_invoice_verifications
  ADD CONSTRAINT runpod_billing_invoice_verifications_identity_evidence_unique
  UNIQUE (bucket_identity_sha256, evidence_sha256);

-- Period-level invoice evidence (R5): pod-scoped, append-only; a supersede is a new row
-- that names and audits the row it replaces.
CREATE TABLE runpod_billing_period_evidence (
  period_evidence_id uuid PRIMARY KEY,
  provider_account_ref text NOT NULL,
  pod_id text NOT NULL,
  period_start timestamptz NOT NULL,
  period_end timestamptz NOT NULL,
  amount_micro_usd bigint NOT NULL CHECK (amount_micro_usd >= 0),
  currency text NOT NULL,
  evidence_sha256 text NOT NULL,
  evidence_source text NOT NULL CHECK (evidence_source IN ('INVOICE', 'CONSOLE')),
  observed_at timestamptz NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('MATCHED', 'MATCHED_ZERO', 'MISMATCHED')),
  bucket_sum_micro_usd bigint NOT NULL,
  supersedes_evidence_id uuid REFERENCES runpod_billing_period_evidence(period_evidence_id),
  actor_ref text,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (period_end > period_start),
  -- T045-FIX A-N6: MATCHED_ZERO is a zero-amount outcome by definition.
  CHECK (outcome <> 'MATCHED_ZERO' OR amount_micro_usd = 0),
  CHECK ((supersedes_evidence_id IS NULL) = (actor_ref IS NULL AND reason IS NULL)),
  CHECK (actor_ref IS NULL OR actor_ref <> ''),
  CHECK (reason IS NULL OR reason <> ''),
  UNIQUE (provider_account_ref, pod_id, period_start, period_end, evidence_sha256)
);
CREATE TRIGGER runpod_billing_period_evidence_append_only
  BEFORE UPDATE OR DELETE ON runpod_billing_period_evidence
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_period_evidence_no_truncate
  BEFORE TRUNCATE ON runpod_billing_period_evidence
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_period_evidence_integer_numbers
  BEFORE INSERT OR UPDATE ON runpod_billing_period_evidence
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

-- Open buckets an ingest deliberately did not store (R4/S4): they are pending provider
-- finality, not zero, and refuse period verification until they close.
CREATE TABLE runpod_billing_query_skipped_buckets (
  skip_id uuid PRIMARY KEY,
  query_id uuid NOT NULL REFERENCES runpod_billing_queries(query_id),
  provider_account_ref text NOT NULL,
  pod_id text NOT NULL,
  bucket_start timestamptz NOT NULL,
  bucket_end timestamptz NOT NULL,
  bucket_size_seconds integer NOT NULL CHECK (bucket_size_seconds > 0),
  observed_at timestamptz NOT NULL,
  reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (bucket_end > bucket_start),
  UNIQUE (query_id, pod_id, bucket_start, bucket_end)
);
CREATE TRIGGER runpod_billing_query_skipped_buckets_append_only
  BEFORE UPDATE OR DELETE ON runpod_billing_query_skipped_buckets
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_query_skipped_buckets_no_truncate
  BEFORE TRUNCATE ON runpod_billing_query_skipped_buckets
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_query_skipped_buckets_integer_numbers
  BEFORE INSERT OR UPDATE ON runpod_billing_query_skipped_buckets
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

-- T045-FIX A-S2: the finality retry attempt count behind the doubling backoff. It is
-- freely rewritable (reset to 0 once BILLED); the four timestamps above stay set-once.
ALTER TABLE pod_leases
  ADD COLUMN finality_attempts integer NOT NULL DEFAULT 0 CHECK (finality_attempts >= 0);

-- T045-FIX A-S1: the audited operator resolution for a create that was sent but never
-- produced a Pod. One resolution per lease, append-only, with the attestation (actor,
-- reason, evidence sha) and its instant. It posts the BILLED 0 settlement.
-- T045-FIX RR-S4: a Pod that appears later contradicts the resolution. The attestation
-- columns stay immutable; the contradiction columns are set exactly once (NULL -> value)
-- and never rewritten or cleared. DELETE stays forbidden.
CREATE TABLE runpod_podless_create_resolutions (
  resolution_id uuid PRIMARY KEY,
  lease_id uuid NOT NULL UNIQUE REFERENCES pod_leases(id),
  actor_ref text NOT NULL CHECK (actor_ref <> ''),
  reason text NOT NULL CHECK (reason <> ''),
  evidence_sha256 text NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
  resolved_at timestamptz NOT NULL,
  contradicted_at timestamptz,
  contradicted_pod_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION md_podless_resolution_contradict_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.contradicted_at IS NOT NULL
     AND NEW.contradicted_at IS DISTINCT FROM OLD.contradicted_at THEN
    RAISE EXCEPTION 'runpod_podless_create_resolutions.contradicted_at is set once'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.contradicted_pod_id IS NOT NULL
     AND NEW.contradicted_pod_id IS DISTINCT FROM OLD.contradicted_pod_id THEN
    RAISE EXCEPTION 'runpod_podless_create_resolutions.contradicted_pod_id is set once'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.contradicted_at IS NOT NULL AND NEW.contradicted_pod_id IS NULL THEN
    RAISE EXCEPTION 'a contradicted podless resolution names its Pod'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.resolution_id, NEW.lease_id, NEW.actor_ref, NEW.reason, NEW.evidence_sha256,
      NEW.resolved_at, NEW.created_at) IS DISTINCT FROM
     (OLD.resolution_id, OLD.lease_id, OLD.actor_ref, OLD.reason, OLD.evidence_sha256,
      OLD.resolved_at, OLD.created_at) THEN
    RAISE EXCEPTION 'runpod_podless_create_resolutions is append-only'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER runpod_podless_create_resolutions_update_guard
  BEFORE UPDATE ON runpod_podless_create_resolutions
  FOR EACH ROW EXECUTE FUNCTION md_podless_resolution_contradict_once();
CREATE TRIGGER runpod_podless_create_resolutions_no_delete
  BEFORE DELETE ON runpod_podless_create_resolutions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_podless_create_resolutions_no_truncate
  BEFORE TRUNCATE ON runpod_podless_create_resolutions
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_podless_create_resolutions_integer_numbers
  BEFORE INSERT OR UPDATE ON runpod_podless_create_resolutions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

-- T045-FIX B-S4: the per-Pod billing-ingest backoff. One row per owned Pod, updated
-- after every ingest attempt (stored, replayed or failed); rows are never deleted.
CREATE TABLE runpod_billing_ingest_backoff (
  pod_id text PRIMARY KEY,
  provider_account_ref text NOT NULL,
  next_ingest_at timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  post_terminate_ingest_done boolean NOT NULL DEFAULT false,
  last_outcome text NOT NULL CHECK (last_outcome IN
    ('STORED','REPLAYED','SKIPPED_OPEN','FAILED')),
  last_detail text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER runpod_billing_ingest_backoff_no_delete
  BEFORE DELETE ON runpod_billing_ingest_backoff
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_ingest_backoff_no_truncate
  BEFORE TRUNCATE ON runpod_billing_ingest_backoff
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_ingest_backoff_integer_numbers
  BEFORE INSERT OR UPDATE ON runpod_billing_ingest_backoff
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
