# A2 design note: budget hierarchy (accounts, steps, amendments, forecasts, costs)

**Version 1.3, 14 Nov 2026. Author: GLM (design note only; one file, no code). Round-3 residuals
closed per [codex-a2-r3.md](codex-a2-r3.md): the five PARTIAL findings (N2R3-1..N2R3-5 — the
allocation-baseline evidence, the runtime-role privilege boundary, deferred step-bounds, the SQL
hierarchy ELSE branch, the service-principal response mapping) are folded in below per their
replacement wording, and §8's global lock order is restated as an enforceable order table
(transaction → locks in order → writes) — **round-3 residuals closed (GLM); operator-authorized
R4 follows**. v1.2 (13 Nov): round-2 rulings per
[a2-recritique-rulings.md](a2-recritique-rulings.md), all 10 findings (N2R2-1..N2R2-10 from
[codex-a2-note-recritique.md](codex-a2-note-recritique.md), 7 BLOCKING + 3 SHOULD-FIX) ACCEPTED;
five were confirmed CLOSED by round 3. v1.1 (same day): round-1 critique per
[a2-critique-rulings.md](a2-critique-rulings.md), all 15 findings (N2-1..N2-15) ACCEPTED; N2-15
strengthens §10.** Requirements:
[phase-A-spec.md](phase-A-spec.md) v0.3 §0, §1, §5 (all), §6, §10 (A2 row + AR-6 activation), §11
(A-T9..A-T11); AC-8, AC-10..AC-14 replacement wording in [codex-a-critique.md](codex-a-critique.md)
(binding per §0) plus its reader/writer inventory; AR-1, AR-2 in
[codex-a-recritique.md](codex-a-recritique.md) (binding); [A1-design-note.md](A1-design-note.md)
v1.2 §1/§2/§6/§9; master [SPEC-v3.md](SPEC-v3.md) v0.4.2 §12.3, §11; [phase-A0-spec.md](phase-A0-spec.md)
v0.4 §5.2/§5.5/§5.6 (the unmetered `llm.subscription` kind). Facts re-verified read-only on
`feat/microdrama-m0-m4` @ `69c4096` (applied tail 0025; 0026 = T031 in `.scratch/t031-gate-h2/`,
0027 = A0, 0028–0031 = A1 — prerequisites, not yet built); v1.1 source references re-verified
read-only @ `b15bea5`; the round-2 source citations folded in by v1.2 (`S/budget/api.py:24`,
`S/budget/billing.py:666`/`:753`, `S/budget/ledger.py:428`, `S/budget/service.py:611`) are
Codex-verified read-only in the round-2 review; v1.3's §8 order table is re-verified read-only @
`dfe67b9` — all seven 451xxx advisory sites (`S/budget/billing.py:256`/`:297`/`:496`/`:828`,
`S/budget/service.py:611`/`:729`/`:761`), the tag-0 provider-operation advisories
(`S/core/provider_ops.py:121`/`:124`, the reservation FOR SHARE guard at `:179-181`), the
janitor's per-pod ingestion call (`S/rendering/janitor.py:1047`; `ingest` opens one self-contained
transaction per pod, `S/budget/billing.py:207-241`), and `resolve_billing_recovery`'s home
(`S/budget/service.py:747-831`). `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`,
`X/` = `microdrama/tests/`.

**A2 builds** the spec §10 A2 row: account kinds and hierarchy serialisation, explicit lookup, step
budgets, the pre-STORY LOCK protocol and LOCK attach, cap amendments, forecasts, cost
reconciliation, the Costs data API — and **activates `create_v3_season` / `create_v3_episodes`**
(AR-6; A1 §6 shipped them returning `NOT_AVAILABLE`).

---

## 1. Migration allocation

Prerequisite pin: T031 (0026) + A0 (0027) + A1 (0028–0031) land first. Applied migration bytes are
never edited — the migrator hashes file bytes and rejects changed checksums (`S/persistence/migrate.py:51`,
`:95`). A2 allocates, one purpose each:

| # | File | Purpose |
|---|------|---------|
| 0032 | `0032_v3_budget_accounts.sql` | Account kinds `SEASON_SETUP`/`SEASON`, `parent_account_id` hierarchy, unique indexes, replaced account CHECKs (cap bound; committed-vs-cap on the row's own base cap — the amendment-aware term is swapped in by 0034's function replacement), kind/version guard triggers |
| 0033 | `0033_v3_budget_mutex_steps.sql` | `season_budget_mutex`, `budget_steps` (+ no-delete/no-truncate/integer guards), `reservations.step_key` (immutable identity + kind rules), `charges.step_key` (+ linkage guard) |
| 0034 | `0034_v3_cap_amendments.sql` | `account_cap_amendments` (predecessor lineage, server-stamped `xact_id`, **`category_baseline` apply-once evidence — N2R3-1**), `budget_accounts.amendment_revision`, `md_apply_cap_amendment()` (the function-only INSERT boundary, N2R2-3; **SECURITY DEFINER, pinned search path, the `md_runtime` grants/revocations — N2R3-2**), `md_row_effective_cap()`/`md_effective_cap()` (lineage-ordered), amendment guards (human session **+ season owner**, V3-only, xact-stamp, AFTER ROW deferred consistency **incl. baseline, step-application and aggregate-bounds validation — N2R3-1/N2R3-3**), the `md_budget_account_rules` replacement, `budget_steps_cap_amendment_only` (**row-time same-transaction/scope/exact-value matching only — N2R2-6/N2R3-3**), the `md_runtime` group role provisioning |

Ordering: 0032's version guard resolves `seasons.workflow_version` (0028); 0033's step guard reads
`budget_accounts.scope_kind` (0032); 0034 reads `budget_category_allocations` (0003:36) and
`budget_steps` (0033) and **replaces** 0032's `md_budget_account_rules` (CREATE OR REPLACE — same
trigger, amendment-aware body) and adds the step-cap guard, because both reference
`account_cap_amendments`, which only 0034 creates. Each migration's trigger bodies reference only
objects that already exist when it applies. A3 starts at 0035.

## 2. Guarded DDL

Guard pattern per A1 §2: `md_immutable_columns` for identity columns, `md_forbid_mutation` for
row DELETE + statement TRUNCATE, `md_forbid_non_integer_numbers` on INSERT OR UPDATE
(`M/0009…sql:94`; the 0026-style DO loop, `.scratch/t031-gate-h2/M/0026…sql:94-99`). The catalog
tests (`X/integration/persistence/test_schema_catalog.py:22-37`, `relkind='r'` only) then cover
every new table automatically, including TRUNCATE (`:57`) and integer-numbers (`:65`).

### 2.1 Migration 0032 — account kinds and hierarchy

Old rule beside new for every changed CHECK on `budget_accounts` (`M/0003…sql:7-30`):

| 0003 rule (old) | 0032 rule (new) |
|---|---|
| `scope_kind IN ('EPISODE','SEASON_RESEARCH')` (`:10`) | `scope_kind IN ('EPISODE','SEASON_RESEARCH','SEASON_SETUP','SEASON')` — plain CHECK replacement |
| `cap_micro_usd BETWEEN 0 AND 10000000` (`:13`) | per-kind bound (constraint trigger, see below): `EPISODE`/`SEASON_RESEARCH` keep `≤ 10_000_000` verbatim; `SEASON_SETUP`/`SEASON` allow `≤ 1_000_000_000` (US$1,000 sanity ceiling; the policy limit stays in Python) |
| `(scope_kind='EPISODE') = (episode_id IS NOT NULL)` (`:25`) | **unchanged** — it already forces `episode_id IS NULL` for the season kinds |
| `shutdown_reserve_micro_usd <= cap_micro_usd` (`:26`) | **unchanged** (base-cap-relative; the setup/season shutdown reserve is 0) |
| `reserved+accrued+settled <= cap_micro_usd + overrun_micro_usd` (`:27-28`, auto-name `budget_accounts_check2`) | dropped; replaced inside the `budget_accounts_rules` trigger below. 0032 ships the row-local predicate `reserved+accrued+settled <= cap_micro_usd + overrun` — identical predicate to 0003:27-28; 0034 swaps the middle term for `md_row_effective_cap(NEW.id, NEW.cap_micro_usd)` once amendments exist. For rows with no amendments the two are the same number, so V1 semantics are the identical predicate throughout |

```sql
ALTER TABLE budget_accounts DROP CONSTRAINT budget_accounts_check2;  -- DO block, fail loudly
ALTER TABLE budget_accounts
  ADD COLUMN parent_account_id uuid REFERENCES budget_accounts(id);

CREATE UNIQUE INDEX budget_accounts_setup_idx ON budget_accounts (season_id)
  WHERE scope_kind = 'SEASON_SETUP';
CREATE UNIQUE INDEX budget_accounts_season_idx ON budget_accounts (season_id)
  WHERE scope_kind = 'SEASON';
-- The V1 indexes stay verbatim (M/0003...sql:31-32): one EPISODE account per episode, one
-- SEASON_RESEARCH envelope per season. A V3 season has no SEASON_RESEARCH account at all.

CREATE FUNCTION md_budget_account_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v text; p record;
BEGIN
  v := (SELECT workflow_version FROM seasons WHERE id = NEW.season_id);
  IF NEW.scope_kind IN ('SEASON_SETUP','SEASON') AND v <> 'v3' THEN
    RAISE EXCEPTION 'season-scope budget accounts exist only for v3 seasons'
      USING ERRCODE='check_violation'; END IF;
  IF NEW.cap_micro_usd < 0 OR (NEW.scope_kind IN ('EPISODE','SEASON_RESEARCH')
      AND NEW.cap_micro_usd > 10000000) OR NEW.cap_micro_usd > 1000000000 THEN
    RAISE EXCEPTION 'cap out of range for scope kind' USING ERRCODE='check_violation'; END IF;
  -- 0032 form: the row's own base cap. 0034 CREATE OR REPLACEs this function, changing only
  -- this term to md_row_effective_cap(NEW.id, NEW.cap_micro_usd) (amendment-aware; N2-2).
  IF NEW.reserved_outstanding_micro_usd + NEW.accrued_micro_usd + NEW.settled_micro_usd
     > NEW.cap_micro_usd + NEW.overrun_micro_usd THEN
    RAISE EXCEPTION 'committed spend exceeds the effective cap unless recorded as overrun'
      USING ERRCODE='check_violation'; END IF;
  IF NEW.parent_account_id IS NOT NULL THEN
    SELECT scope_kind, season_id INTO p FROM budget_accounts WHERE id = NEW.parent_account_id;
    IF NEW.scope_kind NOT IN ('EPISODE','SEASON_SETUP') OR p.scope_kind <> 'SEASON'
       OR p.season_id <> NEW.season_id THEN
      RAISE EXCEPTION 'only a child account may reference its season''s SEASON account'
        USING ERRCODE='check_violation'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER budget_accounts_rules BEFORE INSERT OR UPDATE ON budget_accounts
  FOR EACH ROW EXECUTE FUNCTION md_budget_account_rules();

CREATE FUNCTION md_budget_parent_set_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.parent_account_id IS NOT NULL
     AND NEW.parent_account_id IS DISTINCT FROM OLD.parent_account_id THEN
    RAISE EXCEPTION 'budget account parent is set once at STORY LOCK'
      USING ERRCODE='check_violation'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER budget_accounts_parent_set_once BEFORE UPDATE ON budget_accounts
  FOR EACH ROW EXECUTE FUNCTION md_budget_parent_set_once();
```

**The effective-cap dependency is available before the trigger needs it (N2-2).** Inside a BEFORE
INSERT trigger the account row does not exist yet, so any helper that *selects* `budget_accounts`
by `NEW.id` returns NULL, the comparison becomes NULL, and nothing raises — an overcommitted
account INSERT that 0003:27-28 always rejected would pass. The guard therefore never selects the
not-yet-inserted account: 0032 compares against the row's own `NEW.cap_micro_usd` (the correct
effective cap of a fresh account — it cannot have amendments), and 0034's replacement passes the
base cap as an **explicit fallback**: `md_row_effective_cap(id, fallback)` = the latest amendment's
`new_effective` if one exists, else the fallback. On INSERT no amendment can reference the new id,
so the fallback is exact; on UPDATE base caps are immutable, so `NEW.cap_micro_usd` equals the
stored base. The original committed-cap rejection is thereby preserved on both INSERT and UPDATE,
in V1 and V3 alike.

`budget_accounts_identity_immutable` (`M/0003…sql:33-34`) keeps guarding `cap_micro_usd` — the base
cap stays immutable in both versions; only the effective cap moves, via §5's amendments.
`parent_account_id` is deliberately absent from that trigger's list: it is set once at STORY LOCK
by the set-once trigger above (the `md_benchmark_set_once` pattern,
`.scratch/t031-gate-h2/M/0026…sql:100-113`).

`SEASON` accounts are aggregate-only: no reservation may ever reference them — enforced twice
(Python scope resolution never returns a `SEASON` account, §3.1; 0033's step-linkage guard refuses
any reservation whose account kind is not `EPISODE`/`SEASON_SETUP`). `lock_categories`
(`S/budget/ledger.py:205-214`) still requires the full category set on every account, so SEASON
accounts get category rows with `allocated_micro_usd = 0` at creation.

### 2.2 Migration 0033 — mutex, steps, step attribution

```sql
CREATE TABLE season_budget_mutex (
  season_id  uuid PRIMARY KEY REFERENCES seasons(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION md_v3_season_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT workflow_version FROM seasons WHERE id = NEW.season_id) <> 'v3' THEN
    RAISE EXCEPTION 'v3 budget records exist only for v3 seasons'
      USING ERRCODE='check_violation'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER season_budget_mutex_v3_only BEFORE INSERT ON season_budget_mutex
  FOR EACH ROW EXECUTE FUNCTION md_v3_season_only();
CREATE TRIGGER season_budget_mutex_append_only BEFORE UPDATE OR DELETE ON season_budget_mutex
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE TABLE budget_steps (
  season_id                       uuid NOT NULL REFERENCES seasons(id),
  step_key                        text NOT NULL CHECK (step_key IN
                                    ('step_01','step_02','step_03','step_04','step_05','step_06',
                                     'step_07','step_08','step_09','step_10','launch',
                                     'episode_production')),
  cap_micro_usd                   bigint NOT NULL CHECK (cap_micro_usd >= 0),
  reserved_outstanding_micro_usd  bigint NOT NULL DEFAULT 0 CHECK (reserved_outstanding_micro_usd >= 0),
  accrued_micro_usd               bigint NOT NULL DEFAULT 0 CHECK (accrued_micro_usd >= 0),
  settled_micro_usd               bigint NOT NULL DEFAULT 0 CHECK (settled_micro_usd >= 0),
  revision                        integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  created_at                      timestamptz NOT NULL DEFAULT now(),
  updated_at                      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (season_id, step_key)
);
CREATE TRIGGER budget_steps_identity_immutable BEFORE UPDATE ON budget_steps
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('season_id', 'step_key', 'created_at');
-- counters stay updatable; rows are never deleted (the 0015 mutable-table pattern,
-- M/0015...sql:42-46) — explicit, catalog-tested (N2-8):
CREATE TRIGGER budget_steps_no_delete BEFORE DELETE ON budget_steps
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER budget_steps_no_truncate BEFORE TRUNCATE ON budget_steps
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();  -- TRUNCATE has no rows: a FOR EACH
  -- ROW form is invalid DDL and would fail at migration time (N2R2-6)
-- md_forbid_non_integer_numbers on INSERT OR UPDATE via the §2 DO loop.
-- cap_micro_usd UPDATEs are guarded by 0034's budget_steps_cap_amendment_only (§2.3): a cap
-- change is legal only inside the transaction that recorded an approved amendment naming it.
-- Initial caps are INSERTs and are untouched by that guard.

ALTER TABLE reservations ADD COLUMN step_key text;
ALTER TABLE charges      ADD COLUMN step_key text;

-- Reservation step identity is immutable (N2-8): 0003's trigger is recreated with its exact
-- column list (M/0003...sql:92-93) plus step_key:
DROP TRIGGER reservations_identity_immutable ON reservations;
CREATE TRIGGER reservations_identity_immutable BEFORE UPDATE ON reservations
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns(
    <0003:93 list verbatim>, 'step_key');

CREATE FUNCTION md_reservation_step_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a record; v text;
BEGIN
  SELECT scope_kind, season_id INTO a FROM budget_accounts WHERE id = NEW.account_id;
  v := (SELECT workflow_version FROM seasons WHERE id = a.season_id);
  IF v = 'v1' THEN
    IF NEW.step_key IS NOT NULL THEN
      RAISE EXCEPTION 'v1 reservations carry no step' USING ERRCODE='check_violation'; END IF;
  ELSE  -- v3: SEASON_SETUP and post-LOCK EPISODE accounts take reservations, under their real step
    IF NEW.step_key IS NULL OR a.scope_kind NOT IN ('EPISODE','SEASON_SETUP')
       OR NOT EXISTS (SELECT 1 FROM budget_steps s
                       WHERE s.season_id = a.season_id AND s.step_key = NEW.step_key)
       OR (a.scope_kind = 'EPISODE' AND NEW.step_key NOT IN
           ('step_05','step_06','step_07','step_08','step_09'))
       OR (a.scope_kind = 'SEASON_SETUP' AND NEW.step_key NOT IN
           ('step_01','step_02','step_03','step_04','step_10','launch')) THEN
      RAISE EXCEPTION 'v3 reservations must name a budgeted step of their account kind'
        USING ERRCODE='check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reservations_step_rules BEFORE INSERT OR UPDATE ON reservations
  FOR EACH ROW EXECUTE FUNCTION md_reservation_step_rules();

CREATE FUNCTION md_charge_step_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a record; r record;
BEGIN
  SELECT scope_kind, season_id INTO a FROM budget_accounts WHERE id = NEW.account_id;
  IF (SELECT workflow_version FROM seasons WHERE id = a.season_id) = 'v1' THEN
    IF NEW.step_key IS NOT NULL THEN
      RAISE EXCEPTION 'v1 charges carry no step' USING ERRCODE='check_violation'; END IF;
  ELSIF NEW.reservation_id IS NOT NULL THEN
    SELECT step_key INTO r FROM reservations WHERE id = NEW.reservation_id;
    IF NEW.step_key IS DISTINCT FROM r.step_key THEN
      RAISE EXCEPTION 'a charge carries its reservation''s step' USING ERRCODE='check_violation';
    END IF;
  ELSE  -- unreserved V3 receipt: the caller's step, validated like a reservation (N2-8)
    IF NOT EXISTS (SELECT 1 FROM budget_steps s
                    WHERE s.season_id = a.season_id AND s.step_key = NEW.step_key
                      AND ((a.scope_kind = 'EPISODE' AND s.step_key IN
                            ('step_05','step_06','step_07','step_08','step_09'))
                        OR (a.scope_kind = 'SEASON_SETUP' AND s.step_key IN
                            ('step_01','step_02','step_03','step_04','step_10','launch')))) THEN
      RAISE EXCEPTION 'unreserved v3 charges must name a budgeted step of their account kind'
        USING ERRCODE='check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER charges_step_rules BEFORE INSERT ON charges
  FOR EACH ROW EXECUTE FUNCTION md_charge_step_rules();
```

(`charges` is append-only, `M/0003…sql:128-129`, so its linkage guard is BEFORE INSERT only; the
reservation branch's `SELECT` joins the reservation the charge's `reservation_id` already
references, `M/0003…sql:104`.)

Step-key mapping (settled here; OQ-2): `step_01..step_04`, the teaser `step_10` and `launch` are
**setup scope** — they reserve against the `SEASON_SETUP` account (master §12.3: setup binds steps
1–4, music/SFX libraries, teaser). Steps 5–9 are per-episode production and **keep their real
master-step identities** (N2-7): their reservations carry `step_key='step_05'..'step_09'` — the
actual step, never folded into a production alias — against the episode's `EPISODE` account, and
each step's approved cap is enforced at admission; unused capacity in one production step can
never fund another without an amendment (AC-13's no-spill rule holds between all step rows).
`episode_production` is the derived **production envelope**: a `budget_steps` row per season whose
cap is `episode count × per_episode_base_cap` (the LOCK plan guard, §4 step 6) and whose counters
are maintained as the mirror of `step_05..step_09` — every production reservation/charge moves its
real step row *and* the envelope row by the same delta, so the counter identities hold by
construction: `Σ setup-step counters = setup account counters` and
`Σ(step_05..step_09 counters) = envelope counters = Σ episode-account counters`. The envelope's
relation to the step caps is exact and validated at LOCK and on every amendment:
**`Σ(step_05..step_09 caps) ≤ episode_production cap`** — a step-cap raise that would break it
refuses unless the envelope rises first (a `SEASON` effective-cap amendment, §5). No reservation
or charge ever carries `episode_production`. `charges.step_key` is copied from the reservation at
post time (`S/budget/service.py:1167-1191`); unreserved V3 receipts carry the caller's step on the
contract — `UsageReceipt.step_key` (§2.4), validated by `md_charge_step_rules` above — and V1
charges stay NULL. Every posting path passes the field through: `record_usage` →
`_receipt_account_id` → `_post_charge` → the charge insert (§2.4; N2-8).

Why step counters and no SQL sum backstop: every commitment move on a V3 account applies the
identical delta to its `budget_steps` row (production moves also touch the envelope mirror), so
the two counter identities above hold by construction (tested; §10). Step caps are **plan
guards** (AC-13: no spill between steps without an amendment), enforced at admission under the §6
locks; the hard money backstops stay the account and `SEASON` committed-vs-effective-cap
triggers, because a step's *actual late billing* must be recordable beyond its cap (§3.3) — a
step-sum CHECK would refuse that write.

### 2.3 Migration 0034 — cap amendments and the effective cap

```sql
CREATE TABLE account_cap_amendments (
  id                      uuid PRIMARY KEY,
  account_id              uuid NOT NULL REFERENCES budget_accounts(id),
  predecessor_id          uuid REFERENCES account_cap_amendments(id),
  account_revision        integer NOT NULL CHECK (account_revision >= 1),
  old_effective_micro_usd bigint NOT NULL CHECK (old_effective_micro_usd >= 0),
  new_effective_micro_usd bigint NOT NULL CHECK (new_effective_micro_usd >= 0),
  category_deltas         jsonb NOT NULL,   -- {category: delta int}; must sum to new-old
  category_baseline       jsonb NOT NULL,   -- {category: allocated_micro_usd captured under the
                                            -- function's category locks BEFORE any delta is
                                            -- applied}; SQL-visible apply-once evidence bound to
                                            -- this row (N2R3-1); '{}' only on the SEASON aggregate
  step_deltas             jsonb NOT NULL DEFAULT '{}',  -- {step_key: new cap}; optional, same tx
  actor_owner_id          uuid NOT NULL REFERENCES owners(id),
  actor_session_id        uuid NOT NULL REFERENCES human_sessions(id),
  reason                  text NOT NULL CHECK (length(trim(reason)) BETWEEN 1 AND 500),
  idempotency_key         text NOT NULL UNIQUE,
  approved_at             timestamptz NOT NULL DEFAULT clock_timestamp(),  -- audit metadata only
  created_at              timestamptz NOT NULL DEFAULT now(),
  xact_id                 xid8 NOT NULL DEFAULT pg_current_xact_id(),
  UNIQUE (account_id, account_revision),   -- one strict chain per account (N2-4)
  UNIQUE (predecessor_id)                  -- a predecessor has at most one successor: no forks
);
CREATE TRIGGER account_cap_amendments_append_only BEFORE UPDATE OR DELETE ON account_cap_amendments
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

ALTER TABLE budget_accounts
  ADD COLUMN amendment_revision integer NOT NULL DEFAULT 0 CHECK (amendment_revision >= 0);

CREATE FUNCTION md_row_effective_cap(p_account_id uuid, p_fallback bigint)
  RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    (SELECT a.new_effective_micro_usd FROM account_cap_amendments a
      WHERE a.account_id = p_account_id
      ORDER BY a.account_revision DESC LIMIT 1),   -- serialized lineage order, never timestamps
    p_fallback) $$;
CREATE FUNCTION md_effective_cap(p_account_id uuid) RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT md_row_effective_cap(p_account_id,
    (SELECT b.cap_micro_usd FROM budget_accounts b WHERE b.id = p_account_id)) $$;

-- 0034 replaces 0032's committed-cap term (N2-2): CREATE OR REPLACE FUNCTION
-- md_budget_account_rules() with the middle term md_row_effective_cap(NEW.id,
-- NEW.cap_micro_usd); the budget_accounts_rules trigger itself is untouched.
```

The lineage — not the clock — orders the amendments (N2-4): `md_row_effective_cap` derives the
effective cap from `account_revision DESC` (the serialized chain order, enforced by the two
UNIQUE constraints), so the last *serialized* amendment always wins;
`approved_at`/`created_at`/`id` are audit metadata and never enter the derivation.

Two BEFORE INSERT guards stamp and validate human authority, a third server-stamps transaction
identity, and an **AFTER ROW constraint trigger** validates the amendment's final transaction
state (N2-3 — PostgreSQL constraint triggers are necessarily AFTER ROW, which is why the
consistency guard is not a BEFORE trigger):

1. **`md_cap_amendment_requires_human_session`** (BEFORE INSERT; the 0007
   `md_approval_requires_human_session` pattern, `M/0007…sql:5-21`) — live session, owner match,
   server clock (`approved_at := clock_timestamp()`), **and the actor owns the account's season**
   (N2-9): `EXISTS (SELECT 1 FROM season_owners WHERE season_id = <the account's season> AND
   owner_id = NEW.actor_owner_id)`. A live session proves authentication; the `season_owners` row
   proves account-scope authorization — an authenticated owner of a *different* season cannot
   fabricate an amendment here. This is the "direct mutation refused by a guard trigger"
   backstop, and `cap_micro_usd` itself is immutable (`M/0003…sql:33-34`).
2. **`md_cap_amendment_v3_only`** (BEFORE INSERT) — the account's season must be
   `workflow_version='v3'` (V1 accounts can never be amended, AC-11/A-T9).
3. **`md_cap_amendment_xact_stamped`** (BEFORE INSERT) — `NEW.xact_id := pg_current_xact_id()`,
   overwriting any caller-supplied value: transaction identity is **server-stamped**, never
   trusted from the row (N2R2-6). Every later guard that matches "inserted by the same
   transaction" (`budget_steps_cap_amendment_only`, the deferred multiple-amendment refusal
   below) compares against the stamped value, so a forged `xact_id` buys nothing.
4. **`md_cap_amendment_consistent`** — `CREATE CONSTRAINT TRIGGER … AFTER INSERT ON
   account_cap_amendments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW`, validated at commit
   against the **final** table state. The tip question is split by phase (N2R2-2): the **prior
   tip is validated before insertion, under the function's locks** (predecessor = current tip,
   `account_revision = tip.account_revision + 1` — where the caller-facing `StaleRevision`
   comes from); at **deferred** validation the inserted amendment is already the tip, so the
   guard never tests a row against itself — it verifies the stored relationships instead:
   - lineage: the row's `predecessor_id` exists (or is `NULL` only when the account has no other
     amendment), `account_revision = predecessor.account_revision + 1` (or `1` when `NULL`),
     `old_effective = COALESCE(predecessor.new_effective, base cap)` — re-derived in SQL from the
     row's **own predecessor**, not from timestamps, UUIDs or the now-moved tip — and the row is
     the account's **final tip**: no other amendment for the account has a higher revision. The
     UNIQUE constraints make a fork impossible; the deferred guard proves the stored chain is the
     one the locks validated;
   - **exactly one amendment per account per transaction**: two rows for one account sharing a
     server-stamped `xact_id` are **refused** (N2R2-2). The sanctioned path writes exactly one;
     nothing in V3 needs two in a single transaction;
   - **commitment floor** (SQL-side, not Python-only — N2-4): `new_effective ≥ account.committed`
     (`reserved+accrued+settled`);
   - **ancestor limit** for child accounts (`SEASON_SETUP`, `EPISODE`):
     `new_effective ≤ md_effective_cap(parent) − (parent.committed − account.committed)` (the §5
     rule, SQL-enforced);
   - spending accounts: `Σ category_deltas = new − old`, every category named exactly once with
     an integer delta, and **each category's final allocation checked per category against the
     row's stored baseline** — `final allocated(c) = category_baseline(c) + delta_c`
     (**N2R3-1**: the baseline is captured under the function's category locks before any delta
     is applied and stored on the amendment row itself, so the deferred trigger reads
     SQL-visible evidence, never a value a caller held in memory) **plus** `(SELECT
     SUM(allocated_micro_usd) FROM budget_category_allocations WHERE account_id = …) =
     new_effective` — the CostPolicy "allocation sums to the cap" invariant
     (`S/contracts/season.py:117-118`) on effective caps. **Missing evidence refuses**: the
     column is NOT NULL, and the deferred trigger additionally requires the baseline to cover
     every category of the account exactly once with integer values (an absent, empty or short
     baseline on a spending account raises at commit). Per-category equality against the stored
     baseline is what catches a skipped or doubled **zero-net** redistribution (a `+x/−x` pair
     leaves the sum untouched while breaking both categories; N2R2-2/N2R3-1); the sum invariant
     catches everything else. An inserter that applied the deltas twice, not at all, or only in
     part fails one of the two (deltas validated once, never added twice);
   - **step application and aggregate bounds — deferred, never row-time (N2R3-3):** every
     `step_deltas` key's `budget_steps.cap_micro_usd` equals its approved value in the completed
     transaction state (a partially applied amendment — some named steps updated, others not —
     refuses at commit), and the completed state passes `Σ setup step caps ≤ setup effective
     cap` and `Σ(step_05..step_09 caps) ≤ episode_production cap` (§2.2). These live here, on
     the amendment's final state, because a row-time check inside
     `budget_steps_cap_amendment_only` rejects a valid multi-step reduction: lowering a setup
     cap 100→50 while its steps go 50/50→25/25 leaves an intermediate total of 75 at the first
     step update — commit-time state is the only sound witness (N2R3-3);
   - the aggregate `SEASON` account: `category_deltas = '{}'`, `category_baseline = '{}'`, and
     its allocations remain 0 (no reservation ever lands there).

The sanctioned write path is one SQL function, so the serialisation is not caller-dependent
(N2-4). `md_apply_cap_amendment(p_account_id, p_predecessor_id, p_old_effective, p_new_effective,
p_category_deltas, p_step_deltas, p_actor_owner_id, p_actor_session_id, p_reason,
p_idempotency_key, p_amendment_id) RETURNS integer`, called by the §5 command inside its
transaction. The function runs the **same protocol as §3.2's helper** — fetch and verify the
mutex row, re-read kind and attachment under it (N2R2-1) — then validates the prior tip under
locks, locks the affected step/category rows and captures the **category baseline** under those
locks (N2R3-1), before inserting (N2R2-2):

```sql
-- §6-#7 order throughout: mutex → SEASON (child amendments) → account → amendment tip
-- → budget_steps → categories — the baseline is captured HERE, under these locks (N2R3-1)
SELECT 1 INTO STRICT v_mutex FROM season_budget_mutex WHERE season_id = v_season FOR UPDATE;
-- SELECT … INTO STRICT: a missing mutex row RAISES (never a silent PERFORM pass; N2R2-1)
SELECT scope_kind, parent_account_id INTO v_acct FROM budget_accounts WHERE id = p_account_id;
-- kind/attachment re-read UNDER the mutex — the §3.2 protocol, in SQL (N2R2-1):
IF v_acct.scope_kind = 'SEASON' THEN
  v_parent := NULL;               -- the aggregate account has no parent, by design
ELSIF v_acct.parent_account_id IS NOT NULL THEN
  v_parent := v_acct.parent_account_id;      -- attached child: lock its CURRENT parent
  PERFORM 1 FROM budget_accounts WHERE id = v_parent FOR UPDATE;
ELSIF v_acct.scope_kind = 'SEASON_SETUP'
      AND NOT EXISTS (SELECT 1 FROM budget_accounts WHERE season_id = v_season
                      AND scope_kind = 'SEASON') THEN
  v_parent := NULL;               -- ONLY a pre-LOCK SEASON_SETUP may lack a parent (N2R3-4)
ELSE
  RAISE EXCEPTION 'budget hierarchy detached';
  -- every OTHER parentless kind refuses even before the aggregate exists (N2R3-4): the SQL
  -- branch matches the Python helper exactly — a parentless V3 EPISODE is corruption,
  -- never a tolerated pre-LOCK state
END IF;
SELECT * INTO v_account FROM budget_accounts WHERE id = p_account_id FOR UPDATE;
SELECT * INTO v_tip FROM account_cap_amendments WHERE account_id = p_account_id
  ORDER BY account_revision DESC LIMIT 1 FOR UPDATE;
-- validate the PRIOR tip under these locks (N2R2-2): predecessor = tip (NULL only when no
-- tip); old_effective = tip.new_effective else base (the caller surfaces StaleRevision);
-- commitment floor; ancestor limit; then the §6-#7 tail:
PERFORM 1 FROM budget_steps s WHERE s.season_id = v_season AND s.step_key IN
  (SELECT jsonb_object_keys(p_step_deltas)) FOR UPDATE;
PERFORM 1 FROM budget_category_allocations WHERE account_id = p_account_id FOR UPDATE;
SELECT COALESCE(jsonb_object_agg(category, allocated_micro_usd), '{}'::jsonb)
  INTO v_baseline FROM budget_category_allocations WHERE account_id = p_account_id;
-- ^ CAPTURE THE BASELINE (N2R3-1): every category's allocation, read under the row locks
--   taken above, BEFORE any delta is applied — stored on the amendment row as SQL-visible
--   apply-once evidence the deferred trigger reads at commit
-- INSERT the amendment row (carrying category_baseline) and advance the account revision
-- atomically with the delta application; category deltas and step_deltas apply ONCE (one
-- UPDATE per named key — each step UPDATE passes 0034's budget_steps_cap_amendment_only row
-- guard because the amendment row of THIS transaction names it; the aggregate bounds are
-- proven deferred against the completed state, N2R3-3):
UPDATE budget_accounts SET amendment_revision = v_rev  -- = COALESCE(tip.account_revision,0) + 1
  WHERE id = p_account_id;
RETURN v_rev;
```

0034 also creates **`budget_steps_cap_amendment_only`** (BEFORE UPDATE ON `budget_steps`,
`FOR EACH ROW`): `cap_micro_usd` may change only when an amendment row naming that `step_key`
was inserted **by the same transaction** (matched against the **server-stamped** `xact_id`,
guard 3) for a budget account of this step's season **whose kind owns the step** (permitted step
scope: `SEASON_SETUP` amendments move the setup steps, episode-count/`SEASON` amendments move the
production steps and the envelope, §5), and **the new cap equals the amendment's
`step_deltas[step_key]` exactly**. Strict value matching (N2R2-6): naming the step in a
same-transaction amendment permits **only the approved value** — an update of a named step to a
different, unapproved amount is refused, and §10's direct-SQL tests reject exactly that. The
**row-time final-bounds check is gone by design (N2R3-3)**: `Σ setup step caps ≤ setup
effective cap` and `Σ(step_05..step_09 caps) ≤ episode_production cap` (§2.2) are validated
**deferred, against the amendment's completed transaction state**, by guard 4 above — a row-time
aggregate bound would reject the valid multi-step reduction (the first of two step updates
crosses the new total before the second lands) and refuse a legal amendment. Initial caps are
INSERTs and are untouched by the guard.

**Direct INSERTs are unavailable — an explicitly enforced function-only write boundary
(N2R2-3/N2R3-2).** Locks, predecessor/revision validation and `amendment_revision` advancement
live in `md_apply_cap_amendment`; guards that merely authenticate and check final state cannot
conjure those locks. **The boundary needs a real privilege separation to enforce (N2R3-2), so a
distinct non-superuser runtime role is an explicit prerequisite:** 0034 idempotently provisions
the group role `md_runtime` (`NOLOGIN`, `NOSUPERUSER`, never a member of — and never granted —
the migration-owner role), `REVOKE`s `INSERT, UPDATE, DELETE ON account_cap_amendments FROM
PUBLIC` and from `md_runtime`, and grants the runtime role exactly what the application needs:
`SELECT`/`UPDATE` on the working tables and `EXECUTE` on `md_apply_cap_amendment` — nothing that
carries table INSERT. Ownership stays with the migration owner; because role membership is the
only inherited path to the owner's table privileges, **runtime INSERT is unavailable through
every inherited grant**. The application's login roles (and the test harness's second DSN) get
`GRANT md_runtime TO <login>` — membership in `md_runtime` only. `md_apply_cap_amendment` is
`SECURITY DEFINER`, owned by the migration owner, `SET search_path = pg_catalog`, with every
table/function reference **schema-qualified** (`public.account_cap_amendments`, …) — a pinned
trusted search path that a hostile session `search_path` cannot redirect. Today's harness gaps
are recorded, not inherited: the test fixtures migrate and run services through one superuser
DSN (`X/conftest.py:42`) and staging runs the PostgreSQL bootstrap user
(`deployment/compose.staging.yaml:33`) — A2's conftest provisions `md_runtime`, a login role in
it, and runs the boundary negatives **through that login's DSN** (§10; provisioning the runtime
role in the staging composition is a deployment prerequisite of the A2 build). Every amendment
INSERT — whatever the caller — then runs inside the one function that acquires the verified
hierarchy chain (mutex verified, attachment re-read under it, N2R2-1), re-reads the prior tip,
captures the baseline (N2R3-1), validates revision/floor/ancestor limits and advances the
account's `amendment_revision` atomically with the insert: **equivalent serialization for every
writer** (N2R2-3 ruling). Defense in depth for a privileged session that regains INSERT: guards
1–2 authenticate and scope, guard 3 server-stamps `xact_id`, guard 4 refuses inconsistent final
state, missing baseline evidence, lineage error, or a second same-account row in one transaction
— the money backstop is SQL-side either way (N2-4).

`md_effective_cap` is the **one** deterministic effective cap used by the SQL guards
(0034's replaced committed trigger) **and** by Python ledger loading. Every `AccountRow`
constructor/query is inventoried and provides the field consistently (N2-11): `account_from_row`
(`S/budget/ledger.py:116-132`, the only constructor) is fed by `lock_account`
(`S/budget/ledger.py:198-202`, `SELECT *, md_effective_cap(id) AS effective_cap_micro_usd … FOR
UPDATE`), the report reads (`S/budget/reports.py:52`, `:62`) and the §6 route's account queries —
each gains the same alias, so `AccountRow.effective_cap` is always populated and no reader
silently falls back to the base cap. The id-only lookups (`S/budget/ledger.py:180`/`:190`,
`S/review/intake.py:936`, `S/review/service.py:325`, `S/story/service.py:1117`) select no cap and
need no alias; the account factories' re-open comparisons (`S/budget/service.py:245`/`:282`)
compare the immutable **base** cap at creation and stay on `cap_micro_usd`. All cap math moves to
`effective_cap`; `cap` remains the immutable base the US$10 episode rule binds (master §12.3;
amendments may raise an episode's *effective* cap). Readers whose queries match account **kinds**
shared by both workflow versions get explicit `seasons.workflow_version` guards (§9:
`S/analytics/cost.py`) — account kind alone does not discriminate workflow version (N2-11).

### 2.4 Catalog and contract updates

`EXPECTED_TABLES` (`X/integration/persistence/test_migrations.py:32`, asserted at `:117`) gains
`season_budget_mutex`, `budget_steps`, `account_cap_amendments`. All three tables get the standard
no-TRUNCATE + integer-numbers DO loop (§2 preamble; `budget_steps`' explicit no-delete trigger is
§2.2). Generated contracts change and are regenerated
(`microdrama/Makefile:33` drift check): `BudgetScopeKind += SEASON_SETUP`
(`S/contracts/enums.py:200-202`), `BudgetReservationRequest.step_key` + `_scope_and_bound`
(`S/contracts/cost.py:160-191`) setup-scope rule (names `season_id`, no `episode_id`), the new
`UNSUPPORTED_SCOPE` error, the amendment command contract, **`UsageReceipt.step_key`**
(`S/contracts/cost.py:194-219` gains the optional field — the unreserved-receipt step contract;
`None` for V1, the caller's validated step for V3; every posting path carries it to the charge
insert, N2-8), the `SeasonCostsV3` response with its split panels (§6), the
`budget.cap_amended` event schema and the `season.created` event schema (`{season_id,
workflow_version}` — §7, N2R2-8; dotted names valid: `S/contracts/events.py:21`, `M/0001…sql:118`).

## 3. Lookup and admission

### 3.1 Explicit scope lookup (AC-10)

`S/budget/service.py:372-375` today: `EPISODE → episode_account_id`, **everything else →
`research_account_id`** — an unkindled scope silently rides the research envelope. Replaced by an
explicit dispatch (the V1 fallback kept **for V1 only**):

```python
def resolve_reservation_account(tx, request) -> UUID:
    if request.scope_kind is BudgetScopeKind.EPISODE:
        return episode_account_id(tx, request.episode_id)          # S/budget/ledger.py:177-185
    if request.scope_kind is BudgetScopeKind.SEASON_RESEARCH:
        if _season_version(tx, request.season_id) == "v3":
            raise UnsupportedScope("v3 seasons have no research envelope")
        return research_account_id(tx, request.season_id)          # S/budget/ledger.py:188-195
    if request.scope_kind is BudgetScopeKind.SEASON_SETUP:
        if _season_version(tx, request.season_id) != "v3":
            raise UnsupportedScope("setup accounts exist only for v3 seasons")
        return setup_account_id(tx, request.season_id)             # new; unique index §2.1
    raise UnsupportedScope(f"unsupported budget scope kind: {request.scope_kind}")
```

`UnsupportedScope` (new, code `UNSUPPORTED_SCOPE`) is never a silent route: today's contract enum
(`S/contracts/cost.py:142`) admits only EPISODE/SEASON_RESEARCH, so no V1 caller can hit the new
branches; the final `else` makes any future unkindled scope a hard refusal instead of research
fallback. Receipt routing mirrors it: `_receipt_account_id` (`S/budget/service.py:1009-1014`) keeps
reservation → its account and episode → episode account, and the season branch becomes
version-aware — v1 → `research_account_id`, v3 → `setup_account_id` (a V3 season's unreserved
receipts are setup spend; a receipt naming a V3 episode routes to that episode account unchanged).
The critique's reader/writer inventory rows R14/R15 (account factories/lookups, receipt routing,
policy ownership) are covered by §3, §5, §7 and §9.

### 3.2 The lock chain helper

One helper, called before any child lock in every commitment-changing path (§8 audits each):

```python
def lock_budget_hierarchy(tx: Tx, account_id: UUID) -> AccountRow | None:
    """§6-#7 order: season_budget_mutex → SEASON → (caller locks the child next).
    Mutex-first, mutex-verified (N2-1/N2R2-1): only immutable identity is read before the
    mutex; the mutex row is fetched FOR UPDATE and verified (a missing row never passes
    silently); account kind and attachment are re-read under it. Returns None for V1
    accounts, the SEASON account itself, and pre-LOCK setup accounts. Returns the locked
    parent row for admission and mirroring."""
    ident = tx.fetchone(
        "SELECT a.season_id, s.workflow_version FROM budget_accounts a "
        "JOIN seasons s ON s.id = a.season_id WHERE a.id = %s", (account_id,))
    if ident is None or ident["workflow_version"] != "v3":
        return None
    mutex = tx.fetchone(                          # fetch AND verify the mutex row (N2R2-1)
        "SELECT 1 FROM season_budget_mutex WHERE season_id = %s FOR UPDATE",
        (ident["season_id"],))
    if mutex is None:                             # every V3 season creates it (§4): corruption
        raise Conflict("season budget mutex missing")
    acct = tx.fetchone(                           # kind + attachment re-read UNDER the mutex
        "SELECT scope_kind, parent_account_id FROM budget_accounts WHERE id = %s",
        (account_id,))
    if acct["scope_kind"] == "SEASON":
        return None                # the aggregate account has no parent, by design (N2R2-1)
    if acct["parent_account_id"] is not None:     # attached children require their CURRENT parent
        return lock_account(tx, acct["parent_account_id"])   # the locked row (idempotent in-tx)
    attached = tx.fetchone(                       # parentless: only pre-LOCK SEASON_SETUP is legal
        "SELECT 1 FROM budget_accounts WHERE season_id = %s AND scope_kind = 'SEASON'",
        (ident["season_id"],))
    if attached is None and acct["scope_kind"] == "SEASON_SETUP":
        return None                               # pre-LOCK setup: no parent yet
    raise Conflict("budget hierarchy detached")
```

Nothing mutable is read before the mutex (N2-1): `season_id`/`workflow_version` are immutable
identity, but `parent_account_id` **is re-read under the mutex** — a setup mutation that read
`NULL`, queued behind the STORY LOCK transaction and then acquired the mutex now re-reads the
post-LOCK attachment and locks the existing parent instead of skipping it (set-once immutability
does not make a pre-mutex NULL read stable). The mutex row itself is **verified, not assumed**
(N2R2-1): a V3 season creates it in the same transaction as its first budget row (§4), so its
absence is corruption and raises — the previous `execute` form returned no rows and passed
silently. **The SEASON account returns `None`** — it has no parent by design, and a parentless
probe that asked "does this season have a SEASON account?" would find *itself* and raise
spuriously, breaking §5's SEASON amendments (the operator's aggregate-cap remedy, N2R2-1); a
SEASON amendment simply locks the SEASON row itself as its account next. Parent absence is an
error **once hierarchy attachment has occurred**: the probe asks whether the season's `SEASON`
account exists (created only inside the LOCK attach, §4, and never deleted), and a parentless
child of any other kind — or a `SEASON_SETUP` account after the aggregate exists — is detached;
the raise is `Conflict("budget hierarchy detached")`, reachable only on corruption because the
attach is atomic. **The same protocol runs in the SQL amendment path** (§2.3's
`md_apply_cap_amendment`: `SELECT … INTO STRICT` mutex, kind/attachment re-read under it,
N2R2-1), so Python and SQL serialise identically. The helper returns the locked parent row —
§3.3's aggregate check and ledger mirroring use the row they serialised on, not a second read.
Pre-LOCK setup mutations get `None` (mutex → setup account, no parent) — exactly AR-2's protocol.

### 3.3 Admission, in order (AC-13/AC-12; spec §5.2)

Pseudo-code against the real functions — `reserve()` (`S/budget/service.py:322-481`) keeps its
structure; the numbered comments map to the spec's admission order:

```python
def reserve(self, request):                                   # service.py:322
    policy.check_queue_may_reserve(request.queue, request.category)   # policy.py:42 (unchanged)
    policy.check_price_admissible(request, self._settings)            # policy.py:94  — 1. unit price/ceiling
    cleanup = policy.shutdown_grant(...)                              # policy.py:65 (unchanged)
    cleanup_exempt = v3 and cleanup     # authorized V3 cleanup only (prose below); V1 is never exempt
    with self._db.transaction() as tx:
        account_id = resolve_reservation_account(tx, request)         # §3.1 (replaces :372-375)
        parent = lock_budget_hierarchy(tx, account_id)                # §3.2 — mutex → SEASON; N2-1
        acct = lock_account(tx, account_id)                           # ledger.py:198 (child)
        step  = lock_step(tx, acct.season_id, request.step_key)       # 0033 row (V3 only)
        cats  = lock_categories(tx, account_id)                       # ledger.py:205
        ledger = self._ledger(tx, acct, cats, step=step, parent=parent)
        # blocked/replay/expiry/scope checks unchanged (:381-402); V3 adds: parent blocked → refuse
        if v3 and parent is not None and parent.blocked and not cleanup_exempt:
            raise BudgetExhausted("season overrun")                    # 3.3 truthfulness
        # 2. step cap — no spill between steps (refuse, never borrow):
        if v3 and step.committed + worst > step.cap and not cleanup_exempt:
            raise BudgetExhausted("step budget exhausted", step_key=...)
        # 3. child account (cap + category) — today's checks on effective_cap:
        floor = 0 if cleanup else acct.shutdown_reserve
        if acct.committed + worst + floor > acct.effective_cap and not cleanup_exempt:
            raise BudgetExhausted(...)                                # was :404-414 against cap
        #    recovery-headroom rule unchanged (:415-427) — ordinary admission only; its
        #    category/spill FEASIBILITY is computed without mutation (N2-14): the transfer
        #    amount is calculated here and no budget_transfers row is written until every
        #    check below has passed. cleanup_exempt skips spill feasibility entirely (N2R2-5):
        #    authorized cleanup never depends on available recovery allocation — the
        #    headroom refusal at S/budget/ledger.py:428 is not consulted — and no transfer
        #    is attempted, funded or not
        # 4. SEASON aggregate (post-LOCK only; the locked parent row is mirrored):
        if v3 and parent is not None and parent.committed + worst > parent.effective_cap \
           and not cleanup_exempt:
            raise BudgetExhausted("season envelope exhausted")
        # every admission check is complete before any write; one atomic tail (N2-14).
        # cleanup performs NO allocation transfer (N2R2-5): nothing is borrowed from recovery —
        if spill_shortfall > 0 and not cleanup_exempt:
            ledger.apply_spill(target=request.category, shortfall=spill_shortfall,
                               floor=floor, reason=f"auto-spill:{request.semantic_key}")
        insert_row(tx, "reservations", {..., "step_key": request.step_key})   # was :446-470
        ledger.move(request.category, step_key, reserved=worst)  # actual category counters; mirrors
                                                                 # child+step(+envelope)+parent
        if cleanup_exempt:
            ledger.pre_record_overrun(parent)   # N2-6/N2R2-5: the required child/parent overrun
                                                # increments and cost_overruns rows are recorded,
                                                # blocked flags set, BEFORE flush — regardless of
                                                # category allocations (charge_id NULL allowed)
        ledger.flush()
```

(`Ledger.spill_from_recovery` at `S/budget/ledger.py:423-441` splits into the pure feasibility
check it already performs and `apply_spill` — the `move_allocation` write
(`S/budget/ledger.py:417-421`); same computation, the write moved after all checks.)

**Why admission can never exceed a cap at any level.** Every commitment-changing path takes the
same chain — mutex → SEASON → child → step → categories (§5.3; §8) — so the `committed` counters and
`md_effective_cap` an admission reads are stable for its transaction: amendments, the only writers
of effective caps, take the same chain (§5). Each check adds `worst` to the current committed at its
level and refuses on exceeding that level's effective cap; the transfer, insert and counter move
happen in the same transaction, so at commit `committed' = committed + worst ≤ effective` holds at
step, child and season simultaneously. **Ordinary paid admission never creates overrun**
(N2-15/N2R2-5): every refusal fires before any write, so `overrun_micro_usd` and `cost_overruns`
grow only through actual billing beyond a cap — or through the **one documented exception,
authorized V3 cleanup**, which records its overrun at admission by design (below). The §10 race
tests assert the stronger post-admission invariant `committed ≤ effective` (no erroneous
admission disguised as overrun) at the admitting level **for ordinary paid admissions only;
cleanup's admission-recorded overrun is tested separately** (N2R2-5/N2R2-10).
Attribution is not a commitment: V3 `cost_allocations` never move counters
(§6), so nothing is counted twice, and expired/unknown exposure stays counted (`Ledger.expire`
moves reserved→accrued, committed unchanged, `S/budget/ledger.py:388-396`; release is refused while
operations are in flight, `S/budget/service.py:526-539`).

**Truthful overrun and `BLOCKED (overrun)`.** Usage posting never refuses on a cap
(`record_usage` docstring, `S/budget/service.py:850-852`): `_post_charge`
(`S/budget/service.py:1154-1224`) applies the receipt and calls `check_overrun`
(`S/budget/ledger.py:443-471`), which records the excess in `cost_overruns` and sets
`paid_dispatch_blocked`. For V3 the same deltas mirror into the parent, and `check_overrun` runs
on the child and, separately, on the **SEASON** row. The two cases are distinct (N2-15): a
**child-level** excess blocks paid work on that child only, while the season aggregate remains
within its cap; a **season-level** excess blocks paid work across every child account. §10 tests
child-only and aggregate overrun separately.
Blocked admission surfaces as `BudgetExhausted` (`:381-386`), callers defer with A0's `BUDGET`
reason (A0 §5.2) and `track_waits` projects `WAITING_BUDGET` (A1 0031); the data API (§6) exposes
`overrun_micro_usd` and `paid_dispatch_blocked` so the UI labels the scope `BLOCKED (overrun)`.

**Cleanup and shutdown are never refused** (A-T10 "shutdown proceeds with exhausted caps"). Today a
flagged cleanup bypasses the blocked flag and the floor but "still has to fit the cap"
(`S/budget/service.py:335-341`). For **V3** accounts an authorized cleanup (still only
`pod.stop`/`pod.terminate`/`storage.cleanup`, `S/budget/policy.py:56-86`) is **exempt from the
exhausted step, category, child-cap and season-aggregate refusals and from category/spill
feasibility** — steps 2–4, the category refusal and the spill-feasibility computation above
(`cleanup_exempt`): authorized cleanup **never depends on available recovery allocation**
(`spill_from_recovery`'s headroom refusal, `S/budget/ledger.py:428`, is not consulted) and
**performs no allocation transfer** — nothing is borrowed from recovery or any other category, so
it succeeds with zero recovery headroom (N2R2-5). The hold is admitted, its actual category
counters recorded, and the `overrun_micro_usd` increments it requires on the child **and** the
parent are recorded — blocked flags set — before the counter `flush`
(`pre_record_overrun` above, with `cost_overruns` rows — **a NULL charge reference is allowed while
the exposure is reservation-only**; the column is nullable, `M/0003…sql:150`) so the
committed-vs-effective-cap trigger sees `committed ≤ effective + overrun` and admits. Stop/terminate
execution and truthful accounting survive even a failed reservation admission (N2-6): if the hold
cannot be inserted at all, the stop still runs and its cost posts through the unreserved-receipt
path with the overrun recorded truthfully (master §12.3's "existing cleanup/shutdown exception");
paid dispatch stays blocked. **V1 keeps today's behaviour unchanged** (fit-the-cap refusal; §9
and OQ-7).

## 4. Pre-STORY LOCK protocol and the STORY LOCK transaction (AR-2, AR-1)

**Before STORY LOCK (AR-2).** `create_v3_season` opens, in its command transaction (A1 §6 activates
it here): the season row, `season_tracks(IDEA)` (A1 0030), the `season_budget_mutex` row, the
`SEASON_SETUP` account — **base cap 0**, shutdown reserve 0, all seven category rows with
`allocated = 0` (`lock_categories` requires the full set, `S/budget/ledger.py:212-213`) — and the
creator ownership link: `link_season_creator(tx, season, principal)` (`S/review/scope.py:38-63`)
writes the `season_owners` row (source `CREATOR_AT_CREATION`) in the same transaction, so a V3
season never exists unowned and the §5/§6 authorization rules have a row to bind to (N2-9).
Effective cap 0 means **no paid setup work before approval** (AC-13): every admission refuses at the
child check. `approve_setup_budget` (§5, §7) is the only path to a non-zero effective cap. Account
factories: `open_setup_account` / `open_season_account` follow the idempotent
`open_episode_account` pattern (`S/budget/service.py:220-262`, ON CONFLICT DO NOTHING + re-open
comparison against the expected cap/categories). Pre-LOCK setup
mutations take **mutex → setup account**; admission checks the approved setup budget (child) and
the step caps (§3.3) — no parent exists yet, and none is needed: the mutex makes the LOCK attach
race-free.

**STORY LOCK takes the same mutex.** The LOCK decision transaction (A1 §5) runs its steps 1–8 and
the handler callback (`create_v3_episodes_in(tx, decision_context, count)`, §7) joins it. Budget
attach, inside the same transaction after the A1 sequence (idempotency → `season_tracks` → seasons
→ episode/track inserts), in §6-#7 order:

1. `lock_budget_hierarchy`: mutex FOR UPDATE → lock the `SEASON_SETUP` account (the only existing
   budget row) — serialised against every setup mutation (AR-2's race test, §10).
2. Read the setup ledger: `committed_setup = reserved + accrued + settled` (worst-case exposure,
   open holds included).
3. Create the `SEASON` account: base cap = `count × per_episode_base_cap` (the approved per-episode
   base, US$10 by default — master §12.3), counters **= the setup counters** (the attach), category
   rows at 0.
4. Set the setup account's `parent_account_id` (set-once, §2.1) — "attach the existing setup
   exposure".
5. Create the V3 `EPISODE` accounts (episode id order): base cap US$10 (`CostPolicy`,
   `S/contracts/season.py:99-129`), parent set at creation, categories per policy.
6. Create the production `budget_steps` rows: `step_05..step_09`, each with
   `cap = per-episode step default × count` (CostPolicy defaults; OQ-2), plus the
   `episode_production` envelope with `cap = count × per_episode_base_cap` (the plan guard),
   validating `Σ(step_05..step_09 caps) ≤ episode_production cap` (§2.2); the setup-step rows
   already exist from `approve_setup_budget`.
7. **Validate against the SEASON base cap:** `committed_setup ≤ count × per_episode_base_cap`;
   refuse (rolling the whole decision back) otherwise, naming both numbers — OQ-1.
8. **Validate the count against the binding (N2-10):** `count` must equal the episode count in the
   approved activation binding (recomputed from the binding inputs behind `binding_sha256`); a
   mismatch refuses and rolls the whole decision back — the operator approved a specific count.

**AR-1: setup consumes the envelope, never adds to it.** The SEASON base cap is
`episode count × the approved per-episode base cap`, full stop (AR-1 replacement wording). Setup
spend lives inside it because the setup counters *are* the initial SEASON counters (step 3) and
every later setup delta mirrors up like any child. Any increase is a separately recorded `SEASON`
amendment (§5).

**The arithmetic of A-T9.** 10 episodes, US$10 base, US$30 approved setup, all in micro-USD ×10⁶:
SEASON base cap = 10 × 10_000_000 = **100_000_000 (US$100)**. At LOCK: season committed =
30_000_000 (setup) + 0 (episodes) = 30_000_000 ≤ 100_000_000 ✓ — the lock validates. Capacity left
for episode production = 100_000_000 − 30_000_000 = **70_000_000**, so average episode spend must
stay ≤ 7_000_000 (master §12.3's averaging rule; the forecast shows it before CAST LOCK, §6). Each
episode account still caps at 10_000_000 individually — the aggregate admission (§3.3 step 4) is
what refuses the 8th episode's full-cap reservation once 7 episodes consumed ~9_900_000 together.
Setup never touches the episode accounts: setup reservations/receipts resolve to the setup account
only (§3.1), and setup→episode attribution is `cost_allocations` rows without counter moves (§6).

**After attachment**, every mutation takes mutex → `SEASON` → child (§3.2). A missing parent after
attachment is an error (`§3.2`). Extensions and episode-count changes are `SEASON` amendments (§5).

## 5. Cap amendments (AC-11)

One command path, two faces:

| Command | Actor | Effect |
|---|---|---|
| `approve_setup_budget(season, amount_micro_usd, category_deltas, step_caps, reason, idempotency_key)` | Operator (human session) | An amendment on the `SEASON_SETUP` account from `old_effective = 0` (base 0) to the approved amount; writes the initial `budget_steps` caps (`step_01..step_04`, `step_10`, `launch` — default proposal US$30, `Settings`-supplied; OQ-3) |
| `amend_account_cap(account, expected_old_effective, expected_revision, new_effective, category_deltas, step_deltas?, reason, idempotency_key)` | Operator (human session) | Any later effective-cap change on a V3 account, including `SEASON` (episode-count changes, extensions) |

**Authorisation:** human session + CSRF on the unsafe route (`S/review/api.py:201` refuses
non-human principals) **plus account-scope authorization** (N2-9): the command resolves
account → season and requires `require_season_access(tx, principal, season_id)`
(`S/review/scope.py:79-84`) — a live session matching `actor_owner_id` proves authentication, the
`season_owners` row proves the actor owns *this* season; a foreign scope is `NotFound`, so
workflow, revision and financial detail are never leaked to it. The SQL backstop binds the same
rule: `md_cap_amendment_requires_human_session` (§2.3 guard 1) verifies the actor's `season_owners`
row for the account's season, so even a fabricated amendment from an authenticated owner of a
different season cannot commit.
**Idempotency:** `IdempotencyService.execute` with A1's §5 preflight seam;
`account_cap_amendments.idempotency_key` is UNIQUE; a replay returns the stored response
(`replayed=true`, no new row); the same key with different command parameters raises
`IdempotencyConflict` (A-T2 pattern; §10 tests both).
**Serialisation with admission:** the command takes, in §6 order — idempotency row (#1) → the
RETRY_WAIT job rows it will wake (#5, below) → `lock_budget_hierarchy` (#7: mutex → SEASON for
child amendments; a **SEASON amendment returns no parent from the helper and locks the SEASON row
itself as its account** — N2R2-1) → account → `budget_steps` → categories — then calls
`md_apply_cap_amendment` (§2.3) inside the same transaction — which re-runs the verified
mutex/attachment protocol in SQL (N2R2-1) — so an amendment and an admission are totally ordered
on the same chain; a stale `expected_old_effective` / `account_revision` raises `StaleRevision`
explicitly (surfaced from the function's under-lock prior-tip validation, §2.3/N2R2-2 — the §2.3
UNIQUE constraints already make a fork impossible; N2-4).

**Ancestor-limit and floor validation (in the same transaction, under those locks; every rule is
re-checked by the §2.3 SQL constraint trigger — the backstop is not Python-only, N2-4):**
- raising a child (`EPISODE`/`SEASON_SETUP`) **never raises `SEASON`**: validate
  `new_effective_child ≤ md_effective_cap(season) − (season.committed − child.committed)` — the
  raised child must still fit the season envelope around its siblings' commitments; a `SEASON`
  raise needs its own amendment row (which is what an episode-count change or extension writes,
  with empty `category_deltas`, §2.3);
- lowering: `new_effective ≥ committed` (never below existing exposure);
- for spending accounts `Σ category_deltas = new − old` and the resulting allocations sum to
  `new_effective` (§2.3 re-checks the final state); `step_deltas` may only move caps of steps owned
  by that account, and for the setup account `Σ step caps ≤ new_effective` after the change;
  production step raises additionally respect `Σ(step_05..step_09 caps) ≤ episode_production cap`
  (§2.2). The Python checks compute the **completed amendment state**, and §2.3's deferred guard
  re-proves them at commit — no row-time aggregate bound exists anywhere (N2R3-3).

**Responses (exact, N2-10):** `approve_setup_budget` and `amend_account_cap` return
`{amendment_id, account_id, old_effective_micro_usd, new_effective_micro_usd, account_revision,
woken_jobs, replayed}` — nothing else; a refusal writes nothing.

**Durable wakeup (A0's columns):** in the same transaction, `UPDATE jobs SET run_after = now()
WHERE status='RETRY_WAIT' AND defer_reason='BUDGET' AND season_id = <the season>` (episode
amendment: `... AND episode_id = <the episode>`). The jobs retry time is `run_after`
(`M/0001…sql:86`); `defer_reason` is A0's 0027 column; A-T9 asserts the wakeup. The target job rows
are locked **before** the budget chain (#5 before #7) and re-checked in the UPDATE — no competing
transaction takes job→budget locks today (recorded in §8; A3 must keep it that way).
`approve_setup_budget` runs the same wakeup (OQ-5).

**Direct mutation refused:** `cap_micro_usd` immutable (`M/0003…sql:33-34`); amendment rows
append-only, human-session- and season-owner-guarded, V3-only, xact-stamped, consistency-guarded,
lineage-unique, and writable **only through `md_apply_cap_amendment`** (the function-only INSERT
boundary with equivalent serialization for every writer, §2.3/N2R2-3) — A-T9 asserts all of these
plus the committed-vs-effective-cap trigger on the counters, and
§10 adds rollback/replay (N2-15).

## 6. Forecasts and the Costs data API (spec §5.5, §5.6; AC-13, AC-14)

**Forecasts.** `season_forecast(tx, season_id)`, a read helper used at two checkpoints — the
CAST_LOCK gate conditions (A1's `conditions(tx, …)` seam) and V3 render-lane admission (first
render dispatch per season; a blocker, not a money refusal). `committed` and the expected
remainder are **non-overlapping by construction** (N2-12/N2R2-9): every episode's actual holds
and spend sit inside `committed`, so an episode contributes only an expected *residual* — never a
full estimate stacked on money already committed:

```
committed  = SEASON account counters (mirrored: setup + episodes, attribution excluded)
unfinished = episode_tracks with production_state IN
             ('PLANNED','DIRECTED','RENDERING','EDITING','DRAFTING','AWAITING_REVIEW')
             — every state of SPEC-v3 §2.2's episode chain except the terminal 'APPROVED';
             membership is by enum value, never by observing spend (N2R2-9)
begun      = unfinished episodes with committed_e > 0
observed   = Σ committed_e over begun ÷ |begun|   (0 if none)
plan       = per-episode plan estimate; source and version pinned (below)
per_ep     = max(observed, plan)
forecast   = committed + Σ_{e ∈ unfinished} (per_ep if committed_e = 0
                                            else max(0, per_ep − committed_e))
capacity   = md_effective_cap(season) − committed
```

(`committed_e` is episode *e*'s own account counters.) A full estimate is added **only when an
episode's own commitment is zero**; every episode with any commitment contributes only its
residual — PLANNED/DIRECTED included, since directing is episode-attributable spend under master
§12.3 and a DIRECTED episode's spend is already in `committed` (N2R2-9): a DIRECTED episode with
US$2 committed and a US$10 estimate forecasts 2M + (10M − 2M) = **10M**, never the 12M a full
estimate on top of committed spend would produce. **Plan-estimate source/version (N2-12):** until phase B records
per-episode estimates, `plan` is the per-episode base cap bound in the STORY LOCK activation
binding — `plan_source='lock_base_cap'`, `plan_binding_sha256=<the activation's hash>` in the
response, so the number is reproducible; if phase B later adds a per-episode estimate, its source
and revision travel in the same fields. **Pre-LOCK availability (N2-12):** the Costs route exists
from season creation, but the `SEASON` account does not — before LOCK the forecast section reports
the setup-only view: `phase='pre_lock'`, `committed` = setup counters, `remaining = 0`,
`forecast = committed`, `capacity = md_effective_cap(setup) − committed`. (The CAST_LOCK and
render checkpoints are post-LOCK by definition.) **Revalidation (N2-12):** the forecast is
evaluated live at every CAST_LOCK activation-condition evaluation and every render-lane admission
dispatch — never cached — so any budget or scope change (amendment, episode-count change) is
re-checked at the next checkpoint.

`forecast > md_effective_cap(season)` is a **gate condition** (blocker) with a "raise the cap or
cut scope" action — the CAST_LOCK gate refuses to open (A1's activation conditions), and render
admission surfaces it as `WAITING_BUDGET` deferral on the dispatching job. Because setup consumes
the envelope (AR-1), `capacity` already nets the setup commitment out of episode capacity — no
second subtraction anywhere (`setup_committed` is shown separately for the UI).

**Costs data API.** One V3 read route, `GET /v3/seasons/{season_id}/costs`
(`S/budget/api.py` gains a sibling router). **Access before detail, in that order
(N2-9/N2R2-7/N2R3-5):** the route resolves the season; **non-human service principals are
mapped to `NotFound` explicitly, first** — before the ownership helper and before any financial
read — because `require_season_access` (`S/review/scope.py:79-84`) bottoms out in
`owner_id_in_tx` (`S/core/auth.py:174`), whose human-principal check raises `Unauthorized` for
service credentials; the V3 Costs contract promises `NotFound`, and the explicit mapping makes
the promised response the real one (N2R3-5). Human principals then require
`require_season_access` — a foreign scope is `NotFound` and never learns the workflow version —
and only then `require_workflow(expected='v3')` (an authorized principal on a V1 season sees
`WORKFLOW_MISMATCH`). The V1 route `GET /episodes/{id}/costs` (`S/budget/api.py:21`), which
today accepts a principal and discards it (`:24`) while its reader resolves EPISODE accounts
without workflow filtering, gains exactly one V3-only check: for a **V3 episode id** it resolves
the episode's season and applies the same two-step rule — service credentials map to `NotFound`,
an owner of another season gets `NotFound` — **before any financial read**; V1 episode ids keep
today's authentication behaviour unchanged (N2R2-7/N2R3-5). §10 tests both endpoints with
another season's owner and with service credentials, asserting the exact response (404
`NOT_FOUND`, never 401). Response `SeasonCostsV3` (generated contracts, §2.4),
one REPEATABLE READ READ ONLY transaction (`S/budget/reports.py:3-5` pattern). Separate
quantities, each its exact ledger query — unknowns stay unknown, never COALESCEd to zero (N2-13):

| Quantity | Query |
|---|---|
| **cash** (settled) | `SELECT COALESCE(SUM(settled_micro_usd),0)::bigint FROM budget_accounts WHERE season_id=%s AND scope_kind IN ('SEASON_SETUP','EPISODE')` — Σ settled over the season's cash accounts (the setup account before and after LOCK, episode accounts post-LOCK; the aggregate `SEASON` row is excluded by kind). Per-account rows returned alongside |
| **accrued/unsettled** | same shape on `accrued_micro_usd` — this is also where **expired exposure lands**: expiry moves reserved→accrued (`S/budget/ledger.py:388-396`), so expired holds are shown in their actual ledger bucket (N2-13) |
| **reserved exposure** | open holds only: same shape on `reserved_outstanding_micro_usd`. Expired holds are *not* here — see accrued above — and the unresolved-exposure listing (the `S/budget/reports.py:81-86` pattern) names every EXPIRED-without-settlement hold explicitly, so no exposure is hidden by the bucket move (N2-13) |
| **attribution** (never cash, never cap consumption) | `SELECT target_account_id, COALESCE(SUM(amount_micro_usd),0) FROM cost_allocations a JOIN budget_accounts t ON t.id=a.target_account_id WHERE t.season_id=%s GROUP BY 1` — display only: V3 allocations move no counters (below) |
| **setup counted once** | setup charges exist once on the setup account; the attribution panel references them (`source_account_id`); no panel sums allocation shares into cash — the setup account's own counters are the single count |
| **step panel** | `SELECT step_key, cap_micro_usd, reserved_outstanding_micro_usd, accrued_micro_usd, settled_micro_usd FROM budget_steps WHERE season_id=%s` — production steps report their real identities (steps 5–9), the envelope row reports the aggregate (§2.2) |
| **provider attribution** | `charges.step_key` + `charges.provider` (`M/0003…sql:105`), grouped — computed over each reservation's **current** final rows, respecting accrual-to-settlement replacement (`apply_receipt` replaces finals rather than accumulating, `S/budget/ledger.py:331-349`, `:316-330`), so an accrual later settled is never double-counted (N2-13) |
| **subscription allocation** | a separate field with its basis stated honestly (N2-13): A0's `llm.subscription` rows carry no money (`phase-A0-spec.md` §5.5 item 5: no `UsageReceipt`, no charge) and no ledger source prices the subscription fee — the field reports `subscription_allocation=null, basis='unavailable'` (plus the subscription invocation count) unless/until A0 or `Settings` defines an allocation basis |
| **LLM estimates** | `SELECT COUNT(*) FILTER (WHERE cost_estimate_microusd IS NOT NULL), SUM(cost_estimate_microusd), COUNT(*) FILTER (WHERE cost_estimate_microusd IS NULL) FROM llm_invocations WHERE season_id=%s` — separate `estimated_count` / `estimated_micro_usd` / `unknown_estimate_count`; no COALESCE, so unavailable estimates stay visible as unknowns, never zero (N2-13). `llm.subscription` is unmetered, so it appears **only** here and in the subscription panel |
| **quota** | latest `quota_observations` per invocation (A0 0027); invocations without one are counted in `quota_unknown_count` — quota uncertainty preserved, not zero-filled (N2-13) |
| **overrun / blocked** | `overrun_micro_usd`, `paid_dispatch_blocked` per account + season (§3.3) |
| **forecast** | the §6 helper output + inputs (incl. `plan_source`, `plan_binding_sha256`, `phase`) |

**V3 attribution writes no counters.** `allocate_research_cost` (`S/budget/service.py:1276-1370`)
keeps its V1 body; the V3 variant (`attribute_setup_cost`) inserts `cost_allocations` rows (source
= setup account) **without** `ledger.move` and without `_check_research_share` refusals (AC-14:
allocations are not episode-cap consumption), under mutex → setup → target accounts in id order;
exactly-once per (source charge, target) is the existing UNIQUE (`M/0003…sql:140`). Receipts stay
exactly-once per canonical receipt via the existing dedupe keys (`(provider, provider_receipt_id)`
and `receipt_id`, `M/0003…sql:123-124`; `_replay`, `S/budget/service.py:1082-1116`), and operations
with several receipts (GPU accrual → settlement → late adjustment) post each once because
`apply_receipt` replaces rather than accumulates finals (`S/budget/ledger.py:331-349`, `:316-330`)
— A-T11 exercises exactly that chain.

## 7. The command table (A2 rows; A1 §6 columns)

| Command | Actor | Scope / revision owner | Prerequisites (hash-bound where applicable) | Writes | Events (exact) | Replay identity | Activation |
|---|---|---|---|---|---|---|---|
| `create_v3_season(intake_ref)` | Operator (human session) | season / — | A1 §6 (intake ref, owner scope) | seasons(v3, PROPOSED) + `season_tracks(IDEA)` + `season_budget_mutex` + `SEASON_SETUP` account (base 0, categories 0) + `season_owners` creator link (`link_season_creator`, §4; N2-9) | **exactly one `season.created` with payload `{season_id, workflow_version}` on first success, none on replay** (defined here — A1 §6 ships the command only as a `NOT_AVAILABLE` stub with no event set; N2R2-8); A2 adds no budget event (the cap-0 setup account is not evented) | idempotency key | **A2** (AR-6) |
| `approve_setup_budget(season, amount, category_deltas, step_caps, reason)` | Operator (human session + CSRF + season access) | setup account / expected `old_effective = 0` + `account_revision` | season is v3; no prior setup approval (`old_effective` 0); amount within the Settings bound | `account_cap_amendments` row (0 → amount); `budget_steps` initial caps; BUDGET-job wakeup | exactly one `budget.cap_amended` (payload below) | idempotency key | **A2** |
| `create_v3_episodes_in(tx, decision_context, count)` — internal helper, never a command | System (STORY LOCK handler); exposed to test handlers in phase A | season / `season_tracks.revision` | STORY LOCK APPROVE decision (A1 §5 transaction); §4 validations pass, incl. `count` = the approved binding's episode count (§4 step 8, N2-10) | episodes (legacy PLANNED) + `episode_tracks` + `SEASON` account + parent attach + `EPISODE` accounts + `step_05..step_09` + `episode_production` envelope rows | none of its own — its effects ride the LOCK decision's events (A1 §5's `approval.recorded` + handler events) | inherits the decision's idempotency key and transaction (below) | **A2** (AR-6) |
| `amend_account_cap(account, expected_old_effective, expected_revision, new_effective, category_deltas, step_deltas?, reason)` | Operator (human session + CSRF + season access) | account / `account_revision` + `old_effective` | §5 validations (ancestor limits, deltas sum, V3-only) — all re-checked in SQL (§2.3) | `account_cap_amendments` row; `budget_steps` caps; BUDGET-job wakeup | exactly one `budget.cap_amended` (payload below) | idempotency key | **A2** |
| STORY LOCK budget step (the §4 attach) | System, inside the LOCK decision | season / decision revision + binding hash | §4 steps 1–8 | as §4 | none beyond the decision's (as above) | the decision's idempotency key | **A2** |

**Only external human commands enter `IdempotencyService.execute`** (N2-10): `create_v3_season`,
`approve_setup_budget` and `amend_account_cap` — the service owns their transaction, with the §5
preflight; a refusal writes **nothing** (A-T2 pattern). The internal LOCK helpers —
`create_v3_episodes_in(tx, decision_context, count)` and the §4 budget attach — run **inside the
caller-owned decision transaction** and inherit its replay identity (the decision's idempotency
key, A1 §5 steps 1/8): they never open their own transaction, never enter `execute`, and so can
never nest a transaction waiting on its caller. The `budget.cap_amended` payload schema:
`{account_id, scope_kind, season_id, old_effective_micro_usd, new_effective_micro_usd, reason,
actor_owner_id, revision}`. The `create_v3_season` response is defined here with its event set
(N2R2-8): `{season_id, replayed}` — nothing else — with the single `season.created
{season_id, workflow_version}` event above emitted on first success only. Mismatched replay
(same key, different parameters) raises
`IdempotencyConflict` for every command above; matching replay returns the stored response with
`replayed=true` and writes nothing (§10).

## 8. Lock audit (spec §6 #7; AC-8, AC-12)

The §6 table (A1 §9) row 7 in full: `season_budget_mutex → SEASON → child accounts (id order) →
budget_steps → categories → reservations → charges/receipts`, the audit including provider-operation
advisory locks and caller-owned billing transactions — **complete outer transactions, not just the
shared helpers' interiors** (N2-5; N2R2-4). v1.3 states the order as an **enforceable table**
(N2R2-4's "one ordered sequence", made concrete): §8.1 defines the global order; §8.2 binds every
A2-touched transaction to it and lists its writes.

### 8.1 The global lock order (normative)

Every transaction that takes any lock named here — a 451xxx advisory, a `season_budget_mutex`, or
any #7 budget row lock — acquires its locks as a **subsequence of this order**: it may skip every
family it does not need, but the relative order of the locks it does take must match the table.
Advisory families are taken in **ascending tag order (451045 → 451051)**, each family's keys as
one **sorted block** acquired at the outermost transaction boundary, before every stage-2/3/4
lock.

| Stage | Lock family | Order within the family | Sites |
|---|---|---|---|
| 1a | billing-query advisory — `pg_advisory_xact_lock(hashtextextended(key, 451045))` | one key: `query_id` | `S/budget/billing.py:256` |
| 1b | billing-bucket advisory (…, **451046**) | **all** of the transaction's buckets, `bucket_identity_sha256` ascending | `S/budget/billing.py:297` |
| 1c | reconciliation advisory (…, **451047**) | all of the transaction's allocation keys, ascending | `S/budget/service.py:611` |
| 1d | verification-finalization advisory (…, **451048**) | one key | `S/budget/service.py:729` |
| 1e | billing-recovery advisory (…, **451049**) | one key | `S/budget/service.py:761` |
| 1f | invoice-period advisory (…, **451050**) | keys `{provider_account_ref}:{pod_id}`, ascending | `S/budget/billing.py:496` |
| 1g | podless-create advisory (…, **451051**) | one key: `lease_id` | `S/budget/billing.py:828` |
| 2 | evidence/provider/lease **row** locks — `runpod_billing_queries` → `runpod_billing_buckets` → `pod_leases` → `provider_operations` | rows in identity order within each table; tables in the listed order | `S/budget/billing.py:260`/`:301`/`:830`; `S/core/provider_ops.py:91-95` |
| 3 | **every** required `season_budget_mutex` | all of the transaction's seasons, `season_id` ascending — before any account lock of any of those seasons | 0033 (§2.2) |
| 4 | per season, in `season_id` order, the #7 chain: `SEASON` account → child accounts → `budget_steps` → categories → reservations; charge/receipt inserts last | children by `id`, steps by `step_key`, categories by category, reservations by `id` | §3.2; A1 §9 |

**Why this eliminates the `#6 → #7 → #6` cycle (N2R2-4, made concrete).** The two live cycles:
ingestion reached `:297` again *below* budget locks (bucket advisory → reconcile's advisory +
budget chain → next bucket advisory), and invoice verification acquired its season mutexes only
inside the per-bucket ingestion its `:666` loop triggers at `:753` — so an invoice transaction
could hold a season mutex and request its next bucket while an ingester held that bucket and
waited for the mutex. Under §8.1 this is impossible **by construction**: the outermost
transaction plans **every stage-1 advisory it will ever need** — ingestion: its query key, every
bucket key, every allocation's reconciliation key; verification: its invoice-period key, every
synthetic query, every bucket the period may verify, its finalization key; expiry: none — and
takes them as sorted blocks in ascending tag order **before the first stage-2/3/4 lock**. No
transaction ever requests a stage-1 lock while holding a stage-3/4 lock; all of a transaction's
bucket keys are held before any of them is used; cross-season transactions hold **all** their
mutexes (stage 3) before any account lock (stage 4). The wait-for graph is acyclic because every
edge follows one total order. Inner helpers — the `:666` loop's ingestion calls, a
reconciliation composed after other budget work, the ingest core inside verification — **reuse
the outer plan** and acquire nothing new.

**The provider-operation family sits outside the seven.** Tag-0 advisories
`pg_advisory_xact_lock(hashtextextended('md-job:{job_id}', 0))` then
`hashtextextended('md-reservation:{reservation_id}', 0)`
(`S/core/provider_ops.py:121`/`:124`, job before reservation, always in this order) are taken by
`begin` after a reservation **FOR SHARE** read-guard (`:179-181`) and before the
`provider_operations` insert. No transaction takes both a tag-0 and a 451xxx advisory; `begin`
takes no counter lock and no other #7 lock beyond the read-guard; and the read-guard's only
counterpart (`release`, taking the same row FOR UPDATE inside its own stage-4 chain) can never
hold-and-wait against `begin` in both directions — the family is unconstrained by the stages and
cannot join a #6↔#7 cycle (A1 §9 audited; A2 changes nothing there).

### 8.2 Transaction audit (locks in order → writes)

| Transaction | Locks in order (per §8.1) | Writes | Verdict |
|---|---|---|---|
| `reserve` (V3) | policy checks (no locks) → tx: stage 3 → stage 4 (SEASON → child → step row → categories) → replay read → all admission checks → atomic tail (§3.3) | `reservations` insert; step/category/account counters (mirrors incl. envelope + parent); spill: `budget_transfers` + category allocations; cleanup: `cost_overruns` rows, `overrun_micro_usd`, blocked flags | conforms (§3.3; N2-14) |
| `release` (`S/budget/service.py:484-543`) | stage 3 → stage 4: SEASON → child (`:500`) → categories (`:501`) → reservation (`:502`) — today's order preserved, hierarchy prepended | reservation state; counters | conforms |
| `expire_stale` (`S/budget/service.py:544-576`) | **today: per distinct account in `account_id` order (`:556`): hierarchy (mutex → SEASON, added by A2) → child (`:562`) → categories (`:563`) → reservations (`:566`) — a second season's mutex lands after the first season's account locks (N2R2-4).** Fix: stage 3 — every required mutex, `season_id` order — then per account in id order, stage 4: SEASON → child → categories → reservations | reservation `reserved → accrued`; counters | **fixed** — multi-season-expiry race §10 |
| `record_usage_in_transaction` (`S/budget/service.py:864-880`) | stage 3 → stage 4: SEASON → child (`:872`) → categories (`:873`) → linked reservation (`_linked_reservation`, `:1068-1080`) | `charges` insert; counters | conforms |
| `_record_gpu_interval` (`S/budget/service.py:882-956`) | stage 3 → stage 4: SEASON → child (`:912`) → categories (`:913`) → lease read → overlap check; the pod EXCLUDE gist 40P01 mapping (`:997-1006`) unchanged | `charges` + interval inserts; counters | conforms |
| `settle_billed_lease` (`S/budget/billing.py:1268-1383`) | **today: child account (`:1296`) → reservation (`:1297`) → `record_usage_in_transaction` (`:1367`) — child-before-parent, the inversion the spec names.** Fix: stage 3 → stage 4 hierarchy before `:1296`; the rest unchanged | settlement `charges` insert; counters | **fixed** — competing test §10 |
| billing ingestion — the janitor's per-pod call (`S/rendering/janitor.py:1047` → `ingest`, `S/budget/billing.py:207-241`: **one self-contained transaction per pod**; the sweep holds no lock across pods) | **today: 451045 (`:256`) → query row (`:260`) → per bucket: 451046 (`:297`) → bucket row (`:301`) → per allocation `reconcile_provider_allocation_in_transaction` (451047 + budget chain, `billing.py:370-373`) → **next** 451046 — the `#6 → #7 → #6` cycle (N2-5/N2R2-4).** Fix: stage 1 in tag order — 451045, then **every** bucket's 451046 (`bucket_identity_sha256` sorted), then **every** allocation's 451047 — then stage 2 (query + bucket rows), then stages 3–4 per season; the bucket loop reuses the plan, no reacquisition | `runpod_billing_queries` / `_query_skipped_buckets` / `_billing_buckets` / `_billing_allocations` inserts; `charges` + counters via reconcile | **fixed** — competing-ingestion + invoice-vs-ingestion tests §10 |
| `verify_invoice_period` (`S/budget/billing.py:448-693`) | **today: 451050 (`:496`) → evidence reads → MATCHED loop (`:666`) → `_verify_bucket_revision_in_transaction` → inner `_ingest_in_transaction` (`:753`) per bucket, each taking a fresh 451045/451046 and the budget chain below held evidence state — the outer `#6 → #7 → #6` (N2R2-4).** Fix: plan up front, stage 1 in tag order — 451045 (every synthetic query), 451046 (every bucket the period may verify), 451048 (finalization), 451050 (the period) — then stage 2 (evidence + bucket rows), then stages 3–4; the `:666` loop and its `:753` calls reuse the plan and take no new lock | `runpod_billing_period_evidence` insert; verified bucket revisions + `runpod_billing_invoice_verifications` inserts; `charges` + counters (finalization / inner ingest) | **fixed** — invoice-vs-ingestion race §10 |
| `resolve_podless_create` (`S/budget/billing.py:785-912`) | stage 1g (451051, `:828`) → stage 2 (`pod_leases` row, `:830`) → stages 3–4 via `record_usage_in_transaction` (`:911`) — one advisory, then the chain, no reacquisition | resolution insert; lease window update; `billing.podless_create_resolved` event; BILLED-0 `charges` insert; counters | audited — conforms |
| `resolve_billing_recovery` (`S/budget/service.py:747-831`) | stage 1e (451049, `:761`, before budget) → stages 3–4: hierarchy → child (`:811`) → categories (`:812`) → charge (`:817`) → resolution insert (`:820`) | recovery `charges` insert; resolution insert; counters | **fixed** (hierarchy prepended before `:811`) |
| `reconcile_provider_allocation_in_transaction` (`S/budget/service.py:589-…`) | stage 1c (451047, `:611`) → stage 2 (posting row FOR UPDATE, `:615`) → stages 3–4: hierarchy → child (`:654`) → categories (`:655`) → `_lease_window_reservation` FOR UPDATE (`:1040-1065`) → charge. The per-call advisory is correct for a standalone call; a caller-owned transaction that will reconcile **after** budget work carries this advisory in its outer stage-1 plan — reconciliation never takes a new #6 lock below a held #7 lock (N2R2-4/§8.1) | `charges` insert; counters | **fixed** (hierarchy before `:654`; advisory planned at the outermost transaction when composed) |
| `record_provider_invoice_verification_in_transaction` (`S/budget/service.py:718-745`) | stage 1d (451048, `:729`) → finalization row (`:732`) — no account locks (evidence only) | finalization row | audited — no budget locks, no inversion possible |
| `transfer` (`S/budget/service.py:1228-1272`) | stage 3 → stage 4: SEASON → child (`:1246`) → categories (`:1247`) | `budget_transfers` insert (atomic tail, `S/budget/ledger.py:417-421`); category allocations; counters | conforms |
| `attribute_setup_cost` (V3, §6) | stage 3 → stage 4: SEASON → source (setup) → target accounts in id order | `cost_allocations` rows only — no counter moves | conforms |
| `approve_setup_budget` / `amend_account_cap` (§5) | idempotency row (#1) → RETRY_WAIT job rows FOR UPDATE (#5) → stage 3 → stage 4: SEASON (child amendments) → account → amendment tip → steps → categories (baseline captured here, N2R3-1) → amendment insert + revision advance → step/category deltas → job UPDATE | `account_cap_amendments` row (incl. `category_baseline`); `budget_accounts.amendment_revision`; `budget_steps` caps; category allocations; `jobs.run_after` | conforms (#5 before #7; no existing path takes job→budget — A3 must preserve this; recorded as A2's only new order, with the §10 race test) |
| STORY LOCK decision + attach (§4) | A1 §5 order (1 → 2 → 4 → episode/track inserts → 3) then stage 3 (mutex) → stage 4: setup lock → SEASON create → parent set → episode accounts → steps | `SEASON` account; `parent_account_id` attach; `EPISODE` accounts; `budget_steps` rows | conforms (inserts of not-yet-existing rows serialise under the mutex + unique indexes, per A1 §9's justification) |
| `create_v3_season` | idempotency (#1) → A1's creation order (incl. `season_owners` creator link) → mutex row + setup account inserts | seasons + `season_tracks(IDEA)` + `season_budget_mutex` + `SEASON_SETUP` (base 0, categories 0) + `season_owners` | conforms |
| provider-op `begin` (`S/core/provider_ops.py:144-273`) | reservation FOR SHARE read-guard (`:179-181`) → tag-0 `md-job` advisory (`:121`) → tag-0 `md-reservation` advisory (`:124`) → `provider_operations` insert | `provider_operations` row + its event | audited — outside the seven families (§8.1); no counter lock, no cycle |
| V1 paths | helper is a no-op (no mutex row, `workflow_version='v1'`): lock sequences byte-identical to today; the stage-1 planning of ingestion/verification/expiry acquires nothing for a V1-only batch (V1 seasons have no mutex rows; single-bucket single-season behaviour unchanged) | unchanged | untouched |

**Cross-season ordering (N2-5)** is stage 3: a transaction needing the budget chains of more than
one season (an ingestion batch whose buckets map to episodes of several seasons; a multi-bucket
invoice verification; a multi-season expiry batch) takes **all** required mutexes in `season_id`
order before any account lock of any of those seasons, then proceeds per season down stage 4.
Combined with the stage-1 sorted blocks, every lock sequence is a subsequence of one total order —
deterministic and cycle-free across ingesters, invoice verifiers and expiry. The lease claim's
two-transaction pattern (`S/rendering/leases.py:702-716`: reserve tx, then lease-insert tx) stays;
each transaction holds one lock class plus the already-held scope track lock (A1 §8/§9).
Worker-completion job-before-track order remains A3's row (A1 §9 item 1); A2 adds no such
transaction.

## 9. V1 unchanged

Every V1 path A2 touches, and why its behaviour and tests stay identical:

- **Scope lookup:** `reserve`'s EPISODE/SEASON_RESEARCH branches keep today's semantics and order
  (`S/budget/service.py:372-375`); the contract enum admits nothing else for V1 callers, so the new
  branches are unreachable for V1. The research fallback survives *as the V1 branch*, not as an
  else.
- **Locks:** `lock_budget_hierarchy` returns before any lock for V1 rows; every existing lock
  sequence (`:376-377`, `:500-502`, `:562-566`, `:872-873`, `:912-913`, `:1246-1247`,
  `S/budget/billing.py:1296-1297`) keeps its order and row set.
- **Admission checks:** unit-price, queue, category, spill, recovery-headroom and shutdown-floor
  rules run unchanged (`S/budget/policy.py`; `S/budget/service.py:404-444`); the child-cap check
  compares against `effective_cap`, which equals `cap_micro_usd` without amendments — and V1
  accounts can never have them (§2.3 guard 2). The N2-14 compute-then-apply split changes no V1
  outcome: the feasibility arithmetic is `spill_from_recovery`'s own, and the transfer row is
  written in the same transaction it always was — refusals never durably wrote anything (rollback),
  admissions write the identical rows. V1 cleanup still must fit the cap (`:335-341`);
  only V3 cleanup admits past it (§3.3, OQ-7).
- **SQL:** the 0003:27-28 CHECK becomes the 0032 trigger with the identical predicate (0034's
  amendment-aware term is a no-op without amendment rows); the 0003:13
  cap bound keeps `≤ 10_000_000` verbatim for V1 kinds; scope-kind, episode-binding, queue and
  category CHECKs are extended additively. `md_reservation_step_rules` requires `step_key IS NULL`
  on V1 reservations — today's rows are all NULL (the column is new).
- **Ledger:** `Ledger.move/apply_receipt/expire/release/check_overrun/flush`
  (`S/budget/ledger.py:266-535`) gain step/parent mirroring that activates only for V3 accounts;
  V1 counter semantics, revision guards and error types are untouched.
- **Research allocation:** `allocate_research_cost` (`S/budget/service.py:1276-1401`) keeps its body
  and `_check_research_share` refusals for V1; the no-counter V3 variant is a separate method.
- **Settlement/recovery:** `settle_billed_lease`, `resolve_billing_recovery`,
  `reconcile_provider_allocation`, the billing ingestion core, `verify_invoice_period` and
  `resolve_podless_create` gain the no-op-for-V1 hierarchy call (and, for ingestion, invoice
  verification and multi-season expiry, the outermost-transaction lock plan of §8/N2R2-4 — lock
  order only, no observable change for a single-bucket/single-season V1 batch; the season-mutex
  pre-acquisition acquires nothing for V1 seasons, which have no mutex rows); postings, evidence
  and idempotency unchanged.
- **API and readers:** `GET /episodes/{id}/costs` (`S/budget/api.py:21`) changes only for **V3**
  episode ids — the N2R2-7 access check (a foreign scope is `NotFound` before any financial
  read); V1 episode ids keep today's request/response byte-identical, the check firing only
  where `workflow_version='v3'`;
  `S/budget/reports.py` keeps its response semantics — its account reads (`:52`, `:62`) gain the
  effective-cap alias (§2.3 inventory) without changing any returned V1 field (no amendments ⇒
  same number). `S/analytics/cost.py:96-151` is **not** inherently V1-only: its EPISODE-scope
  queries match V3 accounts too (`scope_kind='EPISODE'` exists in both versions — account kind
  does not discriminate workflow version, N2-11), so it gains explicit `seasons.workflow_version='v1'`
  guards preserving V1 response semantics while V3 rows are served by the §6 route; the
  qualification/lookup readers (`S/review/intake.py:936`, `S/review/service.py:325`,
  `S/story/service.py:1117`) are audited — SEASON_RESEARCH-only queries cannot return V3 rows
  (a V3 season has none), so they need no change beyond the audit.
- **Tests:** every existing budget test (`X/integration/budget/**`, `X/contract/**`) runs green and
  unedited; A2's tests are new files (§10); the upgrade test asserts V1 rows and refusals identical
  across 0032–0034.

## 10. Test plan (A-T9..A-T11; real PostgreSQL, ≥2 connections; spec §11 negatives included)

All offline, ephemeral PostgreSQL via the existing conftest, pytest `--basetemp` under the session
scratchpad, real runtime/composition with fakes; `make check` + V1 `make pilot` stay green. The
conftest additionally provisions the `md_runtime` group role, a login role in it, and a second
DSN running as that login (N2R3-2) — additive; every existing test runs unedited through the
existing DSN. **Independent PostgreSQL connections and controlled barriers throughout (N2-15);
deadlock or lock-wait timeout in any race case is a test failure, not a pass condition.**

| ID | File (new unless noted) | Cases |
|---|---|---|
| A-T9 | `X/integration/v3/test_budget_hierarchy.py` | admission-order matrix: four distinct refusals (unit price `UnknownPrice` → step `BudgetExhausted(step_key)` → child cap → season envelope) at their own thresholds; **the A-T9 arithmetic**: 10 episodes × $10 base, $30 setup approved → LOCK validates at committed 30M ≤ 100M; episode reservations beyond the remaining 70M refused at level 4 while each child cap is still 10M; **no cross-step borrowing**: step_05 capacity cannot fund a step_06 reservation (refused, and only an amendment moves caps — N2-7); **setup mutation racing STORY LOCK attach (stale-parent, N2-1/N2-15)**: two connections with a controlled barrier — the setup `reserve` reads identity, the LOCK decision completes the attach, then the setup mutation proceeds under the mutex: it re-reads the attachment, locks the parent and admits against the attached season (never skips it, never a detached parent); **setup before approval refused** (base 0 → every admission refuses; no reservation, no charge); **setup never touches episode accounts** (after LOCK + spend + attribution: episode accounts hold only their own reservations/charges; allocations exist as rows only); **amendment wakeup**: a `RETRY_WAIT`/`defer_reason='BUDGET'` job gets `run_after=now()` in the amendment transaction; **amendment rollback/replay (N2-15)**: a validation failure mid-amendment leaves no amendment row, no step-cap change, no revision advance, no job wakeup; a replayed amendment returns the stored response with no second row; a same-key/different-parameters replay raises `IdempotencyConflict`; **direct-SQL negatives (all via direct SQL, N2-8/N2-4/N2-9/N2R2-2/N2R2-3/N2R2-6)**: `UPDATE budget_accounts SET cap_micro_usd=…` (immutable trigger); `UPDATE budget_steps SET cap_micro_usd=…` without an amendment (it passing *inside* the amendment transaction, and — N2R2-6 — a same-transaction update of an amendment-named step to a **value different from its approved `step_deltas` value** refused: strict account + step + value matching; **a multi-step cap reduction** — setup cap 100→50 with step caps 50/50→25/25 — **commits** (no row-time aggregate bound refuses the intermediate 75), while a `step_deltas`-named step left un-updated, or a completed state breaking `Σ setup caps ≤ setup effective`, refuses at commit (N2R3-3)); `DELETE FROM budget_steps` / `TRUNCATE budget_steps` (refused); non-integer number writes on every new table; amendment INSERT **connected through the provisioned runtime role's login DSN** (`permission denied` — the function-only write boundary holds for the role the app actually runs as, N2R2-3/N2R3-2; the harness also asserts `md_runtime` holds no membership in the migration-owner role and that `md_apply_cap_amendment` succeeds under a session `search_path` pointing at a hostile schema — the pinned definer path cannot be redirected); with INSERT privilege regained (table owner, testing depth): amendment INSERT without a live session; amendment INSERT by an authenticated owner of a *different* season (season-owner guard, N2-9); amendment on a V1 account; amendment with deltas not summing to the change; amendment not applying its category deltas (deferred consistency trigger refuses at commit); amendment whose zero-net category redistribution (`+x/−x`) is skipped or doubled — per-category final-allocation equality against the **stored baseline** refuses where the sum alone would pass (N2R2-2/N2R3-1); amendment INSERT with missing or short `category_baseline` (NOT NULL / deferred refusal — apply-once evidence is mandatory, N2R3-1); a **second** amendment row for one account in one transaction (refused, N2R2-2); a **forged `xact_id`** (server-stamped over it, N2R2-6); reservation `step_key` UPDATE (immutable identity); charge insert whose step disagrees with its reservation's; `episode_production` reservation refused on any account; helper negatives (N2R2-1/N2R3-4): `lock_budget_hierarchy` on the **SEASON account** returns no parent (no spurious "detached"), and a **missing mutex row** raises instead of passing silently; `md_apply_cap_amendment` on a **parentless V3 EPISODE account** (aggregate not yet created) raises detached-hierarchy — the SQL branch matches the Python helper |
| A-T10 | `X/integration/v3/test_budget_concurrency.py` | ≥2 connections, one V3 season post-LOCK: **reserve-vs-reserve boundary (N2-15/N2R2-10)**: sibling admitters (two episode accounts) and same-child admitters — the **start barrier sits before mutex acquisition**; A pauses *after* acquiring the mutex, B is confirmed blocked on that mutex (never a rendezvous inside the lock holder — the order itself would deadlock there, N2R2-10), then A commits and B re-reads and decides against the post-A state; **15 units of remaining capacity, two 10-unit requests: exactly one succeeds**, repeated with only the child limit binding — after every interleaving the stronger invariant holds: `committed ≤ effective` at the admitting level with **no admission-created overrun for ordinary paid admission** (no `cost_overruns` row, no `overrun_micro_usd` growth — overrun arises only from billing; authorized cleanup's admission-recorded overrun is asserted separately, N2R2-5); reserve vs amendment (raise lands between two reserves — second admits against the new effective cap, or `StaleRevision` on a stale `expected_old_effective`); reserve vs settlement vs release vs late billing interleaved on sibling accounts — after every interleaving, invariant asserts `committed ≤ effective + overrun` at child **and** season, `Σ step counters = account counters` (setup and production identities, §2.2), parent counters = Σ children cash exposure; expired holds keep commitment (expire under race); **truthful overrun blocks, child-only vs aggregate separated (N2-15)**: a settlement beyond a *child* cap with the season aggregate still within cap records `cost_overruns` and sets `paid_dispatch_blocked` on that child only — other children keep admitting paid work; a settlement pushing the *season* aggregate over blocks every child; in both cases cleanup is still admitted; **shutdown proceeds with exhausted caps (N2R2-5)**: cleanup reservation on an over-cap V3 account **with no recovery allocation and exhausted categories** is admitted with **no `budget_transfers` row** (no unfunded transfer attempted) and its excess recorded as overrun (child + parent, blocked flags set, `charge_id` NULL for reservation exposure) before the flush, while the same request on a V1 over-cap account is refused (today's behaviour); **the settle-vs-reserve inversion test**: conn A `settle_billed_lease` on episode 1, conn B `reserve` on episode 1's account, both V3 — serialised (no deadlock, no lock-wait inversion); **competing ingestion (N2-5/N2-15/N2R2-4)**: two connections ingesting batches whose bucket sets overlap — both pre-acquire their bucket locks in `bucket_identity_sha256` order before the budget chain; no `#6→#7→#6` cycle, no deadlock, both complete; **invoice-vs-ingestion (N2R2-4)**: an invoice-verification transaction and an ingester with overlapping bucket sets — the verification transaction plans its invoice-period + bucket advisories and season mutexes at the outermost boundary; no outer `#6→#7→#6`, no deadlock (an invoice transaction never holds a season mutex while requesting a bucket an ingester holds); **multi-season expiry (N2R2-4)**: an `expire_stale` batch spanning two seasons races admissions on both seasons — all required season mutexes pre-acquired in `season_id` order, no deadlock; `resolve_billing_recovery` racing a reserve on the target account. **Any raw or translated deadlock or lock-wait timeout in any race case is a failure, never a pass condition (N2R2-10).** |
| A-T11 | `X/integration/v3/test_cost_ledger.py` | exactly-once per canonical receipt: identical replay returns `replayed=True` (`_replay`), differing content → `IdempotencyConflict`; **multi-receipt operation**: ACCRUAL → SETTLEMENT → late ADJUSTMENT on one GPU reservation — each posts once, the settlement replaces accrued per `S/budget/ledger.py:331-349`, the adjustment adds to settled (`:316-330`); late restated SETTLEMENT refused; **late adjustment on a closed hold** recorded truthfully; **setup counted once**: setup charge + attribution to 3 episodes — cash/accrued/reserved panels unchanged by the attribution, attribution panel shows the shares, no episode counter moved; **expired exposure in its actual bucket (N2-13)**: an EXPIRED hold appears in accrued (not reserved) plus the unresolved-exposure listing, never silently zeroed; **cash/accrued/reserved/attribution/subscription/estimate/quota separate (N2-13)**: `SeasonCostsV3` fields populated from distinct sources — subscription allocation reported with `basis='unavailable'` (no ledger source), `llm.subscription` invocations counted in the subscription panel and never as charges, estimate fields returning `estimated_count`/`estimated_micro_usd`/`unknown_estimate_count` with NULL estimates preserved as unknowns (no COALESCE-to-zero), quota unknowns counted; **provider totals replacement-aware (N2-13)**: grouped totals reflect accrual→settlement replacement (an accrued-then-settled reservation counts once); forecast helper (N2-12/N2R2-9): `committed + Σ_{e ∈ unfinished} (per_ep if committed_e = 0 else max(0, per_ep − committed_e))` — a DIRECTED episode with 2M committed and a 10M estimate contributes 8M, never 12M; a full estimate only at zero commitment; blocker above the effective cap, `plan_source`/`plan_binding_sha256` in the response, pre-LOCK setup-only view; **Costs authorization (N2R2-7/N2R3-5)**: the legacy `GET /episodes/{id}/costs` on a **V3** episode returns `NotFound` for another season's owner and for service credentials **before any financial read**, with the **exact response asserted — 404 `NOT_FOUND`, never 401 `Unauthorized`** (the service-principal path maps to NotFound before `require_season_access`, whose `owner_id_in_tx` would otherwise raise Unauthorized, `S/core/auth.py:174`; a V1 episode id keeps today's response); the new V3 route returns `NotFound` for a foreign scope and for service principals **before** any workflow-mismatch or financial detail, same exact-response assertion |
| A-T16 (A2 part) | `X/integration/persistence/test_migrations.py` (extend; upgrade test at `:122` is the pattern) | 0032–0034 apply on a populated V1 database at 0031 head: every existing row unchanged, applied 0001–0031 checksums unchanged, `step_key` NULL on all V1 reservations/charges, `EXPECTED_TABLES` superset holds, the replaced 0003:27-28 predicate refuses the same V1 overage with the trigger's message (on INSERT **and** UPDATE, N2-2), `amendment_revision=0` on all V1 accounts, `md_runtime` provisioned with exactly the runtime grants (INSERT on `account_cap_amendments` unreachable through any membership path, N2R3-2), catalog tests green on the three new tables (incl. `budget_steps` DELETE/TRUNCATE, N2-8) |
| contracts | `X/contract/contracts/test_v3_budget_contracts.py` | `BudgetScopeKind` exact; `_scope_and_bound` setup rule (season named, episode forbidden); `UNSUPPORTED_SCOPE` error schema; `UsageReceipt.step_key` (optional; V1 `None`, V3 validated — N2-8); `SeasonCostsV3` split panels + `budget.cap_amended` examples; generated-contract drift check green (`Makefile:33`) |

## 11. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | LOCK validation refuses when setup commitment > count × base (e.g. $30 setup, 2 episodes → cap $20). No SEASON account exists yet to amend. | Refuse with both numbers in the error; the remedy is re-issuing `create_v3_episodes` with a higher count (the operator's lever), and the setup-approval UI should warn when the approved amount exceeds 10 × a plausible count. No pre-LOCK SEASON amendment. |
| OQ-2 | Exact step-key strings and mapping. **Settled in v1.1 (N2-7):** setup = `step_01..step_04` + `step_10` + `launch`; production steps 5–9 keep their real identities (`step_05..step_09`) against the episode accounts; `episode_production` is the derived envelope (`Σ(step_05..step_09 caps) ≤ envelope cap`). | As settled above; phase B's Script Maker brief should confirm only whether any production step needs *splitting* before A2 builds (the per-step cap split is CostPolicy's to propose). |
| OQ-3 | Are teaser/launch step caps set at setup approval or later? | Created at setup approval inside the approved amount, `launch` defaulting to 0 (no paid launch work until amended) — one approval moment, later changes via §5. |
| OQ-4 | SEASON/SEASON_SETUP SQL sanity ceiling US$1,000 (§2.1). | Accept; policy limits stay in Python (Settings/`CostPolicy`); the ceiling only stops absurd corruption. |
| OQ-5 | Does `approve_setup_budget` also wake BUDGET-waiting jobs? | Yes — same command path (§5); pre-approval there is normally nothing to wake, but the semantics are uniform. |
| OQ-6 | Should V3 attribution reuse `cost_allocations` (source = setup account) or a V3-specific table? | Reuse: the table's shape fits (`M/0003…sql:132-144`) and the Costs API reads one attribution panel; the no-counter-move rule is the V3 difference. |
| OQ-7 | V3 cleanup admits past the cap (A-T10 wording) while V1 cleanup still must fit it (`S/budget/service.py:335-341`). | Keep the divergence: it is exactly master §12.3's "existing cleanup/shutdown exception, recorded truthfully", realised for V3 only; V1 alignment would change V1 behaviour, which phase A forbids. Flagged for the record. |
| OQ-8 | Subscription-allocation basis: no ledger source prices the `llm.subscription` fee today (N2-13). | Report `subscription_allocation=null, basis='unavailable'` (plus invocation counts) until A0 or `Settings` defines an allocation basis; do not fabricate a number from estimate sums. |

— end of note —
