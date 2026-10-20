-- 0001 foundation: shared trigger functions, principals, durable jobs, outbox,
-- idempotency, provider operations and webhook dedupe.
-- Conventions: uuid ids; integer micro-USD (bigint) money; timestamptz (UTC);
-- schema_version + optimistic revision on mutable records.

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Append-only guard: forbid UPDATE/DELETE on audit/immutable tables.
CREATE FUNCTION md_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only (% rejected)', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'check_violation';
END $$;

-- Column-level immutability: columns named in the trigger arguments may not change.
CREATE FUNCTION md_immutable_columns() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  col text;
BEGIN
  FOREACH col IN ARRAY TG_ARGV LOOP
    IF (to_jsonb(OLD) -> col) IS DISTINCT FROM (to_jsonb(NEW) -> col) THEN
      RAISE EXCEPTION 'column %.% is immutable', TG_TABLE_NAME, col
        USING ERRCODE = 'check_violation';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;

-- Principals --------------------------------------------------------------------
-- Human owners and their review sessions are structurally separate from service
-- credentials: approval events reference human_sessions, which workers, runtime
-- models, webhooks and schedulers never hold.

CREATE TABLE owners (
  id              uuid PRIMARY KEY,
  schema_version  text NOT NULL DEFAULT '1.0',
  username        text NOT NULL UNIQUE,
  password_hash   text NOT NULL,           -- KDF hash; never plaintext
  active          boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  revision        integer NOT NULL DEFAULT 0 CHECK (revision >= 0)
);

CREATE TABLE human_sessions (
  id               uuid PRIMARY KEY,
  owner_id         uuid NOT NULL REFERENCES owners(id),
  token_hash       text NOT NULL UNIQUE,   -- sha256 of the cookie token
  csrf_token_hash  text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  revoked_at       timestamptz,
  last_seen_at     timestamptz,
  CHECK (expires_at > created_at)
);

CREATE TABLE service_credentials (
  id             uuid PRIMARY KEY,
  principal_id   text NOT NULL UNIQUE,
  kind           text NOT NULL CHECK (kind IN ('SERVICE_WORKER','RUNTIME_MODEL','PROVIDER_WEBHOOK','SCHEDULER')),
  runtime_role   text,
  token_hash     text NOT NULL UNIQUE,
  scopes         text[] NOT NULL DEFAULT '{}',
  active         boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  revoked_at     timestamptz,
  CHECK (kind <> 'RUNTIME_MODEL' OR runtime_role IS NOT NULL)
);

-- Durable jobs ------------------------------------------------------------------

CREATE TABLE jobs (
  id                uuid PRIMARY KEY,
  schema_version    text NOT NULL DEFAULT '1.0',
  job_type          text NOT NULL,
  job_version       integer NOT NULL DEFAULT 1 CHECK (job_version >= 1),
  queue             text NOT NULL CHECK (queue IN ('production','publication','community')),
  semantic_key      text NOT NULL UNIQUE,
  input_hash        text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
  input             jsonb NOT NULL CHECK (octet_length(input::text) <= 65536),
  status            text NOT NULL CHECK (status IN ('QUEUED','RUNNING','WAITING_EXTERNAL','RETRY_WAIT',
                                                   'SUCCEEDED','FAILED','NEEDS_RECONCILIATION','CANCELLED')),
  priority          integer NOT NULL DEFAULT 100,
  attempt           integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  max_attempts      integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
  run_after         timestamptz NOT NULL DEFAULT now(),
  lease_owner       text,
  lease_expires_at  timestamptz,
  heartbeat_at      timestamptz,
  external_id       text,
  outcome           jsonb,
  error_code        text,
  season_id         uuid,
  episode_id        uuid,
  correlation_id    uuid,
  causation_id      uuid,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  revision          integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK ((status = 'RUNNING') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX jobs_claim_idx ON jobs (queue, status, run_after, priority);
CREATE INDEX jobs_episode_idx ON jobs (episode_id);
CREATE TRIGGER jobs_identity_immutable BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('job_type', 'semantic_key', 'input_hash', 'input', 'queue');

-- Outbox / domain events ------------------------------------------------------------

CREATE TABLE aggregate_sequences (
  aggregate_id    uuid PRIMARY KEY,
  aggregate_type  text NOT NULL,
  last_sequence   bigint NOT NULL DEFAULT 0 CHECK (last_sequence >= 0)
);

CREATE TABLE domain_events (
  event_id         uuid PRIMARY KEY,
  schema_version   text NOT NULL DEFAULT '1.0',
  event_type       text NOT NULL CHECK (event_type ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
  aggregate_type   text NOT NULL,
  aggregate_id     uuid NOT NULL,
  sequence         bigint NOT NULL CHECK (sequence >= 1),
  correlation_id   uuid NOT NULL,
  causation_id     uuid,
  occurred_at      timestamptz NOT NULL,
  payload          jsonb NOT NULL CHECK (octet_length(payload::text) <= 32768),
  global_position  bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  UNIQUE (aggregate_id, sequence)
);
CREATE TRIGGER domain_events_append_only BEFORE UPDATE OR DELETE ON domain_events
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- Dispatch tracking kept separate so domain_events stays strictly append-only.
CREATE TABLE event_dispatches (
  event_id       uuid PRIMARY KEY REFERENCES domain_events(event_id),
  transport      text NOT NULL,
  dispatched_at  timestamptz NOT NULL DEFAULT now()
);

-- At-least-once delivery: consumers record what they have applied.
CREATE TABLE event_consumptions (
  consumer     text NOT NULL,
  event_id     uuid NOT NULL REFERENCES domain_events(event_id),
  consumed_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer, event_id)
);

-- Command idempotency ---------------------------------------------------------------

CREATE TABLE idempotency_records (
  id               uuid PRIMARY KEY,
  scope            text NOT NULL,
  idempotency_key  text NOT NULL,
  principal_id     text NOT NULL,
  request_hash     text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  response_status  integer,
  response_body    jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  completed_at     timestamptz,
  UNIQUE (scope, idempotency_key),
  CHECK ((response_status IS NULL) = (completed_at IS NULL))
);
CREATE TRIGGER idempotency_identity_immutable BEFORE UPDATE ON idempotency_records
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('scope', 'idempotency_key', 'principal_id', 'request_hash');

-- External provider operations (submit / status / reconcile) -------------------------

CREATE TABLE provider_operations (
  id              uuid PRIMARY KEY,
  schema_version  text NOT NULL DEFAULT '1.0',
  provider        text NOT NULL,
  operation_kind  text NOT NULL,
  client_token    text NOT NULL,
  request_hash    text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  job_id          uuid REFERENCES jobs(id),
  reservation_id  uuid,                -- FK added in 0003
  state           text NOT NULL CHECK (state IN ('PENDING_SUBMIT','SUBMITTED','RUNNING','SUCCEEDED',
                                                 'FAILED','CANCELLED','UNKNOWN','NOT_FOUND')),
  external_id     text,
  attempt         integer NOT NULL DEFAULT 1 CHECK (attempt >= 1),
  submitted_at    timestamptz,
  deadline_at     timestamptz NOT NULL,
  last_result     jsonb,
  episode_id      uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  revision        integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (provider, client_token)
);
CREATE UNIQUE INDEX provider_operations_external_idx
  ON provider_operations (provider, external_id) WHERE external_id IS NOT NULL;
CREATE TRIGGER provider_operations_identity_immutable BEFORE UPDATE ON provider_operations
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('provider', 'client_token', 'request_hash', 'operation_kind');

-- Inbound webhook dedupe -----------------------------------------------------------

CREATE TABLE webhook_events (
  id               uuid PRIMARY KEY,
  provider         text NOT NULL,
  event_id         text NOT NULL,
  event_type       text,
  signature_valid  boolean NOT NULL,
  payload          jsonb NOT NULL DEFAULT '{}' CHECK (octet_length(payload::text) <= 65536),
  received_at      timestamptz NOT NULL DEFAULT now(),
  processed_at     timestamptz,
  job_id           uuid REFERENCES jobs(id),
  UNIQUE (provider, event_id)
);

-- Visible manual work (qualification must never hide it) -----------------------------

CREATE TABLE manual_interventions (
  id           uuid PRIMARY KEY,
  season_id    uuid,
  episode_id   uuid,
  kind         text NOT NULL CHECK (kind IN ('TECHNICAL_FIX','MANUAL_EDIT','MANUAL_UPLOAD','DATA_CORRECTION','OTHER')),
  description  text NOT NULL,
  actor        text NOT NULL,
  occurred_at  timestamptz NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER manual_interventions_append_only BEFORE UPDATE OR DELETE ON manual_interventions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
