-- 0003 budget accounting (integer micro-USD) and GPU pod leases.
-- The budget service (T005) performs check+reserve inside one transaction holding a
-- row lock on budget_accounts. The CHECK constraints below are a backstop: even a
-- buggy caller cannot commit outstanding + accrued + settled above the cap unless the
-- excess is explicitly recorded as an observed overrun (late billing), never hidden.

CREATE TABLE budget_accounts (
  id                              uuid PRIMARY KEY,
  schema_version                  text NOT NULL DEFAULT '1.0',
  scope_kind                      text NOT NULL CHECK (scope_kind IN ('EPISODE','SEASON_RESEARCH')),
  season_id                       uuid NOT NULL REFERENCES seasons(id),
  episode_id                      uuid REFERENCES episodes(id),
  cap_micro_usd                   bigint NOT NULL CHECK (cap_micro_usd BETWEEN 0 AND 10000000),
  shutdown_reserve_micro_usd      bigint NOT NULL DEFAULT 0 CHECK (shutdown_reserve_micro_usd >= 0),
  reserved_outstanding_micro_usd  bigint NOT NULL DEFAULT 0 CHECK (reserved_outstanding_micro_usd >= 0),
  accrued_micro_usd               bigint NOT NULL DEFAULT 0 CHECK (accrued_micro_usd >= 0),
  settled_micro_usd               bigint NOT NULL DEFAULT 0 CHECK (settled_micro_usd >= 0),
  credits_micro_usd               bigint NOT NULL DEFAULT 0 CHECK (credits_micro_usd >= 0),  -- recorded, never restores allowance
  overrun_micro_usd               bigint NOT NULL DEFAULT 0 CHECK (overrun_micro_usd >= 0),
  paid_dispatch_blocked           boolean NOT NULL DEFAULT false,
  blocked_reason                  text,
  created_at                      timestamptz NOT NULL DEFAULT now(),
  updated_at                      timestamptz NOT NULL DEFAULT now(),
  revision                        integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK ((scope_kind = 'EPISODE') = (episode_id IS NOT NULL)),
  CHECK (shutdown_reserve_micro_usd <= cap_micro_usd),
  CHECK (reserved_outstanding_micro_usd + accrued_micro_usd + settled_micro_usd
         <= cap_micro_usd + overrun_micro_usd),
  CHECK (overrun_micro_usd = 0 OR paid_dispatch_blocked)
);
CREATE UNIQUE INDEX budget_accounts_episode_idx ON budget_accounts (episode_id) WHERE scope_kind = 'EPISODE';
CREATE UNIQUE INDEX budget_accounts_research_idx ON budget_accounts (season_id) WHERE scope_kind = 'SEASON_RESEARCH';
CREATE TRIGGER budget_accounts_identity_immutable BEFORE UPDATE ON budget_accounts
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('scope_kind', 'season_id', 'episode_id', 'cap_micro_usd');

CREATE TABLE budget_category_allocations (
  account_id                      uuid NOT NULL REFERENCES budget_accounts(id),
  category                        text NOT NULL CHECK (category IN ('RESEARCH_SCRIPT_PROMPTS_METADATA','REFERENCES_DIALOGUE',
                                       'GPU_GENERATION','QA_CAPTIONS','CPU_STORAGE_TRANSFER','METERED_MANAGEMENT',
                                       'RECOVERY_HEADROOM')),
  allocated_micro_usd             bigint NOT NULL CHECK (allocated_micro_usd >= 0),
  reserved_outstanding_micro_usd  bigint NOT NULL DEFAULT 0 CHECK (reserved_outstanding_micro_usd >= 0),
  accrued_micro_usd               bigint NOT NULL DEFAULT 0 CHECK (accrued_micro_usd >= 0),
  settled_micro_usd               bigint NOT NULL DEFAULT 0 CHECK (settled_micro_usd >= 0),
  protected                       boolean NOT NULL DEFAULT false,  -- committed production/shutdown funds
  revision                        integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  PRIMARY KEY (account_id, category)
);

CREATE TABLE budget_transfers (
  id               uuid PRIMARY KEY,
  account_id       uuid NOT NULL REFERENCES budget_accounts(id),
  from_category    text NOT NULL,
  to_category      text NOT NULL,
  amount_micro_usd bigint NOT NULL CHECK (amount_micro_usd > 0),
  reason           text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (from_category <> to_category)
);
CREATE TRIGGER budget_transfers_append_only BEFORE UPDATE OR DELETE ON budget_transfers
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE reservations (
  id                      uuid PRIMARY KEY,
  schema_version          text NOT NULL DEFAULT '1.0',
  account_id              uuid NOT NULL REFERENCES budget_accounts(id),
  request_id              uuid NOT NULL UNIQUE,
  semantic_key            text NOT NULL UNIQUE,
  request_hash            text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  category                text NOT NULL,
  queue                   text NOT NULL CHECK (queue IN ('production','publication','community')),
  job_id                  uuid REFERENCES jobs(id),
  provider                text NOT NULL,
  operation_kind          text NOT NULL,
  price                   jsonb NOT NULL,          -- contracts.PriceQuote
  ceilings                jsonb NOT NULL,          -- contracts.ExposureCeilings
  is_shutdown_or_cleanup  boolean NOT NULL DEFAULT false,
  reserved_micro_usd      bigint NOT NULL CHECK (reserved_micro_usd >= 0),
  accrued_micro_usd       bigint NOT NULL DEFAULT 0 CHECK (accrued_micro_usd >= 0),
  settled_micro_usd       bigint NOT NULL DEFAULT 0 CHECK (settled_micro_usd >= 0),
  state                   text NOT NULL CHECK (state IN ('ACTIVE','SETTLED','RELEASED','EXPIRED')),
  expires_at              timestamptz NOT NULL,
  closed_at               timestamptz,
  season_id               uuid,
  episode_id              uuid,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  revision                integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  CHECK ((state = 'ACTIVE') = (closed_at IS NULL))
);
CREATE INDEX reservations_account_state_idx ON reservations (account_id, state);
CREATE TRIGGER reservations_identity_immutable BEFORE UPDATE ON reservations
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('account_id', 'request_id', 'semantic_key', 'request_hash',
                                                     'category', 'reserved_micro_usd', 'price', 'ceilings');
ALTER TABLE provider_operations
  ADD CONSTRAINT provider_operations_reservation_fk FOREIGN KEY (reservation_id) REFERENCES reservations(id);

-- Recorded usage. Unique provider receipt ids make replayed/late receipts idempotent.
CREATE TABLE charges (
  id                   uuid PRIMARY KEY,
  schema_version       text NOT NULL DEFAULT '1.0',
  account_id           uuid NOT NULL REFERENCES budget_accounts(id),
  reservation_id       uuid REFERENCES reservations(id),
  receipt_id           uuid NOT NULL UNIQUE,
  provider             text NOT NULL,
  provider_receipt_id  text NOT NULL,
  kind                 text NOT NULL CHECK (kind IN ('ACCRUAL','SETTLEMENT','CREDIT','ADJUSTMENT')),
  cost_basis           text NOT NULL CHECK (cost_basis IN ('SYNTHETIC_FAKE','PROVIDER_REPORTED','BILLED')),
  provenance           text NOT NULL,
  category             text NOT NULL,
  amount_micro_usd     bigint NOT NULL CHECK (amount_micro_usd >= 0),
  units                bigint NOT NULL CHECK (units >= 0),
  unit                 text NOT NULL,
  interval_start       timestamptz,
  interval_end         timestamptz,
  observed_at          timestamptz NOT NULL,
  job_id               uuid,
  season_id            uuid,
  episode_id           uuid,
  pod_lease_id         uuid,
  receipt              jsonb NOT NULL,          -- contracts.UsageReceipt
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_receipt_id),
  CHECK ((cost_basis = 'SYNTHETIC_FAKE') = (provenance = 'FAKE_SYNTHETIC')),
  CHECK (interval_end IS NULL OR interval_end >= interval_start)
);
CREATE INDEX charges_account_idx ON charges (account_id);
CREATE TRIGGER charges_append_only BEFORE UPDATE OR DELETE ON charges
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- Allocation of shared (season research/reference setup) cost to episodes.
CREATE TABLE cost_allocations (
  id                 uuid PRIMARY KEY,
  source_charge_id   uuid NOT NULL REFERENCES charges(id),
  source_account_id  uuid NOT NULL REFERENCES budget_accounts(id),
  target_account_id  uuid NOT NULL REFERENCES budget_accounts(id),
  amount_micro_usd   bigint NOT NULL CHECK (amount_micro_usd > 0),
  basis              text NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_charge_id, target_account_id),
  CHECK (source_account_id <> target_account_id)
);
CREATE TRIGGER cost_allocations_append_only BEFORE UPDATE OR DELETE ON cost_allocations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- Observed overruns are recorded, never erased or relabelled.
CREATE TABLE cost_overruns (
  id                    uuid PRIMARY KEY,
  account_id            uuid NOT NULL REFERENCES budget_accounts(id),
  charge_id             uuid REFERENCES charges(id),
  amount_micro_usd      bigint NOT NULL CHECK (amount_micro_usd > 0),
  quarantined_profile   text,
  note                  text NOT NULL,
  detected_at           timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER cost_overruns_append_only BEFORE UPDATE OR DELETE ON cost_overruns
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

-- GPU pods -----------------------------------------------------------------------------

CREATE TABLE pod_leases (
  id                      uuid PRIMARY KEY,
  schema_version          text NOT NULL DEFAULT '1.0',
  provider                text NOT NULL,
  pod_id                  text,
  owned_tag               text NOT NULL,
  client_token            text NOT NULL,
  owner_episode_id        uuid NOT NULL REFERENCES episodes(id),
  owner_job_id            uuid REFERENCES jobs(id),
  reservation_id          uuid NOT NULL REFERENCES reservations(id),
  lease_state             text NOT NULL CHECK (lease_state IN ('CLAIMED','ACTIVE','TRANSFERRING','RELEASED','EXPIRED','ORPHANED')),
  pod_state               text NOT NULL CHECK (pod_state IN ('REQUESTED','CREATING','RUNNING','RELEASING','STOPPED','TERMINATED','UNKNOWN')),
  gpu_type                text NOT NULL,
  hourly_price_micro_usd  bigint NOT NULL CHECK (hourly_price_micro_usd >= 0),
  heartbeat_at            timestamptz,
  lease_expires_at        timestamptz NOT NULL,
  accrued_until           timestamptz,
  stop_verified_at        timestamptz,
  transferred_from        uuid REFERENCES pod_leases(id),
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  revision                integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  UNIQUE (provider, client_token)
);
CREATE UNIQUE INDEX pod_leases_live_pod_idx ON pod_leases (provider, pod_id)
  WHERE pod_id IS NOT NULL AND lease_state IN ('CLAIMED','ACTIVE','TRANSFERRING');
-- Pilot rule (SPEC §6): only one episode owns a GPU lease at a time.
CREATE UNIQUE INDEX pod_leases_single_live_lease_idx ON pod_leases ((true))
  WHERE lease_state IN ('CLAIMED','ACTIVE','TRANSFERRING');
CREATE TRIGGER pod_leases_identity_immutable BEFORE UPDATE ON pod_leases
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('provider', 'client_token', 'owned_tag', 'owner_episode_id',
                                                     'reservation_id', 'hourly_price_micro_usd');

-- Each paid pod time interval is attributed exactly once (EXCLUDE forbids overlap).
CREATE TABLE pod_usage_intervals (
  id                uuid PRIMARY KEY,
  provider          text NOT NULL,
  pod_id            text NOT NULL,
  lease_id          uuid NOT NULL REFERENCES pod_leases(id),
  account_id        uuid NOT NULL REFERENCES budget_accounts(id),
  charge_id         uuid REFERENCES charges(id),
  interval_start    timestamptz NOT NULL,
  interval_end      timestamptz NOT NULL,
  basis             text NOT NULL CHECK (basis IN ('COLD_START','DOWNLOAD','RUNNING','IDLE','SHUTDOWN')),
  amount_micro_usd  bigint NOT NULL CHECK (amount_micro_usd >= 0),
  created_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (interval_end > interval_start),
  EXCLUDE USING gist (provider WITH =, pod_id WITH =, tstzrange(interval_start, interval_end, '[)') WITH &&)
);
CREATE TRIGGER pod_usage_intervals_append_only BEFORE UPDATE OR DELETE ON pod_usage_intervals
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
