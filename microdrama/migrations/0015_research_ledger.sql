-- 0015 T009 (story lane): bounded source research. Two tables:
--   research_runs              one row per bounded research run (idempotent per trigger key)
--   research_source_documents  the provenance / date / source-quality ledger, deduped by content
--
-- A run is mutable only through its lifecycle (RUNNING -> COMPLETED/FAILED) and its typed
-- outcome; its identity (season, trigger key, request hash, planned worst case) is immutable.
-- The document ledger dedupes by (season, content_sha256); re-seeing the same content in a later
-- run only bumps mention_count / last_seen_run_id, never the provenance columns. Failed or
-- partially-known sources have no document row: they persist as typed UNKNOWN probes inside the
-- run's outcome instead (never PASS, never silently dropped).
--
-- Whole-schema guards (migrations/README.md rule 0): both tables join the deletion class and the
-- integer-numbers class.

CREATE TABLE research_runs (
  id                          uuid PRIMARY KEY,
  schema_version              text NOT NULL DEFAULT '1.0',
  season_id                   uuid NOT NULL REFERENCES seasons(id),
  trigger_kind                text NOT NULL CHECK (trigger_kind IN ('SCHEDULED','MANUAL')),
  semantic_key                text NOT NULL CHECK (length(semantic_key) BETWEEN 3 AND 400),
  request_hash                text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  state                       text NOT NULL CHECK (state IN ('RUNNING','COMPLETED','FAILED')),
  failure_code                text,
  failure_detail              jsonb,
  planned_worst_case_micro_usd bigint NOT NULL CHECK (planned_worst_case_micro_usd >= 0),
  settled_micro_usd           bigint NOT NULL DEFAULT 0 CHECK (settled_micro_usd >= 0),
  outcome                     jsonb,
  proposal_id                 uuid REFERENCES season_proposals(id),
  started_at                  timestamptz NOT NULL,
  completed_at                timestamptz,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now(),
  revision                    integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (season_id, semantic_key),
  CHECK (state <> 'FAILED' OR failure_code IS NOT NULL),
  CHECK (state = 'RUNNING' OR completed_at IS NOT NULL),
  CHECK (state <> 'COMPLETED' OR outcome IS NOT NULL)
);
CREATE TRIGGER research_runs_identity_immutable BEFORE UPDATE ON research_runs
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('season_id','trigger_kind','semantic_key',
                                                     'request_hash','planned_worst_case_micro_usd');
CREATE TRIGGER research_runs_no_delete BEFORE DELETE ON research_runs
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER research_runs_no_truncate BEFORE TRUNCATE ON research_runs
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER research_runs_integer_numbers BEFORE INSERT OR UPDATE ON research_runs
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

CREATE TABLE research_source_documents (
  id                 uuid PRIMARY KEY,
  schema_version     text NOT NULL DEFAULT '1.0',
  season_id          uuid NOT NULL REFERENCES seasons(id),
  source_id          text NOT NULL CHECK (length(source_id) BETWEEN 1 AND 120),
  url                text NOT NULL,
  title              text NOT NULL,
  published_at       timestamptz,              -- NULL = unknown date (typed unknown, not missing)
  retrieved_at       timestamptz NOT NULL,
  quality            text NOT NULL CHECK (quality IN ('PRIMARY_OFFICIAL','REPUTABLE_SECONDARY',
                                                      'PUBLIC_COMMENTS','UNVERIFIED','FIXTURE')),
  content_sha256     text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  provenance         text NOT NULL CHECK (provenance IN ('FAKE_SYNTHETIC','LIVE_PROVIDER',
                                                         'DERIVED_LOCAL','ORIGINAL_FIXTURE','LICENSED')),
  excerpt            text NOT NULL,
  mention_count      integer NOT NULL DEFAULT 1 CHECK (mention_count >= 1),
  first_seen_run_id  uuid REFERENCES research_runs(id),
  last_seen_run_id   uuid REFERENCES research_runs(id),
  first_seen_at      timestamptz NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  revision           integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (season_id, content_sha256),
  -- Mirrors contracts.SourceDocument: fixture-provenance documents are FIXTURE quality, so a
  -- mock citation can never masquerade as a real source in the ledger.
  CHECK (provenance <> 'FAKE_SYNTHETIC' OR quality = 'FIXTURE')
);
CREATE TRIGGER research_source_documents_content_immutable BEFORE UPDATE ON research_source_documents
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns(
      'season_id','source_id','url','title','published_at','retrieved_at','quality',
      'content_sha256','provenance','excerpt','first_seen_run_id','first_seen_at');
CREATE TRIGGER research_source_documents_no_delete BEFORE DELETE ON research_source_documents
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER research_source_documents_no_truncate BEFORE TRUNCATE ON research_source_documents
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER research_source_documents_integer_numbers BEFORE INSERT OR UPDATE ON research_source_documents
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
