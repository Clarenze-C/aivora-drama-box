-- 0005 release packages, publication slots, metadata versions, community events/actions,
-- membership catalog/entitlements, performance snapshots and qualification runs.

CREATE TABLE release_packages (
  id                      uuid PRIMARY KEY,   -- = ReleasePackage.package_id
  schema_version          text NOT NULL DEFAULT '1.0',
  episode_id              uuid NOT NULL REFERENCES episodes(id),
  version                 integer NOT NULL CHECK (version >= 1),
  package_hash            text NOT NULL UNIQUE CHECK (package_hash ~ '^[0-9a-f]{64}$'),
  body                    jsonb NOT NULL,     -- contracts.ReleasePackage
  media_hashes            jsonb NOT NULL,
  management_policy_hash  text NOT NULL CHECK (management_policy_hash ~ '^[0-9a-f]{64}$'),
  release_scope_hash      text NOT NULL CHECK (release_scope_hash ~ '^[0-9a-f]{64}$'),
  status                  text NOT NULL CHECK (status IN ('DRAFT','READY','BLOCKED','APPROVED','REVISED','REJECTED','SUPERSEDED')),
  gate_blockers           jsonb NOT NULL DEFAULT '[]',
  approval_event_id       uuid REFERENCES approval_events(id),
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  revision                integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (episode_id, version),
  CHECK (status <> 'APPROVED' OR (approval_event_id IS NOT NULL AND jsonb_array_length(gate_blockers) = 0)),
  CHECK (status NOT IN ('DRAFT','READY','BLOCKED') OR approval_event_id IS NULL),
  CHECK (status <> 'READY' OR jsonb_array_length(gate_blockers) = 0),
  CHECK (status <> 'BLOCKED' OR jsonb_array_length(gate_blockers) > 0)
);
CREATE UNIQUE INDEX release_packages_one_approved ON release_packages (episode_id) WHERE status = 'APPROVED';
CREATE TRIGGER release_packages_content_immutable BEFORE UPDATE ON release_packages
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('episode_id', 'version', 'package_hash', 'body', 'media_hashes',
                                                     'management_policy_hash', 'release_scope_hash');

-- One row per publication slot; the SPEC key is unique (MD-014).
CREATE TABLE platform_posts (
  id                          uuid PRIMARY KEY,
  schema_version              text NOT NULL DEFAULT '1.0',
  series_id                   uuid NOT NULL,
  episode_id                  uuid NOT NULL REFERENCES episodes(id),
  part                        integer NOT NULL CHECK (part >= 0),
  locale                      text NOT NULL,
  platform                    text NOT NULL CHECK (platform IN ('TIKTOK','YOUTUBE','FACEBOOK','INSTAGRAM')),
  account_ref                 text NOT NULL,
  release_slot                text NOT NULL,
  dedupe_key                  text NOT NULL UNIQUE CHECK (dedupe_key ~ '^[0-9a-f]{64}$'),
  slot_kind                   text NOT NULL CHECK (slot_kind IN ('FULL_EPISODE','PART','PROMO_CUT','HOOK')),
  required                    boolean NOT NULL,
  release_package_id          uuid NOT NULL REFERENCES release_packages(id),
  approval_event_id           uuid NOT NULL REFERENCES approval_events(id),
  asset_id                    uuid NOT NULL REFERENCES assets(id),
  asset_sha256                text NOT NULL CHECK (asset_sha256 ~ '^[0-9a-f]{64}$'),
  capability_id               uuid,
  capability_version          integer,
  state                       text NOT NULL CHECK (state IN ('RELEASE_APPROVED','SCHEDULED','SUBMITTED','PROCESSING',
                                   'PUBLISHED_VERIFIED','RETRY_WAIT','NEEDS_RECONCILIATION','HELD','FAILED','CANCELLED')),
  iana_zone                   text NOT NULL,
  local_time                  text NOT NULL,
  scheduled_utc               timestamptz NOT NULL,
  depends_on                  jsonb NOT NULL DEFAULT '[]',
  client_token                text NOT NULL UNIQUE,
  provider_operation_id       uuid REFERENCES provider_operations(id),
  external_id                 text,
  url                         text,
  verified_fields             jsonb NOT NULL DEFAULT '[]',
  unverified_fields           jsonb NOT NULL DEFAULT '[]',
  current_metadata_version_id uuid,
  blocker                     text,
  last_error_code             text,
  attempt                     integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  submitted_at                timestamptz,
  verified_at                 timestamptz,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now(),
  revision                    integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (series_id, episode_id, part, locale, platform, account_ref, release_slot),
  CHECK (state <> 'PUBLISHED_VERIFIED' OR (external_id IS NOT NULL AND verified_at IS NOT NULL))
);
CREATE UNIQUE INDEX platform_posts_external_idx ON platform_posts (platform, account_ref, external_id)
  WHERE external_id IS NOT NULL;
CREATE TRIGGER platform_posts_slot_immutable BEFORE UPDATE ON platform_posts
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('series_id', 'episode_id', 'part', 'locale', 'platform', 'account_ref',
                                                     'release_slot', 'dedupe_key', 'release_package_id', 'approval_event_id',
                                                     'asset_id', 'asset_sha256', 'client_token');

CREATE TABLE metadata_versions (
  id                uuid PRIMARY KEY,
  schema_version    text NOT NULL DEFAULT '1.0',
  platform_post_id  uuid NOT NULL REFERENCES platform_posts(id),
  version           integer NOT NULL CHECK (version >= 1),
  metadata          jsonb NOT NULL,           -- contracts.PostMetadata
  metadata_hash     text NOT NULL CHECK (metadata_hash ~ '^[0-9a-f]{64}$'),
  substantive       boolean NOT NULL,
  policy_hash       text NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
  catalog_version   integer NOT NULL,
  rollback_of       uuid REFERENCES metadata_versions(id),
  applied_at        timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (platform_post_id, version)
);
CREATE TRIGGER metadata_versions_content_immutable BEFORE UPDATE ON metadata_versions
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('platform_post_id', 'version', 'metadata', 'metadata_hash',
                                                     'substantive', 'policy_hash', 'catalog_version', 'rollback_of');
CREATE TRIGGER metadata_versions_no_delete BEFORE DELETE ON metadata_versions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE community_events (
  id                    uuid PRIMARY KEY,
  schema_version        text NOT NULL DEFAULT '1.0',
  platform              text NOT NULL,
  account_ref           text NOT NULL,
  provider_event_id     text NOT NULL,
  kind                  text NOT NULL CHECK (kind IN ('COMMENT','REPLY','DIRECT_MESSAGE','MENTION','POST_STATUS')),
  platform_post_id      uuid REFERENCES platform_posts(id),
  external_post_id      text,
  author_ref            text NOT NULL,
  text                  text NOT NULL DEFAULT '' CHECK (char_length(text) <= 5000),
  received_at           timestamptz NOT NULL,
  dm_window_expires_at  timestamptz,
  classification        text,
  status                text NOT NULL CHECK (status IN ('RECEIVED','CLASSIFIED','ACTIONED','SUPPRESSED','DEFERRED','IGNORED')),
  provenance            text NOT NULL,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  revision              integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (platform, account_ref, provider_event_id)
);
CREATE TRIGGER community_events_content_immutable BEFORE UPDATE ON community_events
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('platform', 'account_ref', 'provider_event_id', 'kind', 'author_ref',
                                                     'text', 'received_at');

CREATE TABLE management_actions (
  id                  uuid PRIMARY KEY,
  schema_version      text NOT NULL DEFAULT '1.0',
  kind                text NOT NULL,
  platform            text NOT NULL,
  account_ref         text NOT NULL,
  platform_post_id    uuid REFERENCES platform_posts(id),
  community_event_id  uuid REFERENCES community_events(id),
  dedupe_key          text NOT NULL UNIQUE,
  body                jsonb NOT NULL,          -- contracts.ManagementAction
  policy_hash         text NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
  catalog_version     integer NOT NULL,
  reservation_id      uuid REFERENCES reservations(id),
  decision            text NOT NULL CHECK (decision IN ('PROPOSED','EXECUTED','SUPPRESSED','DEFERRED','FAILED','NEEDS_RECONCILIATION')),
  reason              text,
  external_id         text,
  error_code          text,
  provenance          text NOT NULL,
  executed_at         timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  revision            integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK (decision <> 'SUPPRESSED' OR reason IS NOT NULL)
);
CREATE TRIGGER management_actions_body_immutable BEFORE UPDATE ON management_actions
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('kind', 'platform', 'account_ref', 'dedupe_key', 'body', 'policy_hash',
                                                     'catalog_version');

CREATE TABLE membership_catalog (
  id                          uuid PRIMARY KEY,   -- = MembershipCatalogEntry.entry_id
  schema_version              text NOT NULL DEFAULT '1.0',
  season_id                   uuid NOT NULL REFERENCES seasons(id),
  episode_id                  uuid NOT NULL REFERENCES episodes(id),
  catalog_version             integer NOT NULL CHECK (catalog_version >= 1),
  public_state                text NOT NULL CHECK (public_state IN ('NOT_RELEASED','EARLY_ACCESS_MEMBERS','PUBLIC_FREE','WITHDRAWN')),
  media_finished_and_approved boolean NOT NULL,
  approval_event_id           uuid REFERENCES approval_events(id),
  member_provider             text CHECK (member_provider IN ('PATREON','BUY_ME_A_COFFEE')),
  member_post_id              text,
  member_price_micro_usd      bigint CHECK (member_price_micro_usd >= 0),
  free_release_utc            timestamptz,
  free_release_zone           text,
  public_url                  text,
  member_url                  text,
  body                        jsonb NOT NULL,     -- contracts.MembershipCatalogEntry
  current                     boolean NOT NULL DEFAULT true,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (episode_id, catalog_version),
  CHECK (public_state <> 'EARLY_ACCESS_MEMBERS'
         OR (media_finished_and_approved AND approval_event_id IS NOT NULL AND free_release_utc IS NOT NULL
             AND member_provider IS NOT NULL AND member_price_micro_usd IS NOT NULL)),
  CHECK (coalesce(public_url, '') !~* '[?&](token|access_token|auth|key|signature|sig|secret|code)='),
  CHECK (coalesce(member_url, '') !~* '[?&](token|access_token|auth|key|signature|sig|secret|code)=')
);
CREATE UNIQUE INDEX membership_catalog_one_current ON membership_catalog (episode_id) WHERE current;
CREATE TRIGGER membership_catalog_content_immutable BEFORE UPDATE ON membership_catalog
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('season_id', 'episode_id', 'catalog_version', 'public_state', 'body',
                                                     'approval_event_id', 'free_release_utc', 'member_price_micro_usd');

CREATE TABLE entitlement_links (
  id                   uuid PRIMARY KEY,
  schema_version       text NOT NULL DEFAULT '1.0',
  provider             text NOT NULL CHECK (provider IN ('PATREON','BUY_ME_A_COFFEE')),
  member_ref_hash      text NOT NULL CHECK (member_ref_hash ~ '^[0-9a-f]{64}$'),  -- no raw member identifiers
  catalog_entry_id     uuid NOT NULL REFERENCES membership_catalog(id),
  member_post_id       text,
  active               boolean,                 -- NULL = could not verify (never entitled)
  verification_method  text NOT NULL,
  verified_at          timestamptz NOT NULL,
  last_webhook_event   uuid REFERENCES webhook_events(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  revision             integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (provider, member_ref_hash, catalog_entry_id)
);

CREATE TABLE performance_snapshots (
  id                   uuid PRIMARY KEY,
  schema_version       text NOT NULL DEFAULT '1.0',
  platform_post_id     uuid NOT NULL REFERENCES platform_posts(id),
  platform             text NOT NULL,
  account_ref          text NOT NULL,
  external_post_id     text NOT NULL,
  episode_id           uuid NOT NULL REFERENCES episodes(id),
  snapshot_window      text NOT NULL CHECK (snapshot_window IN ('H24','H72','D7')),
  observed_at          timestamptz NOT NULL,
  definitions_version  text NOT NULL,
  metrics              jsonb NOT NULL,           -- name -> {value|null, definition, denominator}
  country              text,
  traffic              text NOT NULL CHECK (traffic IN ('ORGANIC','PAID','UNKNOWN')),
  sample_count         bigint,
  provenance           text NOT NULL,
  body                 jsonb NOT NULL,           -- contracts.MetricSnapshot
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (platform_post_id, snapshot_window)
);
CREATE TRIGGER performance_snapshots_append_only BEFORE UPDATE OR DELETE ON performance_snapshots
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE qualification_runs (
  id                  uuid PRIMARY KEY,
  schema_version      text NOT NULL DEFAULT '1.0',
  season_id           uuid NOT NULL REFERENCES seasons(id),
  evaluated_at        timestamptz NOT NULL,
  production_status   text NOT NULL CHECK (production_status IN ('QUALIFIED','NOT_QUALIFIED','PENDING')),
  management_status   text NOT NULL CHECK (management_status IN ('QUALIFIED','NOT_QUALIFIED','PENDING')),
  consecutive         integer NOT NULL CHECK (consecutive >= 0),
  body                jsonb NOT NULL,            -- contracts.QualificationResult
  created_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (production_status <> 'QUALIFIED' OR consecutive >= 10)
);
CREATE TRIGGER qualification_runs_append_only BEFORE UPDATE OR DELETE ON qualification_runs
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
