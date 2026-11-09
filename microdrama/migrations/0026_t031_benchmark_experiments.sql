-- T031 local experiment coordination; canonical budget/jobs remain authoritative.
CREATE TABLE benchmark_experiments (
 experiment_id uuid PRIMARY KEY, episode_id uuid NOT NULL REFERENCES episodes(id),
 account_id uuid NOT NULL REFERENCES budget_accounts(id), plan_sha256 text NOT NULL CHECK(plan_sha256 ~ '^[0-9a-f]{64}$'),
 plan jsonb NOT NULL, sealed_sha256 text CHECK(sealed_sha256 ~ '^[0-9a-f]{64}$'),
 execution_state text NOT NULL DEFAULT 'PREPARED', execution_outcome text,
 cleanup_state text NOT NULL DEFAULT 'NOT_REQUIRED', billing_state text NOT NULL DEFAULT 'PENDING_PROVIDER_FINALITY',
 cap_micro_usd bigint NOT NULL CHECK(cap_micro_usd BETWEEN 1 AND 8000000),
 gpu_limit_ms bigint NOT NULL CHECK(gpu_limit_ms BETWEEN 1 AND 14400000), hard_stop timestamptz,
 revision integer NOT NULL DEFAULT 0 CHECK(revision>=0), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(episode_id,plan_sha256)
);
CREATE TRIGGER benchmark_experiments_identity BEFORE UPDATE ON benchmark_experiments FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('experiment_id','episode_id','account_id','plan_sha256','plan','cap_micro_usd','gpu_limit_ms');
CREATE TABLE benchmark_samples (
 experiment_id uuid NOT NULL REFERENCES benchmark_experiments(experiment_id), sample_id text NOT NULL, shot_id text NOT NULL,
 repeat integer NOT NULL CHECK(repeat BETWEEN 1 AND 3), seed bigint NOT NULL,
 input jsonb NOT NULL, input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[0-9a-f]{64}$'), state text NOT NULL DEFAULT 'PLANNED',
 job_id uuid REFERENCES jobs(id), operation_id uuid REFERENCES provider_operations(id), reservation_id uuid REFERENCES reservations(id), acquisition_id uuid,
 output jsonb, coverage jsonb, request jsonb,
 PRIMARY KEY(experiment_id,sample_id), UNIQUE(experiment_id,shot_id,repeat), UNIQUE(experiment_id,seed)
);
CREATE TRIGGER benchmark_samples_identity BEFORE UPDATE ON benchmark_samples FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('experiment_id','sample_id','shot_id','repeat','seed','input','input_sha256');
CREATE TABLE benchmark_seals (
 experiment_id uuid PRIMARY KEY REFERENCES benchmark_experiments(experiment_id), manifest jsonb NOT NULL,
 sealed_sha256 text NOT NULL CHECK(sealed_sha256 ~ '^[0-9a-f]{64}$'), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER benchmark_seals_append_only BEFORE UPDATE OR DELETE ON benchmark_seals FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TABLE benchmark_authorizations (
 experiment_id uuid NOT NULL REFERENCES benchmark_experiments(experiment_id), authorization_sha256 text NOT NULL CHECK(authorization_sha256 ~ '^[0-9a-f]{64}$'),
 payload jsonb NOT NULL, authorized_at timestamptz NOT NULL, PRIMARY KEY(experiment_id,authorization_sha256)
);
CREATE TRIGGER benchmark_authorizations_append_only BEFORE UPDATE OR DELETE ON benchmark_authorizations FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TABLE benchmark_acquisitions (
 acquisition_id uuid PRIMARY KEY, experiment_id uuid NOT NULL REFERENCES benchmark_experiments(experiment_id), generation integer NOT NULL CHECK(generation>0),
 quote jsonb NOT NULL, quote_sha256 text NOT NULL CHECK(quote_sha256 ~ '^[0-9a-f]{64}$'),
 intent jsonb NOT NULL, job_id uuid REFERENCES jobs(id), lease_id uuid REFERENCES pod_leases(id), state text NOT NULL,
 create_intent_at timestamptz NOT NULL, compute_window_start timestamptz, compute_window_end timestamptz,
 coordinator_token uuid, coordinator_lease_until timestamptz, UNIQUE(experiment_id,generation)
);
CREATE UNIQUE INDEX benchmark_one_acquisition ON benchmark_acquisitions(experiment_id) WHERE state NOT IN ('CLOSED','NO_CREATE_PROVEN');
CREATE TRIGGER benchmark_acquisition_identity BEFORE UPDATE ON benchmark_acquisitions FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('acquisition_id','experiment_id','generation','quote','quote_sha256','intent','create_intent_at');
ALTER TABLE benchmark_samples ADD FOREIGN KEY(acquisition_id) REFERENCES benchmark_acquisitions(acquisition_id);
CREATE TABLE benchmark_dispatch_slots (
 experiment_id uuid PRIMARY KEY REFERENCES benchmark_experiments(experiment_id), sample_id text,
 coordinator_token uuid, coordinator_lease_until timestamptz, revision integer NOT NULL DEFAULT 0 CHECK(revision>=0),
 FOREIGN KEY(experiment_id,sample_id) REFERENCES benchmark_samples(experiment_id,sample_id)
);
CREATE TABLE benchmark_reservation_links (
 reservation_id uuid PRIMARY KEY REFERENCES reservations(id), experiment_id uuid NOT NULL REFERENCES benchmark_experiments(experiment_id),
 acquisition_id uuid REFERENCES benchmark_acquisitions(acquisition_id), sample_id text,
 purpose text NOT NULL CHECK(purpose IN ('COMPUTE','PROMPT','STORAGE','CLEANUP')),
 FOREIGN KEY(experiment_id,sample_id) REFERENCES benchmark_samples(experiment_id,sample_id)
);
CREATE TRIGGER benchmark_links_append_only BEFORE UPDATE OR DELETE ON benchmark_reservation_links FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TABLE benchmark_uploads (
 acquisition_id uuid NOT NULL REFERENCES benchmark_acquisitions(acquisition_id), asset_sha256 text NOT NULL CHECK(asset_sha256 ~ '^[0-9a-f]{64}$'),
 media_kind text NOT NULL CHECK(media_kind IN ('image','audio')), role text NOT NULL, subject_id text NOT NULL,
 destination_slot text NOT NULL, upload_key text NOT NULL, locator jsonb,
 state text NOT NULL CHECK(state IN ('INTENT','UNKNOWN','VERIFIED')), verified_readback_sha256 text,
 PRIMARY KEY(acquisition_id,asset_sha256,media_kind,role,subject_id), UNIQUE(acquisition_id,destination_slot),
 CHECK(state<>'VERIFIED' OR verified_readback_sha256=asset_sha256)
);
CREATE TRIGGER benchmark_upload_identity BEFORE UPDATE ON benchmark_uploads FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('acquisition_id','asset_sha256','media_kind','role','subject_id','destination_slot','upload_key');
CREATE TABLE benchmark_screenings (
 experiment_id uuid NOT NULL REFERENCES benchmark_experiments(experiment_id), decision_sha256 text NOT NULL CHECK(decision_sha256 ~ '^[0-9a-f]{64}$'),
 decision jsonb NOT NULL, sealed_sha256 text NOT NULL CHECK(sealed_sha256 ~ '^[0-9a-f]{64}$'), actor_ref text NOT NULL,
 observed_at timestamptz NOT NULL, PRIMARY KEY(experiment_id,decision_sha256)
);
CREATE TRIGGER benchmark_screenings_append_only BEFORE UPDATE OR DELETE ON benchmark_screenings FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TABLE benchmark_billing_evidence (
 experiment_id uuid NOT NULL REFERENCES benchmark_experiments(experiment_id), acquisition_id uuid NOT NULL REFERENCES benchmark_acquisitions(acquisition_id),
 observation_identity text NOT NULL, raw_commit_sha256 text NOT NULL CHECK(raw_commit_sha256 ~ '^[0-9a-f]{64}$'),
 amounts jsonb NOT NULL, pod_id text NOT NULL, interval_start timestamptz NOT NULL, interval_end timestamptz NOT NULL,
 normalization_policy text NOT NULL, discrepancy text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(acquisition_id,raw_commit_sha256), CHECK(interval_end>interval_start)
);
CREATE TRIGGER benchmark_billing_append_only BEFORE UPDATE OR DELETE ON benchmark_billing_evidence FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- Schema-catalog guarantees for every benchmark table: refuse row DELETE, refuse
-- TRUNCATE, and refuse non-integer numbers (money is integer micro-USD, time is
-- integer ms). The append-only tables above already refuse UPDATE and DELETE via
-- md_forbid_mutation; the mutable ones refuse DELETE here.
CREATE TRIGGER benchmark_experiments_no_delete BEFORE DELETE ON benchmark_experiments FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER benchmark_samples_no_delete BEFORE DELETE ON benchmark_samples FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER benchmark_acquisitions_no_delete BEFORE DELETE ON benchmark_acquisitions FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER benchmark_dispatch_slots_no_delete BEFORE DELETE ON benchmark_dispatch_slots FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER benchmark_uploads_no_delete BEFORE DELETE ON benchmark_uploads FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
DO $$ DECLARE table_name text; BEGIN
 FOREACH table_name IN ARRAY ARRAY['benchmark_experiments','benchmark_samples','benchmark_seals','benchmark_authorizations','benchmark_acquisitions','benchmark_dispatch_slots','benchmark_reservation_links','benchmark_uploads','benchmark_screenings','benchmark_billing_evidence'] LOOP
  EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation()',table_name||'_no_truncate',table_name);
  EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers()',table_name||'_integer_numbers',table_name);
 END LOOP;
END $$;
CREATE FUNCTION md_benchmark_set_once() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key text; prior jsonb; current_value jsonb;
BEGIN
 FOREACH key IN ARRAY TG_ARGV LOOP
  prior := to_jsonb(OLD)->key; current_value := to_jsonb(NEW)->key;
  IF prior <> 'null'::jsonb AND prior IS DISTINCT FROM current_value THEN
   RAISE EXCEPTION 'benchmark %.% is set once', TG_TABLE_NAME,key USING ERRCODE='check_violation';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER benchmark_experiments_set_once BEFORE UPDATE ON benchmark_experiments FOR EACH ROW EXECUTE FUNCTION md_benchmark_set_once('sealed_sha256','hard_stop','execution_outcome');
CREATE TRIGGER benchmark_sample_links_set_once BEFORE UPDATE ON benchmark_samples FOR EACH ROW EXECUTE FUNCTION md_benchmark_set_once('job_id','operation_id','reservation_id','acquisition_id','request','output');
CREATE TRIGGER benchmark_acquisition_links_set_once BEFORE UPDATE ON benchmark_acquisitions FOR EACH ROW EXECUTE FUNCTION md_benchmark_set_once('job_id','lease_id','compute_window_start','compute_window_end');
