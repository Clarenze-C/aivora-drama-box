-- Append-only Runpod billing query, bucket revision, allocation and invoice evidence.
CREATE TABLE runpod_billing_queries (
  query_id uuid PRIMARY KEY,
  provider_account_ref text NOT NULL,
  observed_at timestamptz NOT NULL,
  result_state text NOT NULL CHECK (result_state IN ('BUCKETS','EMPTY','UNKNOWN')),
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runpod_billing_buckets (
  observation_id uuid PRIMARY KEY,
  bucket_identity_sha256 text NOT NULL,
  revision integer NOT NULL CHECK (revision > 0),
  prior_observation_id uuid REFERENCES runpod_billing_buckets(observation_id),
  query_id uuid NOT NULL REFERENCES runpod_billing_queries(query_id),
  provider_account_ref text NOT NULL,
  pod_id text NOT NULL,
  bucket_start timestamptz NOT NULL,
  bucket_end timestamptz NOT NULL,
  bucket_size_seconds integer NOT NULL CHECK (bucket_size_seconds > 0),
  raw_response_sha256 text NOT NULL,
  observed_at timestamptz NOT NULL,
  currency text NOT NULL,
  total_amount_micro_usd bigint NOT NULL,
  gpu_amount_micro_usd bigint NOT NULL,
  cpu_amount_micro_usd bigint NOT NULL,
  disk_amount_micro_usd bigint NOT NULL,
  finality_state text NOT NULL CHECK (finality_state IN ('PENDING_PROVIDER_FINALITY','ALLOCATED_PROVIDER_REPORTED','INVOICE_VERIFIED','DISPUTED')),
  invoice_verification_id uuid,
  payload jsonb NOT NULL,
  UNIQUE (bucket_identity_sha256, revision),
  UNIQUE (bucket_identity_sha256, raw_response_sha256),
  CHECK (bucket_end > bucket_start)
);

CREATE TABLE runpod_billing_allocations (
  allocation_id uuid PRIMARY KEY,
  bucket_observation_id uuid NOT NULL REFERENCES runpod_billing_buckets(observation_id),
  bucket_identity_sha256 text NOT NULL,
  bucket_revision integer NOT NULL CHECK (bucket_revision > 0),
  component text NOT NULL CHECK (component IN ('GPU','CPU','DISK')),
  owner_kind text NOT NULL CHECK (owner_kind IN ('EPISODE','RECOVERY')),
  owner_id text NOT NULL,
  allocation_basis text NOT NULL CHECK (allocation_basis IN ('MEASURED_OVERLAP','STORAGE_OWNER','UNCOVERED')),
  delta_micro_usd bigint NOT NULL,
  payload jsonb NOT NULL,
  UNIQUE (bucket_observation_id, component, owner_kind, owner_id, allocation_basis)
);

CREATE TABLE runpod_billing_invoice_verifications (
  verification_id uuid PRIMARY KEY,
  bucket_observation_id uuid NOT NULL REFERENCES runpod_billing_buckets(observation_id),
  evidence_sha256 text NOT NULL,
  verified_at timestamptz NOT NULL,
  result text NOT NULL CHECK (result IN ('MATCHED','MISMATCHED')),
  payload jsonb NOT NULL
);

-- Explicit, prospective disk ownership. A transfer closes the previous interval and
-- starts another; historical storage charges remain with their original owner.
CREATE TABLE pod_storage_ownership (
  id uuid PRIMARY KEY,
  provider text NOT NULL,
  pod_id text NOT NULL,
  owner_episode_id uuid NOT NULL REFERENCES episodes(id),
  valid_from timestamptz NOT NULL,
  valid_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (valid_until IS NULL OR valid_until > valid_from),
  EXCLUDE USING gist (provider WITH =, pod_id WITH =,
    tstzrange(valid_from, COALESCE(valid_until, 'infinity'::timestamptz), '[)') WITH &&)
);
CREATE TRIGGER pod_storage_ownership_no_delete BEFORE DELETE ON pod_storage_ownership
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER pod_storage_ownership_identity_immutable BEFORE UPDATE ON pod_storage_ownership
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('provider','pod_id','owner_episode_id','valid_from');
CREATE TRIGGER pod_storage_ownership_no_truncate BEFORE TRUNCATE ON pod_storage_ownership
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER pod_storage_ownership_integer_numbers BEFORE INSERT OR UPDATE ON pod_storage_ownership
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

CREATE TRIGGER runpod_billing_queries_append_only BEFORE UPDATE OR DELETE ON runpod_billing_queries
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_queries_no_truncate BEFORE TRUNCATE ON runpod_billing_queries
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_queries_integer_numbers BEFORE INSERT OR UPDATE ON runpod_billing_queries
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
CREATE TRIGGER runpod_billing_buckets_append_only BEFORE UPDATE OR DELETE ON runpod_billing_buckets
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_buckets_no_truncate BEFORE TRUNCATE ON runpod_billing_buckets
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_buckets_integer_numbers BEFORE INSERT OR UPDATE ON runpod_billing_buckets
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
CREATE TRIGGER runpod_billing_allocations_append_only BEFORE UPDATE OR DELETE ON runpod_billing_allocations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_allocations_no_truncate BEFORE TRUNCATE ON runpod_billing_allocations
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_allocations_integer_numbers BEFORE INSERT OR UPDATE ON runpod_billing_allocations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
CREATE TRIGGER runpod_billing_invoice_append_only BEFORE UPDATE OR DELETE ON runpod_billing_invoice_verifications
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_invoice_no_truncate BEFORE TRUNCATE ON runpod_billing_invoice_verifications
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER runpod_billing_invoice_integer_numbers BEFORE INSERT OR UPDATE ON runpod_billing_invoice_verifications
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
