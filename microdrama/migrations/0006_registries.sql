-- 0006 capability/rights/preset registries, credential references and imported policy.
-- Registries record evidence; imported policy is settings, not proof of provider readiness.

CREATE TABLE credential_refs (
  ref          text PRIMARY KEY CHECK (ref ~ '^credref:[a-z0-9][a-z0-9._\-]{1,120}$'),
  purpose      text NOT NULL,
  provider     text NOT NULL,
  store        text NOT NULL CHECK (store IN ('ENV','FILE','VAULT','NONE')),
  locator      text NOT NULL,          -- e.g. env var NAME or vault path; never the secret value
  created_at   timestamptz NOT NULL DEFAULT now(),
  rotated_at   timestamptz,
  revoked_at   timestamptz
);

CREATE TABLE capability_registry (
  id               uuid PRIMARY KEY,
  capability_id    uuid NOT NULL,
  version          integer NOT NULL CHECK (version >= 1),
  platform         text NOT NULL CHECK (platform IN ('TIKTOK','YOUTUBE','FACEBOOK','INSTAGRAM')),
  provider_route   text NOT NULL,
  account_ref      text NOT NULL,
  record           jsonb NOT NULL,     -- contracts.CapabilityRecord
  enabled          boolean NOT NULL DEFAULT false,
  evidence_sources jsonb NOT NULL DEFAULT '[]',
  verified_at      timestamptz,
  current          boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (capability_id, version),
  CHECK (NOT enabled OR (verified_at IS NOT NULL AND jsonb_array_length(evidence_sources) > 0))
);
CREATE UNIQUE INDEX capability_registry_current ON capability_registry (platform, account_ref, provider_route) WHERE current;
CREATE TRIGGER capability_registry_record_immutable BEFORE UPDATE ON capability_registry
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('capability_id', 'version', 'record', 'enabled', 'evidence_sources');

CREATE TABLE rights_registry (
  id                      uuid PRIMARY KEY,
  rights_route_id         text NOT NULL,
  version                 integer NOT NULL CHECK (version >= 1),
  subject_kind            text NOT NULL CHECK (subject_kind IN ('MODEL','MODEL_OUTPUT','VOICE','MUSIC','FONT','REFERENCE','STOCK')),
  subject_ref             text NOT NULL,
  territories             jsonb NOT NULL DEFAULT '[]',   -- ISO country codes; empty = unknown
  commercial_use          boolean,                        -- NULL = unknown (blocks)
  output_release_allowed  boolean,                        -- NULL = unknown (blocks)
  required_disclosures    jsonb NOT NULL DEFAULT '[]',
  expires_at              timestamptz,
  evidence                jsonb NOT NULL DEFAULT '[]',
  status                  text NOT NULL CHECK (status IN ('ELIGIBLE','INELIGIBLE','UNKNOWN','EXPIRED')),
  current                 boolean NOT NULL DEFAULT true,
  created_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rights_route_id, subject_kind, subject_ref, version),
  CHECK (status <> 'ELIGIBLE' OR (commercial_use AND output_release_allowed AND jsonb_array_length(evidence) > 0
                                  AND jsonb_array_length(territories) > 0))
);
CREATE UNIQUE INDEX rights_registry_current ON rights_registry (rights_route_id, subject_kind, subject_ref) WHERE current;
CREATE TRIGGER rights_registry_record_immutable BEFORE UPDATE ON rights_registry
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('rights_route_id', 'version', 'subject_kind', 'subject_ref', 'territories',
                                                     'commercial_use', 'output_release_allowed', 'expires_at', 'evidence', 'status');

CREATE TABLE preset_registry (
  id               uuid PRIMARY KEY,
  preset_id        text NOT NULL,
  version          integer NOT NULL CHECK (version >= 1),
  tier             text NOT NULL CHECK (tier IN ('fast_four_step','quality_eight_step','compatible_baseline')),
  workflow_sha256  text NOT NULL CHECK (workflow_sha256 ~ '^[0-9a-f]{64}$'),
  record           jsonb NOT NULL,   -- model/LoRA/node hashes, GPU/RAM, precision, controls, measured latency/cost/acceptance
  enabled          boolean NOT NULL DEFAULT false,
  evidence         jsonb NOT NULL DEFAULT '[]',
  current          boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (preset_id, version),
  CHECK (NOT enabled OR jsonb_array_length(evidence) > 0)
);
CREATE UNIQUE INDEX preset_registry_current ON preset_registry (preset_id) WHERE current;
CREATE TRIGGER preset_registry_record_immutable BEFORE UPDATE ON preset_registry
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('preset_id', 'version', 'tier', 'workflow_sha256', 'record', 'enabled', 'evidence');

CREATE TABLE policy_versions (
  id             uuid PRIMARY KEY,
  version        text NOT NULL UNIQUE,
  document_kind  text NOT NULL,
  body           jsonb NOT NULL,
  body_hash      text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  imported_at    timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER policy_versions_append_only BEFORE UPDATE OR DELETE ON policy_versions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
