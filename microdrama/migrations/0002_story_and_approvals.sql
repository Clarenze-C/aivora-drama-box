-- 0002 seasons, proposals, canon, episodes, scripts, manifests, references,
-- approval events (append-only, human-session bound), identity locks, preferences.

CREATE TABLE seasons (
  id                       uuid PRIMARY KEY,
  schema_version           text NOT NULL DEFAULT '1.0',
  state                    text NOT NULL CHECK (state IN ('PROPOSED','SEASON_APPROVED','ACTIVE','COMPLETE','REJECTED','CANCELLED')),
  title_th                 text NOT NULL,
  title_en                 text NOT NULL,
  current_proposal_id      uuid,
  approved_scope_version   integer,
  approved_scope_hash      text CHECK (approved_scope_hash ~ '^[0-9a-f]{64}$'),
  approval_event_id        uuid,
  approved_at              timestamptz,
  expected_episode_count   integer NOT NULL DEFAULT 10 CHECK (expected_episode_count >= 1),
  correlation_id           uuid,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  revision                 integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK (state NOT IN ('SEASON_APPROVED','ACTIVE','COMPLETE')
         OR (approved_scope_hash IS NOT NULL AND approval_event_id IS NOT NULL AND approved_scope_version IS NOT NULL))
);

CREATE TABLE season_proposals (
  id                        uuid PRIMARY KEY,
  schema_version            text NOT NULL DEFAULT '1.0',
  season_id                 uuid NOT NULL REFERENCES seasons(id),
  scope_version             integer NOT NULL CHECK (scope_version >= 1),
  scope                     jsonb NOT NULL,          -- contracts.SeasonScope
  scope_hash                text NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
  source_provenance         jsonb NOT NULL DEFAULT '[]',
  research_reservation_ids  jsonb NOT NULL DEFAULT '[]',
  status                    text NOT NULL CHECK (status IN ('PROPOSED','APPROVED','REJECTED','SUPERSEDED')),
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  revision                  integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (season_id, scope_version)
);
CREATE TRIGGER season_proposals_scope_immutable BEFORE UPDATE ON season_proposals
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('season_id', 'scope_version', 'scope', 'scope_hash');

-- Planned, final-approved and published canon are kept as separate kinds.
CREATE TABLE canon_versions (
  id                 uuid PRIMARY KEY,
  schema_version     text NOT NULL DEFAULT '1.0',
  season_id          uuid NOT NULL REFERENCES seasons(id),
  kind               text NOT NULL CHECK (kind IN ('PLANNED','FINAL_APPROVED','PUBLISHED')),
  version            integer NOT NULL CHECK (version >= 1),
  facts              jsonb NOT NULL,
  facts_hash         text NOT NULL CHECK (facts_hash ~ '^[0-9a-f]{64}$'),
  source_episode_id  uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (season_id, kind, version)
);
CREATE TRIGGER canon_versions_append_only BEFORE UPDATE OR DELETE ON canon_versions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE episodes (
  id                         uuid PRIMARY KEY,
  schema_version             text NOT NULL DEFAULT '1.0',
  season_id                  uuid NOT NULL REFERENCES seasons(id),
  episode_number             integer NOT NULL CHECK (episode_number >= 1),
  state                      text NOT NULL CHECK (state IN ('PLANNED','SCRIPTING','REFERENCES','RENDERING','ASSEMBLING',
                                   'AI_REVIEW','AWAITING_FINAL_REVIEW','RELEASE_APPROVED','SCHEDULED','PUBLISHING',
                                   'PUBLISHED_VERIFIED','MANAGED')),
  outcome                    text CHECK (outcome IN ('BUDGET_EXHAUSTED','FAILED_QA','FAILED_INFRA','RIGHTS_UNCLEARED',
                                   'CAPABILITY_UNAVAILABLE','NEEDS_RECONCILIATION','REJECTED','CANCELLED')),
  outcome_detail             text,
  approved_scope_hash        text NOT NULL CHECK (approved_scope_hash ~ '^[0-9a-f]{64}$'),
  plan                       jsonb,                   -- contracts.EpisodePlan
  current_script_id          uuid,
  current_manifest_id        uuid,
  current_package_id         uuid,
  identity_lock_id           uuid,
  qa_cycle                   integer NOT NULL DEFAULT 1 CHECK (qa_cycle >= 1),
  correlation_id             uuid,
  created_at                 timestamptz NOT NULL DEFAULT now(),
  updated_at                 timestamptz NOT NULL DEFAULT now(),
  revision                   integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (season_id, episode_number)
);

CREATE TABLE scripts (
  id              uuid PRIMARY KEY,
  schema_version  text NOT NULL DEFAULT '1.0',
  episode_id      uuid NOT NULL REFERENCES episodes(id),
  version         integer NOT NULL CHECK (version >= 1),
  canon_version   integer NOT NULL CHECK (canon_version >= 0),
  body            jsonb NOT NULL,                     -- contracts.Script
  body_hash       text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  status          text NOT NULL CHECK (status IN ('DRAFT','CRITIC_PASSED','CRITIC_FAILED','CURRENT','SUPERSEDED')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  revision        integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (episode_id, version)
);
CREATE TRIGGER scripts_body_immutable BEFORE UPDATE ON scripts
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('episode_id', 'version', 'body', 'body_hash');

CREATE TABLE shot_manifests (
  id                uuid PRIMARY KEY,
  schema_version    text NOT NULL DEFAULT '1.0',
  episode_id        uuid NOT NULL REFERENCES episodes(id),
  script_id         uuid NOT NULL REFERENCES scripts(id),
  version           integer NOT NULL CHECK (version >= 1),
  identity_lock_id  uuid,
  body              jsonb NOT NULL,                   -- contracts.ShotManifest
  body_hash         text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  status            text NOT NULL CHECK (status IN ('DRAFT','CURRENT','SUPERSEDED')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  revision          integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (episode_id, version)
);
CREATE TRIGGER shot_manifests_body_immutable BEFORE UPDATE ON shot_manifests
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('episode_id', 'version', 'body', 'body_hash', 'script_id');

CREATE TABLE characters (
  id                    uuid PRIMARY KEY,
  schema_version        text NOT NULL DEFAULT '1.0',
  season_id             uuid NOT NULL REFERENCES seasons(id),
  character_key         text NOT NULL,
  name_th               text NOT NULL,
  name_en               text NOT NULL,
  brief                 jsonb NOT NULL,
  state                 text NOT NULL CHECK (state IN ('PROVISIONAL','LOCKED','SUPERSEDED')),
  first_episode_number  integer NOT NULL CHECK (first_episode_number >= 1),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  revision              integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (season_id, character_key)
);

CREATE TABLE voices (
  id                  uuid PRIMARY KEY,
  schema_version      text NOT NULL DEFAULT '1.0',
  season_id           uuid NOT NULL REFERENCES seasons(id),
  character_id        uuid NOT NULL REFERENCES characters(id),
  voice_key           text NOT NULL,
  version             integer NOT NULL CHECK (version >= 1),
  provider            text NOT NULL,
  provider_voice_ref  text NOT NULL,
  rights_route_id     text,
  license_hash        text CHECK (license_hash ~ '^[0-9a-f]{64}$'),
  anchor_asset_id     uuid,
  state               text NOT NULL CHECK (state IN ('PROVISIONAL','ACCEPTED','LOCKED','SUPERSEDED')),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  revision            integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (season_id, voice_key, version)
);

-- Versioned reusable references (faces, wardrobe, locations, style, voice anchors).
CREATE TABLE reference_versions (
  id              uuid PRIMARY KEY,
  schema_version  text NOT NULL DEFAULT '1.0',
  season_id       uuid NOT NULL REFERENCES seasons(id),
  ref_kind        text NOT NULL CHECK (ref_kind IN ('FACE','VOICE','WARDROBE','LOCATION','STYLE')),
  ref_key         text NOT NULL,
  version         integer NOT NULL CHECK (version >= 1),
  asset_id        uuid NOT NULL,                     -- FK added in 0004
  content_sha256  text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  source_hash     text CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  license_hash    text CHECK (license_hash ~ '^[0-9a-f]{64}$'),
  cache_key       text NOT NULL CHECK (cache_key ~ '^[0-9a-f]{64}$'),  -- full input/model/license hash
  character_key   text,
  state           text NOT NULL CHECK (state IN ('PROVISIONAL','ACCEPTED','LOCKED','SUPERSEDED','FAILED')),
  reviewed_in_package_id uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  revision        integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (season_id, ref_kind, ref_key, version),
  UNIQUE (season_id, cache_key)
);
CREATE TRIGGER reference_versions_content_immutable BEFORE UPDATE ON reference_versions
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('season_id', 'ref_kind', 'ref_key', 'version', 'asset_id',
                                                     'content_sha256', 'cache_key');

-- Human gate decisions ---------------------------------------------------------------

CREATE TABLE approval_events (
  id                      uuid PRIMARY KEY,
  schema_version          text NOT NULL DEFAULT '1.0',
  gate_type               text NOT NULL CHECK (gate_type IN ('SEASON_CONCEPT','EPISODE_FINAL')),
  action                  text NOT NULL CHECK (action IN ('APPROVE','REVISE','REJECT')),
  entity_type             text NOT NULL CHECK (entity_type IN ('season','episode')),
  entity_id               uuid NOT NULL,
  expected_revision       integer NOT NULL CHECK (expected_revision >= 0),
  package_hash            text NOT NULL CHECK (package_hash ~ '^[0-9a-f]{64}$'),
  media_hashes            jsonb NOT NULL DEFAULT '[]',
  management_policy_hash  text CHECK (management_policy_hash ~ '^[0-9a-f]{64}$'),
  release_scope_hash      text CHECK (release_scope_hash ~ '^[0-9a-f]{64}$'),
  actor_owner_id          uuid NOT NULL REFERENCES owners(id),
  actor_session_id        uuid NOT NULL REFERENCES human_sessions(id),
  idempotency_key         text NOT NULL UNIQUE,
  command_hash            text NOT NULL CHECK (command_hash ~ '^[0-9a-f]{64}$'),
  feedback                jsonb NOT NULL DEFAULT '[]',
  reason                  text,
  created_at              timestamptz NOT NULL DEFAULT now(),
  CHECK ((gate_type = 'SEASON_CONCEPT') = (entity_type = 'season')),
  CHECK (gate_type <> 'SEASON_CONCEPT' OR action IN ('APPROVE','REJECT')),
  CHECK (gate_type <> 'EPISODE_FINAL' OR action <> 'APPROVE'
         OR (jsonb_array_length(media_hashes) > 0 AND management_policy_hash IS NOT NULL
             AND release_scope_hash IS NOT NULL)),
  CHECK (action <> 'REVISE' OR jsonb_array_length(feedback) > 0)
);
-- One decision per entity revision: concurrent or stale double-decisions conflict.
CREATE UNIQUE INDEX approval_events_one_per_revision
  ON approval_events (gate_type, entity_id, expected_revision);
CREATE TRIGGER approval_events_append_only BEFORE UPDATE OR DELETE ON approval_events
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- Defense in depth: an approval row must come from a live human review session of an
-- active owner. Service credentials have no human_sessions rows and cannot satisfy this.
CREATE FUNCTION md_approval_requires_human_session() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  s record;
BEGIN
  SELECT hs.owner_id, hs.expires_at, hs.revoked_at, o.active
    INTO s
    FROM human_sessions hs JOIN owners o ON o.id = hs.owner_id
   WHERE hs.id = NEW.actor_session_id;
  IF NOT FOUND OR s.owner_id <> NEW.actor_owner_id OR NOT s.active
     OR s.revoked_at IS NOT NULL OR s.expires_at <= NEW.created_at THEN
    RAISE EXCEPTION 'approval events require a live human owner session'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER approval_events_human_session BEFORE INSERT ON approval_events
  FOR EACH ROW EXECUTE FUNCTION md_approval_requires_human_session();

CREATE TABLE feedback_events (
  id                    uuid PRIMARY KEY,
  schema_version        text NOT NULL DEFAULT '1.0',
  episode_id            uuid NOT NULL REFERENCES episodes(id),
  approval_event_id     uuid NOT NULL REFERENCES approval_events(id),
  category              text NOT NULL CHECK (category IN ('identity_voice','thai_dialogue','subtitles','motivation',
                                                         'continuity_props','pacing','sound','other')),
  start_ms              bigint NOT NULL CHECK (start_ms >= 0),
  end_ms                bigint NOT NULL,
  asset_id              uuid,
  shot_key              text,
  comment               text NOT NULL,
  scope                 text NOT NULL CHECK (scope IN ('SHOT','EPISODE','SERIES')),
  explicit_recurring    boolean NOT NULL DEFAULT false,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CHECK (end_ms >= start_ms),
  CHECK (scope <> 'SERIES' OR explicit_recurring)
);
CREATE TRIGGER feedback_events_append_only BEFORE UPDATE OR DELETE ON feedback_events
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE identity_locks (
  id                    uuid PRIMARY KEY,
  schema_version        text NOT NULL DEFAULT '1.0',
  season_id             uuid NOT NULL REFERENCES seasons(id),
  source_episode_id     uuid NOT NULL REFERENCES episodes(id),
  version               integer NOT NULL CHECK (version >= 1),
  approval_event_id     uuid NOT NULL REFERENCES approval_events(id),
  release_package_hash  text NOT NULL CHECK (release_package_hash ~ '^[0-9a-f]{64}$'),
  body                  jsonb NOT NULL,              -- contracts.IdentityLock
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (season_id, version),
  UNIQUE (approval_event_id)
);
CREATE TRIGGER identity_locks_append_only BEFORE UPDATE OR DELETE ON identity_locks
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE identity_lock_assets (
  lock_id               uuid NOT NULL REFERENCES identity_locks(id),
  reference_version_id  uuid NOT NULL REFERENCES reference_versions(id),
  asset_id              uuid NOT NULL,
  content_sha256        text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  asset_kind            text NOT NULL CHECK (asset_kind IN ('FACE','VOICE','WARDROBE','LOCATION','STYLE')),
  PRIMARY KEY (lock_id, reference_version_id)
);
CREATE TRIGGER identity_lock_assets_append_only BEFORE UPDATE OR DELETE ON identity_lock_assets
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- Scoped feedback memory. Series-wide rules need explicit scope or the final gate.
CREATE TABLE preference_rules (
  id                        uuid PRIMARY KEY,
  schema_version            text NOT NULL DEFAULT '1.0',
  season_id                 uuid NOT NULL REFERENCES seasons(id),
  rule_key                  text NOT NULL,
  version                   integer NOT NULL CHECK (version >= 1),
  scope                     text NOT NULL CHECK (scope IN ('SHOT','EPISODE','SERIES')),
  episode_id                uuid REFERENCES episodes(id),
  shot_key                  text,
  category                  text NOT NULL,
  instruction               text NOT NULL,
  source_feedback_event_id  uuid REFERENCES feedback_events(id),
  source_approval_event_id  uuid REFERENCES approval_events(id),
  explicit_recurring        boolean NOT NULL DEFAULT false,
  state                     text NOT NULL CHECK (state IN ('ACTIVE','SUPERSEDED','ROLLED_BACK')),
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  revision                  integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (season_id, rule_key, version),
  CHECK (scope <> 'SERIES' OR explicit_recurring OR source_approval_event_id IS NOT NULL),
  CHECK (scope = 'SERIES' OR episode_id IS NOT NULL),
  CHECK (scope <> 'SHOT' OR shot_key IS NOT NULL)
);
CREATE UNIQUE INDEX preference_rules_one_active
  ON preference_rules (season_id, rule_key) WHERE state = 'ACTIVE';
