-- 0004 assets/lineage, edit manifests, captions, hook experiments, QA observations
-- (immutable Pass A), findings and repair plans.

CREATE TABLE assets (
  id              uuid PRIMARY KEY,
  schema_version  text NOT NULL DEFAULT '1.0',
  asset_kind      text NOT NULL CHECK (asset_kind IN ('VIDEO','AUDIO','IMAGE','CAPTION','EDL','TRANSCRIPT','REPORT',
                                                     'CONTACT_SHEET','OTHER')),
  object_key      text NOT NULL UNIQUE,      -- private object-store key (never a public URL)
  sha256          text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes      bigint NOT NULL CHECK (size_bytes >= 0),
  media_type      text NOT NULL,
  media           jsonb,                     -- contracts.MediaInfo measured by ffprobe
  duration_ms     bigint CHECK (duration_ms >= 0),
  state           text NOT NULL CHECK (state IN ('PROVISIONAL','ACCEPTED','FAILED','LOCKED','SUPERSEDED')),
  provenance      text NOT NULL CHECK (provenance IN ('FAKE_SYNTHETIC','LIVE_PROVIDER','DERIVED_LOCAL',
                                                     'ORIGINAL_FIXTURE','LICENSED')),
  season_id       uuid REFERENCES seasons(id),
  episode_id      uuid REFERENCES episodes(id),
  version         integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  license_refs    jsonb NOT NULL DEFAULT '[]',
  generation_key  text CHECK (generation_key ~ '^[0-9a-f]{64}$'),  -- full input/model/settings hash
  verified_at     timestamptz,               -- last durable checksum verification
  descriptor      jsonb NOT NULL,            -- contracts.AssetDescriptor
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  revision        integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK (asset_kind NOT IN ('VIDEO','AUDIO') OR media IS NOT NULL)
);
CREATE INDEX assets_sha_idx ON assets (sha256);
CREATE INDEX assets_episode_idx ON assets (episode_id);
CREATE TRIGGER assets_content_immutable BEFORE UPDATE ON assets
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('asset_kind', 'object_key', 'sha256', 'size_bytes',
                                                     'media_type', 'media', 'provenance', 'generation_key');

ALTER TABLE reference_versions
  ADD CONSTRAINT reference_versions_asset_fk FOREIGN KEY (asset_id) REFERENCES assets(id);
ALTER TABLE voices
  ADD CONSTRAINT voices_anchor_asset_fk FOREIGN KEY (anchor_asset_id) REFERENCES assets(id);

CREATE TABLE asset_lineage (
  asset_id         uuid NOT NULL REFERENCES assets(id),
  source_asset_id  uuid NOT NULL REFERENCES assets(id),
  relation         text NOT NULL DEFAULT 'derived_from',
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_id, source_asset_id),
  CHECK (asset_id <> source_asset_id)
);
CREATE TRIGGER asset_lineage_append_only BEFORE UPDATE OR DELETE ON asset_lineage
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE edit_manifests (
  id               uuid PRIMARY KEY,          -- = EditDecisionList.edl_id
  schema_version   text NOT NULL DEFAULT '1.0',
  episode_id       uuid NOT NULL REFERENCES episodes(id),
  purpose          text NOT NULL CHECK (purpose IN ('FULL_EPISODE','PART','PROMO_CUT','HOOK')),
  variant_key      text NOT NULL DEFAULT 'main',
  version          integer NOT NULL CHECK (version >= 1),
  edl              jsonb NOT NULL,            -- contracts.EditDecisionList
  edl_hash         text NOT NULL CHECK (edl_hash ~ '^[0-9a-f]{64}$'),
  output_asset_id  uuid REFERENCES assets(id),
  state            text NOT NULL CHECK (state IN ('PLANNED','RENDERED','FAILED','INVALIDATED','SUPERSEDED')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  revision         integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (episode_id, purpose, variant_key, version)
);
CREATE TRIGGER edit_manifests_edl_immutable BEFORE UPDATE ON edit_manifests
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('episode_id', 'purpose', 'variant_key', 'version', 'edl', 'edl_hash');

CREATE TABLE caption_tracks (
  id              uuid PRIMARY KEY,           -- = CaptionTrack.track_id
  schema_version  text NOT NULL DEFAULT '1.0',
  episode_id      uuid NOT NULL REFERENCES episodes(id),
  locale          text NOT NULL,
  version         integer NOT NULL CHECK (version >= 1),
  timing_source   text NOT NULL CHECK (timing_source IN ('ACTUAL_AUDIO_ALIGNMENT','ESTIMATED_FROM_SCRIPT')),
  body            jsonb NOT NULL,             -- contracts.CaptionTrack
  body_hash       text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  asset_id        uuid REFERENCES assets(id), -- rendered subtitle file
  state           text NOT NULL CHECK (state IN ('CURRENT','INVALIDATED','SUPERSEDED')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  revision        integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (episode_id, locale, version)
);
CREATE UNIQUE INDEX caption_tracks_one_current ON caption_tracks (episode_id, locale) WHERE state = 'CURRENT';
CREATE TRIGGER caption_tracks_body_immutable BEFORE UPDATE ON caption_tracks
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('episode_id', 'locale', 'version', 'body', 'body_hash', 'timing_source');

CREATE TABLE hook_experiments (
  id              uuid PRIMARY KEY,
  schema_version  text NOT NULL DEFAULT '1.0',
  episode_id      uuid NOT NULL REFERENCES episodes(id),
  body            jsonb NOT NULL,             -- contracts.HookExperiment
  body_hash       text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (episode_id, body_hash)
);
CREATE TRIGGER hook_experiments_append_only BEFORE UPDATE OR DELETE ON hook_experiments
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- Hook experiment ledger: one row per planned/actual exposure in an eligible slot.
CREATE TABLE hook_exposures (
  id                 uuid PRIMARY KEY,
  experiment_id      uuid NOT NULL REFERENCES hook_experiments(id),
  candidate_id       text NOT NULL,
  platform           text NOT NULL,
  account_ref        text NOT NULL,
  release_slot       text NOT NULL,
  cohort             text NOT NULL,
  scheduled_utc      timestamptz NOT NULL,
  duration_ms        bigint NOT NULL CHECK (duration_ms BETWEEN 20000 AND 40000),
  subtitle_locale    text,
  offer_ref          text,
  traffic            text NOT NULL DEFAULT 'ORGANIC' CHECK (traffic = 'ORGANIC'),
  platform_post_id   uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (experiment_id, candidate_id, platform, account_ref, release_slot)
);

-- Pass A: frozen, media-only observations. Immutable once written (IMP-04).
CREATE TABLE qa_observations (
  id              uuid PRIMARY KEY,           -- = ObservationReport.report_id
  schema_version  text NOT NULL DEFAULT '1.0',
  episode_id      uuid NOT NULL REFERENCES episodes(id),
  request_id      uuid NOT NULL UNIQUE,
  request_sha256  text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  media_sha256    jsonb NOT NULL,
  report          jsonb NOT NULL,             -- contracts.ObservationReport
  report_sha256   text NOT NULL CHECK (report_sha256 ~ '^[0-9a-f]{64}$'),
  provenance      text NOT NULL,
  frozen_at       timestamptz NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER qa_observations_append_only BEFORE UPDATE OR DELETE ON qa_observations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE qa_findings (
  id               uuid PRIMARY KEY,          -- = QAFinding.finding_id
  schema_version   text NOT NULL DEFAULT '1.0',
  episode_id       uuid NOT NULL REFERENCES episodes(id),
  qa_cycle         integer NOT NULL CHECK (qa_cycle >= 1),
  asset_id         uuid NOT NULL,
  start_ms         bigint NOT NULL CHECK (start_ms >= 0),
  end_ms           bigint NOT NULL,
  check_id         text NOT NULL,
  check_family     text NOT NULL,
  source_pass      text NOT NULL CHECK (source_pass IN ('TECHNICAL','PASS_A_OBSERVATION','PASS_B_COMPARISON','HUMAN_FEEDBACK')),
  severity         text NOT NULL CHECK (severity IN ('CRITICAL','MAJOR','MINOR','INFO')),
  coverage         text NOT NULL CHECK (coverage IN ('CHECKED','PARTIAL','UNSAMPLED','UNAVAILABLE')),
  outcome          text NOT NULL CHECK (outcome IN ('PASS','REPAIRABLE','BLOCKED','UNKNOWN')),
  observation_id   uuid REFERENCES qa_observations(id),
  body             jsonb NOT NULL,            -- contracts.QAFinding
  resolution       text NOT NULL DEFAULT 'OPEN' CHECK (resolution IN ('OPEN','RESOLVED','SUPERSEDED','ACCEPTED_UNKNOWN')),
  resolved_by_plan_id uuid,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  revision         integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK (end_ms >= start_ms),
  CHECK (coverage NOT IN ('UNSAMPLED','UNAVAILABLE') OR outcome = 'UNKNOWN'),
  CHECK (outcome <> 'PASS' OR coverage = 'CHECKED')
);
CREATE INDEX qa_findings_episode_idx ON qa_findings (episode_id, qa_cycle);
CREATE TRIGGER qa_findings_body_immutable BEFORE UPDATE ON qa_findings
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('episode_id', 'qa_cycle', 'asset_id', 'start_ms', 'end_ms', 'check_id',
                                                     'source_pass', 'severity', 'coverage', 'outcome', 'body');

CREATE TABLE repair_plans (
  id                        uuid PRIMARY KEY,
  schema_version            text NOT NULL DEFAULT '1.0',
  episode_id                uuid NOT NULL REFERENCES episodes(id),
  qa_cycle                  integer NOT NULL CHECK (qa_cycle >= 1),
  trigger                   text NOT NULL CHECK (trigger IN ('QA_FINDING','HUMAN_FEEDBACK')),
  round_number              integer NOT NULL CHECK (round_number >= 1),
  source_approval_event_id  uuid REFERENCES approval_events(id),
  body                      jsonb NOT NULL,   -- contracts.RepairPlan
  body_hash                 text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  total_estimated_micro_usd bigint NOT NULL CHECK (total_estimated_micro_usd >= 0),
  reservation_ids           jsonb NOT NULL DEFAULT '[]',
  status                    text NOT NULL CHECK (status IN ('PLANNED','RESERVED','EXECUTING','COMPLETED','FAILED','CANCELLED')),
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  revision                  integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK (trigger <> 'QA_FINDING' OR round_number <= 2),
  CHECK ((trigger = 'HUMAN_FEEDBACK') = (source_approval_event_id IS NOT NULL))
);
CREATE UNIQUE INDEX repair_plans_qa_round_idx ON repair_plans (episode_id, qa_cycle, round_number)
  WHERE trigger = 'QA_FINDING';
CREATE UNIQUE INDEX repair_plans_feedback_idx ON repair_plans (source_approval_event_id)
  WHERE trigger = 'HUMAN_FEEDBACK';
CREATE TRIGGER repair_plans_body_immutable BEFORE UPDATE ON repair_plans
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('episode_id', 'qa_cycle', 'trigger', 'round_number', 'body', 'body_hash');
