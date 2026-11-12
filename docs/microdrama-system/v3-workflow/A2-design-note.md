# A2 design note: budget hierarchy (accounts, steps, amendments, forecasts, costs)

**Version 1.0, 12 Nov 2026. Author: GLM (design note only; one file, no code).** Requirements:
[phase-A-spec.md](phase-A-spec.md) v0.3 §0, §1, §5 (all), §6, §10 (A2 row + AR-6 activation), §11
(A-T9..A-T11); AC-8, AC-10..AC-14 replacement wording in [codex-a-critique.md](codex-a-critique.md)
(binding per §0) plus its reader/writer inventory; AR-1, AR-2 in
[codex-a-recritique.md](codex-a-recritique.md) (binding); [A1-design-note.md](A1-design-note.md)
v1.2 §1/§2/§6/§9; master [SPEC-v3.md](SPEC-v3.md) v0.4.2 §12.3, §11; [phase-A0-spec.md](phase-A0-spec.md)
v0.4 §5.2/§5.5/§5.6 (the unmetered `llm.subscription` kind). Facts re-verified read-only on
`feat/microdrama-m0-m4` @ `69c4096` (applied tail 0025; 0026 = T031 in `.scratch/t031-gate-h2/`,
0027 = A0, 0028–0031 = A1 — prerequisites, not yet built). `S/` = `microdrama/src/microdrama/`,
`M/` = `microdrama/migrations/`, `X/` = `microdrama/tests/`.

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
| 0032 | `0032_v3_budget_accounts.sql` | Account kinds `SEASON_SETUP`/`SEASON`, `parent_account_id` hierarchy, unique indexes, replaced account CHECKs (cap bound; committed-vs-effective-cap), kind/version guard triggers |
| 0033 | `0033_v3_budget_mutex_steps.sql` | `season_budget_mutex`, `budget_steps`, `reservations.step_key`, `charges.step_key` (+ step linkage guard) |
| 0034 | `0034_v3_cap_amendments.sql` | `account_cap_amendments`, `md_effective_cap()`, amendment guard triggers (human session, V3-only, consistency) |

Ordering: 0032's version guard resolves `seasons.workflow_version` (0028); 0033's step guard reads
`budget_accounts.scope_kind` (0032); 0034's consistency trigger reads `budget_category_allocations`
(0003:36) and `budget_steps` (0033). A3 starts at 0035.

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
| `reserved+accrued+settled <= cap_micro_usd + overrun_micro_usd` (`:27-28`, auto-name `budget_accounts_check2`) | dropped; replaced inside the `budget_accounts_rules` trigger below: `reserved+accrued+settled <= md_effective_cap(id) + overrun_micro_usd` — for rows with no amendments `md_effective_cap = cap_micro_usd`, so V1 semantics are the identical predicate |

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
  IF NEW.reserved_outstanding_micro_usd + NEW.accrued_micro_usd + NEW.settled_micro_usd
     > md_effective_cap(NEW.id) + NEW.overrun_micro_usd THEN
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

`budget_accounts_identity_immutable` (`M/0003…sql:33-34`) keeps guarding `cap_micro_usd` — the base
cap stays immutable in both versions; only `md_effective_cap` moves, via §5's amendments.
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

ALTER TABLE reservations ADD COLUMN step_key text;
ALTER TABLE charges      ADD COLUMN step_key text;

CREATE FUNCTION md_reservation_step_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a record; v text;
BEGIN
  SELECT scope_kind, season_id INTO a FROM budget_accounts WHERE id = NEW.account_id;
  v := (SELECT workflow_version FROM seasons WHERE id = a.season_id);
  IF v = 'v1' THEN
    IF NEW.step_key IS NOT NULL THEN
      RAISE EXCEPTION 'v1 reservations carry no step' USING ERRCODE='check_violation'; END IF;
  ELSE  -- v3: only SEASON_SETUP and post-LOCK EPISODE accounts take reservations
    IF NEW.step_key IS NULL OR a.scope_kind NOT IN ('EPISODE','SEASON_SETUP')
       OR NOT EXISTS (SELECT 1 FROM budget_steps s
                       WHERE s.season_id = a.season_id AND s.step_key = NEW.step_key)
       OR (NEW.step_key = 'episode_production') <> (a.scope_kind = 'EPISODE') THEN
      RAISE EXCEPTION 'v3 reservations must name a budgeted step of their account kind'
        USING ERRCODE='check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reservations_step_rules BEFORE INSERT OR UPDATE ON reservations
  FOR EACH ROW EXECUTE FUNCTION md_reservation_step_rules();
```

Step-key mapping (settled here; OQ-2): `step_01..step_04`, the teaser `step_10` and `launch` are
**setup scope** — they reserve against the `SEASON_SETUP` account (master §12.3: setup binds steps
1–4, music/SFX libraries, teaser). Steps 5–9 are per-episode production; their reservations carry
`step_key='episode_production'` against the episode's `EPISODE` account. `charges.step_key` is
copied from the reservation at post time (`S/budget/service.py:1167-1191`); unreserved V3 receipts
carry the caller's step (validated against `budget_steps`), V1 charges stay NULL.

Why step counters and no SQL sum backstop: every commitment move on a V3 account applies the
identical delta to its `budget_steps` row, so `Σ step counters = account counters` holds by
construction (tested; §10). Step caps are **plan guards** (AC-13: no spill between steps without an
amendment), enforced at admission under the §6 locks; the hard money backstops stay the account and
`SEASON` committed-vs-effective-cap triggers, because a step's *actual late billing* must be
recordable beyond its cap (§3.3) — a step-sum CHECK would refuse that write.

### 2.3 Migration 0034 — cap amendments and the effective cap

```sql
CREATE TABLE account_cap_amendments (
  id                      uuid PRIMARY KEY,
  account_id              uuid NOT NULL REFERENCES budget_accounts(id),
  account_revision        integer NOT NULL CHECK (account_revision >= 0),
  old_effective_micro_usd bigint NOT NULL CHECK (old_effective_micro_usd >= 0),
  new_effective_micro_usd bigint NOT NULL CHECK (new_effective_micro_usd >= 0),
  category_deltas         jsonb NOT NULL,   -- {category: delta int}; must sum to new-old
  step_deltas             jsonb NOT NULL DEFAULT '{}',  -- {step_key: new cap}; optional, same tx
  actor_owner_id          uuid NOT NULL REFERENCES owners(id),
  actor_session_id        uuid NOT NULL REFERENCES human_sessions(id),
  reason                  text NOT NULL CHECK (length(trim(reason)) BETWEEN 1 AND 500),
  idempotency_key         text NOT NULL UNIQUE,
  approved_at             timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_at              timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER account_cap_amendments_append_only BEFORE UPDATE OR DELETE ON account_cap_amendments
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE FUNCTION md_effective_cap(p_account_id uuid) RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    (SELECT a.new_effective_micro_usd FROM account_cap_amendments a
      WHERE a.account_id = p_account_id
      ORDER BY a.approved_at DESC, a.created_at DESC, a.id DESC LIMIT 1),
    (SELECT b.cap_micro_usd FROM budget_accounts b WHERE b.id = p_account_id)) $$;
```

Three guards, each a BEFORE INSERT trigger (the 0007 `md_approval_requires_human_session` pattern,
`M/0007…sql:5-21`):

1. **`md_cap_amendment_requires_human_session`** — live session, owner match, server clock
   (`approved_at := clock_timestamp()`). This is the "direct mutation refused by a guard trigger"
   backstop: a fabricated amendment row without a live human session cannot commit, and
   `cap_micro_usd` itself is immutable (`M/0003…sql:33-34`).
2. **`md_cap_amendment_v3_only`** — the account's season must be `workflow_version='v3'`
   (V1 accounts can never be amended, AC-11/A-T9).
3. **`md_cap_amendment_consistent`** — a DEFERRABLE constraint trigger validating against the
   account: `old_effective = md_effective_cap` as of before this row (latest prior amendment's
   `new_effective`, else base — re-derived in SQL, the backstop behind §5's lock chain);
   `new_effective ≥ 0` (the ≥-committed check runs in Python under the locks). For spending
   accounts (`SEASON_SETUP`, `EPISODE`): `Σ category_deltas = new − old`, every category named
   exactly once with an integer delta, and `Σ(current allocated + delta) = new_effective` (the
   CostPolicy "allocation sums to the cap" invariant, `S/contracts/season.py:117-118`, on effective
   caps). For the aggregate `SEASON` account: `category_deltas = '{}'` (allocations stay 0 — no
   reservation ever lands there). `step_deltas` values are the new step caps, written to
   `budget_steps` by the command in the same transaction.

`md_effective_cap` is the **one** deterministic effective cap used by the SQL guards (0032's
committed trigger) **and** by Python ledger loading: `lock_account` (`S/budget/ledger.py:198-202`)
selects `*, md_effective_cap(id) AS effective_cap_micro_usd ... FOR UPDATE`, and `AccountRow` gains
`effective_cap` (reports' plain reads use the same expression; `account_from_row`,
`S/budget/ledger.py:116-132`). All cap math moves to `effective_cap`; `cap` remains the immutable
base the US$10 episode rule binds (master §12.3; amendments may raise an episode's *effective* cap).

### 2.4 Catalog and contract updates

`EXPECTED_TABLES` (`X/integration/persistence/test_migrations.py:32`, asserted at `:117`) gains
`season_budget_mutex`, `budget_steps`, `account_cap_amendments`. All three tables get the standard
no-TRUNCATE + integer-numbers DO loop (§2 preamble). Generated contracts change and are regenerated
(`microdrama/Makefile:33` drift check): `BudgetScopeKind += SEASON_SETUP`
(`S/contracts/enums.py:200-202`), `BudgetReservationRequest.step_key` + `_scope_and_bound`
(`S/contracts/cost.py:160-191`) setup-scope rule (names `season_id`, no `episode_id`), the new
`UNSUPPORTED_SCOPE` error, the amendment command contract, the `SeasonCostsV3` response (§6) and the
`budget.cap_amended` event schema (dotted name valid: `S/contracts/events.py:21`, `M/0001…sql:118`).

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
def lock_budget_hierarchy(tx: Tx, account_id: UUID) -> None:
    """§6-#7 order: season_budget_mutex → SEASON → (caller locks the child next).
    No-op for V1 accounts and for the SEASON account itself."""
    row = tx.fetchone(
        "SELECT a.season_id, a.parent_account_id, s.workflow_version FROM budget_accounts a "
        "JOIN seasons s ON s.id = a.season_id WHERE a.id = %s", (account_id,))
    if row is None or row["workflow_version"] != "v3":
        return
    tx.execute("SELECT 1 FROM season_budget_mutex WHERE season_id = %s FOR UPDATE",
               (row["season_id"],))
    if row["parent_account_id"] is not None:
        lock_account(tx, row["parent_account_id"])   # already-held locks are no-ops in one tx
```

`parent_account_id` is read without a lock: set once at STORY LOCK, immutable after
(`md_budget_parent_set_once`, §2.1), so the plain read is stable. **A missing parent after LOCK is
an error:** a V3 child mutation that finds `parent_account_id IS NULL` while the season's planning
track is at `STORY_LOCKED` (read under the mutex) raises `Conflict("budget hierarchy detached")` —
the attach is atomic (§4), so this only fires on corruption. Pre-LOCK setup mutations take mutex →
setup account (no parent) — exactly AR-2's protocol.

### 3.3 Admission, in order (AC-13/AC-12; spec §5.2)

Pseudo-code against the real functions — `reserve()` (`S/budget/service.py:322-481`) keeps its
structure; the numbered comments map to the spec's admission order:

```python
def reserve(self, request):                                   # service.py:322
    policy.check_queue_may_reserve(request.queue, request.category)   # policy.py:42 (unchanged)
    policy.check_price_admissible(request, self._settings)            # policy.py:94  — 1. unit price/ceiling
    cleanup = policy.shutdown_grant(...)                              # policy.py:65 (unchanged)
    with self._db.transaction() as tx:
        account_id = resolve_reservation_account(tx, request)         # §3.1 (replaces :372-375)
        lock_budget_hierarchy(tx, account_id)                         # §3.2 — mutex → SEASON
        acct = lock_account(tx, account_id)                           # ledger.py:198 (child)
        step  = lock_step(tx, acct.season_id, request.step_key)       # 0033 row (V3 only)
        cats  = lock_categories(tx, account_id)                       # ledger.py:205
        ledger = self._ledger(tx, acct, cats, step=step, parent=parent_row_or_None)
        # blocked/replay/expiry/scope checks unchanged (:381-402); V3 adds: parent blocked → refuse
        if v3 and parent is not None and parent.blocked and not cleanup:
            raise BudgetExhausted("season overrun")                    # 3.3 truthfulness
        # 2. step cap — no spill between steps (refuse, never borrow):
        if v3 and step.committed + worst > step.cap:
            raise BudgetExhausted("step budget exhausted", step_key=...)
        # 3. child account (cap + category) — today's checks on effective_cap:
        floor = 0 if cleanup else acct.shutdown_reserve
        if acct.committed + worst + floor > acct.effective_cap and not (v3 and cleanup):
            raise BudgetExhausted(...)                                # was :404-414 against cap
        #    recovery-headroom and category/spill rules unchanged (:415-444)
        # 4. SEASON aggregate (post-LOCK only; the parent row is locked and mirrored):
        if v3 and parent is not None and parent.committed + worst > parent.effective_cap \
           and not (v3 and cleanup):
            raise BudgetExhausted("season envelope exhausted")
        insert_row(tx, "reservations", {..., "step_key": request.step_key})   # was :446-470
        ledger.move(request.category, step_key, reserved=worst)       # mirrors child+step+parent
        ledger.flush()
```

**Why admission can never exceed a cap at any level.** Every commitment-changing path takes the
same chain — mutex → SEASON → child → step → categories (§5.3; §8) — so the `committed` counters and
`md_effective_cap` an admission reads are stable for its transaction: amendments, the only writers
of effective caps, take the same chain (§5). Each check adds `worst` to the current committed at its
level and refuses on exceeding that level's effective cap; the insert + counter move happen in the
same transaction, so at commit `committed' = committed + worst ≤ effective` holds at step, child and
season simultaneously. Attribution is not a commitment: V3 `cost_allocations` never move counters
(§6), so nothing is counted twice, and expired/unknown exposure stays counted (`Ledger.expire`
moves reserved→accrued, committed unchanged, `S/budget/ledger.py:388-396`; release is refused while
operations are in flight, `S/budget/service.py:526-539`).

**Truthful overrun and `BLOCKED (overrun)`.** Usage posting never refuses on a cap
(`record_usage` docstring, `S/budget/service.py:850-852`): `_post_charge`
(`S/budget/service.py:1154-1224`) applies the receipt and calls `check_overrun`
(`S/budget/ledger.py:443-471`), which records the excess in `cost_overruns` and sets
`paid_dispatch_blocked`. For V3 the same deltas mirror into the parent, and `check_overrun` also
runs on the **SEASON** row — a season-level excess blocks paid work across every child account.
Blocked admission surfaces as `BudgetExhausted` (`:381-386`), callers defer with A0's `BUDGET`
reason (A0 §5.2) and `track_waits` projects `WAITING_BUDGET` (A1 0031); the data API (§6) exposes
`overrun_micro_usd` and `paid_dispatch_blocked` so the UI labels the scope `BLOCKED (overrun)`.

**Cleanup and shutdown are never refused** (A-T10 "shutdown proceeds with exhausted caps"). Today a
flagged cleanup bypasses the blocked flag and the floor but "still has to fit the cap"
(`S/budget/service.py:335-341`). For **V3** accounts the cap refusal in steps 2–4 above is skipped
when `cleanup` (still only `pod.stop`/`pod.terminate`/`storage.cleanup`, `S/budget/policy.py:56-86`):
the hold is admitted, the excess lands through `check_overrun` on child **and** parent — recorded
truthfully (master §12.3's "existing cleanup/shutdown exception"), and paid dispatch stays blocked.
The 0003/0032 committed trigger admits it because committed ≤ effective + overrun. **V1 keeps
today's behaviour unchanged** (fit-the-cap refusal; recorded in §9 and OQ-7).

## 4. Pre-STORY LOCK protocol and the STORY LOCK transaction (AR-2, AR-1)

**Before STORY LOCK (AR-2).** `create_v3_season` opens, in its command transaction (A1 §6 activates
it here): the season row, `season_tracks(IDEA)` (A1 0030), the `season_budget_mutex` row, and the
`SEASON_SETUP` account — **base cap 0**, shutdown reserve 0, all seven category rows with
`allocated = 0` (`lock_categories` requires the full set, `S/budget/ledger.py:212-213`). Effective
cap 0 means **no paid setup work before approval** (AC-13): every admission refuses at the child
check. `approve_setup_budget` (§5, §7) is the only path to a non-zero effective cap. Account
factories: `open_setup_account` / `open_season_account` follow the idempotent
`open_episode_account` pattern (`S/budget/service.py:220-262`, ON CONFLICT DO NOTHING + re-open
comparison against the expected cap/categories). Pre-LOCK setup
mutations take **mutex → setup account**; admission checks the approved setup budget (child) and
the step caps (§3.3) — no parent exists yet, and none is needed: the mutex makes the LOCK attach
race-free.

**STORY LOCK takes the same mutex.** The LOCK decision transaction (A1 §5) runs its steps 1–8 and
the handler callback (`create_v3_episodes(season, count)`) joins it. Budget attach, inside the same
transaction after the A1 sequence (idempotency → `season_tracks` → seasons → episode/track
inserts), in §6-#7 order:

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
6. Create `budget_steps`: `episode_production` cap = `count × per_episode_base_cap` (the plan
   guard); the setup-step rows already exist from `approve_setup_budget`.
7. **Validate against the SEASON base cap:** `committed_setup ≤ count × per_episode_base_cap`;
   refuse (rolling the whole decision back) otherwise, naming both numbers — OQ-1.

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
LOCK is an error (`§3.2`). Extensions and episode-count changes are `SEASON` amendments (§5).

## 5. Cap amendments (AC-11)

One command path, two faces:

| Command | Actor | Effect |
|---|---|---|
| `approve_setup_budget(season, amount_micro_usd, category_deltas, step_caps, reason, idempotency_key)` | Operator (human session) | An amendment on the `SEASON_SETUP` account from `old_effective = 0` (base 0) to the approved amount; writes the initial `budget_steps` caps (`step_01..step_04`, `step_10`, `launch` — default proposal US$30, `Settings`-supplied; OQ-3) |
| `amend_account_cap(account, expected_old_effective, expected_revision, new_effective, category_deltas, step_deltas?, reason, idempotency_key)` | Operator (human session) | Any later effective-cap change on a V3 account, including `SEASON` (episode-count changes, extensions) |

**Authorisation:** human session + CSRF on the unsafe route (`S/review/api.py:201` refuses
non-human principals; `md_cap_amendment_requires_human_session`, §2.3, is the SQL backstop).
**Idempotency:** `IdempotencyService.execute` with A1's §5 preflight seam;
`account_cap_amendments.idempotency_key` is UNIQUE; a replay returns the stored response.
**Serialisation with admission:** the command takes, in §6 order — idempotency row (#1) → the
RETRY_WAIT job rows it will wake (#5, below) → `lock_budget_hierarchy` (#7: mutex → SEASON for
child amendments) → account → `budget_steps` → categories — so an amendment and an admission are
totally ordered on the same chain; a stale `expected_old_effective` / `account_revision` raises
`StaleRevision` explicitly.

**Ancestor-limit validation (in the same transaction, under those locks):**
- raising a child (`EPISODE`/`SEASON_SETUP`) **never raises `SEASON`**: validate
  `new_effective_child ≤ md_effective_cap(season) − (season.committed − child.committed)` — the
  raised child must still fit the season envelope around its siblings' commitments; a `SEASON`
  raise needs its own amendment row (which is what an episode-count change or extension writes,
  with empty `category_deltas`, §2.3);
- lowering: `new_effective ≥ committed` (never below existing exposure);
- for spending accounts `Σ category_deltas = new − old` and the resulting allocations sum to
  `new_effective` (§2.3 re-checks); `step_deltas` may only move caps of steps owned by that
  account, and for the setup account `Σ step caps ≤ new_effective` after the change.

**Durable wakeup (A0's columns):** in the same transaction, `UPDATE jobs SET run_after = now()
WHERE status='RETRY_WAIT' AND defer_reason='BUDGET' AND season_id = <the season>` (episode
amendment: `... AND episode_id = <the episode>`). The jobs retry time is `run_after`
(`M/0001…sql:86`); `defer_reason` is A0's 0027 column; A-T9 asserts the wakeup. The target job rows
are locked **before** the budget chain (#5 before #7) and re-checked in the UPDATE — no competing
transaction takes job→budget locks today (recorded in §8; A3 must keep it that way).
`approve_setup_budget` runs the same wakeup (OQ-5).

**Direct mutation refused:** `cap_micro_usd` immutable (`M/0003…sql:33-34`); amendment rows
append-only, human-session-guarded, V3-only, consistency-guarded (§2.3) — A-T9 asserts all three
plus the committed-vs-effective-cap trigger on the counters.

## 6. Forecasts and the Costs data API (spec §5.5, §5.6; AC-13, AC-14)

**Forecasts.** `season_forecast(tx, season_id)`, a read helper used at two checkpoints — the
CAST_LOCK gate conditions (A1's `conditions(tx, …)` seam) and V3 render-lane admission (first
render dispatch per season; a blocker, not a money refusal):

```
committed = SEASON account counters (mirrored: setup + episodes, attribution excluded)
remaining = count of episode_tracks with production_state IN ('PLANNED','DIRECTED','RENDERING','EDITING','DRAFTING')
observed  = Σ committed over episodes that have begun production ÷ that count   (0 if none)
plan      = per-episode plan estimate (the episode base cap by default)
forecast  = committed + remaining × max(observed, plan);   capacity = md_effective_cap(season) − committed
```

`forecast > md_effective_cap(season)` is a **gate condition** (blocker) with a "raise the cap or
cut scope" action — the CAST_LOCK gate refuses to open (A1's activation conditions), and render
admission surfaces it as `WAITING_BUDGET` deferral on the dispatching job. Because setup consumes
the envelope (AR-1), `capacity` already nets the setup commitment out of episode capacity — no
second subtraction anywhere (`setup_committed` is shown separately for the UI).

**Costs data API.** One V3 read route, `GET /v3/seasons/{season_id}/costs`
(`S/budget/api.py` gains a sibling router; `require_workflow(expected='v3')` — a V1 season is
`WORKFLOW_MISMATCH`, the V1 route `GET /episodes/{id}/costs` (`S/budget/api.py:21`) is untouched).
Response `SeasonCostsV3` (generated contracts, §2.4), one REPEATABLE READ READ ONLY transaction
(`S/budget/reports.py:3-5` pattern). Separate quantities, each its exact ledger query:

| Quantity | Query |
|---|---|
| **cash** (settled) | `SELECT COALESCE(SUM(settled_micro_usd),0)::bigint FROM budget_accounts WHERE season_id=%s AND scope_kind IN ('SEASON_SETUP','EPISODE')` — Σ settled over the season's cash accounts (the setup account before and after LOCK, episode accounts post-LOCK; the aggregate `SEASON` row is excluded by kind). Per-account rows returned alongside |
| **accrued/unsettled** | same shape on `accrued_micro_usd` |
| **reserved exposure** | same shape on `reserved_outstanding_micro_usd` (expired and past-expiry holds included: EXPIRED rows keep their exposure counted, `S/budget/ledger.py:388-396`; the unknowns listing follows `S/budget/reports.py:81-86`) |
| **attribution** (never cash, never cap consumption) | `SELECT target_account_id, COALESCE(SUM(amount_micro_usd),0) FROM cost_allocations a JOIN budget_accounts t ON t.id=a.target_account_id WHERE t.season_id=%s GROUP BY 1` — display only: V3 allocations move no counters (below) |
| **setup counted once** | setup charges exist once on the setup account; the attribution panel references them (`source_account_id`); no panel sums allocation shares into cash — the setup account's own counters are the single count |
| **step panel** | `SELECT step_key, cap_micro_usd, reserved_outstanding_micro_usd, accrued_micro_usd, settled_micro_usd FROM budget_steps WHERE season_id=%s` |
| **provider attribution** | `charges.step_key` + `charges.provider` (`M/0003…sql:105`), grouped |
| **subscription allocation / LLM estimates** | `SELECT COUNT(*), COALESCE(SUM(cost_estimate_microusd),0) FROM llm_invocations WHERE season_id=%s` — A0's 0027 records; `llm.subscription` is unmetered (A0 §5.5 item 5: no `UsageReceipt`, no charge), so it appears **only** here |
| **quota** | latest `quota_observations` per invocation (A0 0027) |
| **overrun / blocked** | `overrun_micro_usd`, `paid_dispatch_blocked` per account + season (§3.3) |
| **forecast** | the §6 helper output + inputs |

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

| Command | Actor | Scope / revision owner | Prerequisites (hash-bound where applicable) | Writes | Events | Replay identity | Activation |
|---|---|---|---|---|---|---|---|
| `create_v3_season(intake_ref)` | Operator (human session) | season / — | A1 §6 (intake ref, owner scope) | seasons(v3, PROPOSED) + `season_tracks(IDEA)` + `season_budget_mutex` + `SEASON_SETUP` account (base 0, categories 0) | (A1's creation events) | idempotency key | **A2** (AR-6) |
| `approve_setup_budget(season, amount, category_deltas, step_caps, reason)` | Operator (human session + CSRF) | setup account / expected `old_effective = 0` + `account_revision` | season is v3; no prior setup approval (`old_effective` 0); amount within the Settings bound | `account_cap_amendments` row (0 → amount); `budget_steps` initial caps; BUDGET-job wakeup | `budget.cap_amended` | idempotency key | **A2** |
| `create_v3_episodes(season, count)` | System (STORY LOCK handler); exposed to test handlers in phase A | season / `season_tracks.revision` | STORY LOCK APPROVE decision (A1 §5 transaction); §4 validation passes | episodes (legacy PLANNED) + `episode_tracks` + `SEASON` account + parent attach + `EPISODE` accounts + `episode_production` step | (LOCK decision's own events, A1 §5) | semantic `(scope, from, to, revision)` | **A2** (AR-6) |
| `amend_account_cap(account, expected_old_effective, expected_revision, new_effective, category_deltas, step_deltas?, reason)` | Operator (human session + CSRF) | account / `account_revision` + `old_effective` | §5 validations (ancestor limits, deltas sum, V3-only) | `account_cap_amendments` row; `budget_steps` caps; BUDGET-job wakeup | `budget.cap_amended` | idempotency key | **A2** |
| STORY LOCK budget step (the §4 attach) | System, inside the LOCK decision | season / decision revision + binding hash | §4 steps 1–7 | as §4 | (LOCK's own events, A1) | the decision's idempotency key | **A2** |

Every row runs through `IdempotencyService.execute` with the §5 preflight; a refusal writes
**nothing** (A-T2 pattern). The `budget.cap_amended` payload schema: `{account_id, scope_kind,
season_id, old_effective_micro_usd, new_effective_micro_usd, reason, actor_owner_id, revision}`.

## 8. Lock audit (spec §6 #7; AC-8, AC-12)

The §6 table (A1 §9) row 7 in full: `season_budget_mutex → SEASON → child accounts (id order) →
budget_steps → categories → reservations → charges/receipts`, the audit including provider-operation
advisory locks and caller-owned billing transactions. Every transaction A2 adds or touches:

| Transaction | Locks in order | Verdict |
|---|---|---|
| `reserve` (V3) | policy checks (no locks) → tx: mutex → SEASON → child → step row → categories → replay read → reservation insert | conforms (§3.3) |
| `release` (`S/budget/service.py:484-543`) | mutex → SEASON → child (`:500`) → categories (`:501`) → reservation (`:502`) — today's order preserved, hierarchy prepended | conforms |
| `expire_stale` (`:545-577`) | per distinct account in `:557` id order: mutex → SEASON → child (`:562`) → categories (`:563`) → reservations FOR UPDATE id order (`:566`) | conforms |
| `record_usage_in_transaction` (`:864-880`) | mutex → SEASON → child (`:872`) → categories (`:873`) → linked reservation (`_linked_reservation`, `:1068-1080`) → charge insert | conforms |
| `_record_gpu_interval` (`:882-956`) | mutex → SEASON → child (`:912`) → categories (`:913`) → lease read → overlap check → charge + interval inserts; the pod EXCLUDE gist 40P01 mapping (`:997-1006`) unchanged | conforms |
| `settle_billed_lease` (`S/budget/billing.py:1269`) | **today: child account (`:1296`) → reservation (`:1297`) → `record_usage_in_transaction` (`:1367`) — child-before-parent, the inversion the spec names.** Fix: `lock_budget_hierarchy` before `:1296`; the rest unchanged | **fixed** — competing test §10 |
| `resolve_billing_recovery` (`:747-831`) | advisory xact lock on the allocation (`:761`, #6-class, before budget) → hierarchy → child (`:811`) → categories (`:812`) → charge (`:817`) → resolution insert (`:820`) | **fixed** (hierarchy prepended before `:811`) |
| `reconcile_provider_allocation_in_transaction` (`:588-704`) | advisory (`:611`) → posting row FOR UPDATE (`:615`) → hierarchy → child (`:654`) → categories (`:655`) → `_lease_window_reservation` FOR UPDATE (`:1040-1065`) → charge | **fixed** (hierarchy before `:654`) |
| `record_provider_invoice_verification_in_transaction` (`:718-745`) | advisory (`:729`) → finalization row (`:732`) — no account locks (evidence only) | n/a (unchanged) |
| `transfer` (`:1228-1272`) | mutex → SEASON → child (`:1246`) → categories (`:1247`) → `budget_transfers` insert (`S/budget/ledger.py:417-421`) | conforms |
| `attribute_setup_cost` (V3, §6) | mutex → SEASON → source (setup) → target accounts in id order — allocations only, no counter moves | conforms |
| `approve_setup_budget` / `amend_account_cap` (§5) | idempotency (#1) → RETRY_WAIT job rows FOR UPDATE (#5) → mutex → SEASON (child amendments) → account → steps → categories → amendment insert → job UPDATE | conforms (#5 before #7; no existing path takes job→budget — A3 must preserve this; recorded as A2's only new order, with the §10 race test) |
| STORY LOCK decision + attach (§4) | A1 §5 order (1 → 2 → 4 → episode/track inserts → 3) then §4's mutex → setup → SEASON create → parent set → episode accounts → steps | conforms (inserts of not-yet-existing rows serialise under the mutex + unique indexes, per A1 §9's justification) |
| `create_v3_season` | idempotency → A1's creation order → mutex row + setup account inserts | conforms |
| V1 paths | helper is a no-op (no mutex row, `workflow_version='v1'`): lock sequences byte-identical to today | untouched |

**Provider-operation advisory locks:** the three `pg_advisory_xact_lock` sites
(`S/budget/service.py:611`/`:729`/`:761`, keys 451047-9) all take the advisory before any budget row
lock — #6-class before #7, no inversion; A2 adds none. The lease claim's two-transaction pattern
(`S/rendering/leases.py:702-716`: reserve tx, then lease-insert tx) stays; each transaction holds
one lock class plus the already-held scope track lock (A1 §8/§9). Worker-completion
job-before-track order remains A3's row (A1 §9 item 1); A2 adds no such transaction.

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
  accounts can never have them (§2.3 guard 2). V1 cleanup still must fit the cap (`:335-341`);
  only V3 cleanup admits past it (§3.3, OQ-7).
- **SQL:** the 0003:27-28 CHECK becomes the 0032 trigger with the identical predicate; the 0003:13
  cap bound keeps `≤ 10_000_000` verbatim for V1 kinds; scope-kind, episode-binding, queue and
  category CHECKs are extended additively. `md_reservation_step_rules` requires `step_key IS NULL`
  on V1 reservations — today's rows are all NULL (the column is new).
- **Ledger:** `Ledger.move/apply_receipt/expire/release/check_overrun/flush`
  (`S/budget/ledger.py:266-535`) gain step/parent mirroring that activates only for V3 accounts;
  V1 counter semantics, revision guards and error types are untouched.
- **Research allocation:** `allocate_research_cost` (`S/budget/service.py:1276-1401`) keeps its body
  and `_check_research_share` refusals for V1; the no-counter V3 variant is a separate method.
- **Settlement/recovery:** `settle_billed_lease`, `resolve_billing_recovery`,
  `reconcile_provider_allocation` gain only the no-op-for-V1 hierarchy call; postings, evidence and
  idempotency unchanged.
- **API:** `GET /episodes/{id}/costs` (`S/budget/api.py:21`), `S/budget/reports.py` and
  `S/analytics/cost.py:111-151` are untouched (the latter aggregates V1 kinds only); the V3 route
  is separate.
- **Tests:** every existing budget test (`X/integration/budget/**`, `X/contract/**`) runs green and
  unedited; A2's tests are new files (§10); the upgrade test asserts V1 rows and refusals identical
  across 0032–0034.

## 10. Test plan (A-T9..A-T11; real PostgreSQL, ≥2 connections; spec §11 negatives included)

All offline, ephemeral PostgreSQL via the existing conftest, pytest `--basetemp` under the session
scratchpad, real runtime/composition with fakes; `make check` + V1 `make pilot` stay green.

| ID | File (new unless noted) | Cases |
|---|---|---|
| A-T9 | `X/integration/v3/test_budget_hierarchy.py` | admission-order matrix: four distinct refusals (unit price `UnknownPrice` → step `BudgetExhausted(step_key)` → child cap → season envelope) at their own thresholds; **the A-T9 arithmetic**: 10 episodes × $10 base, $30 setup approved → LOCK validates at committed 30M ≤ 100M; episode reservations beyond the remaining 70M refused at level 4 while each child cap is still 10M; **setup mutation racing STORY LOCK attach**: two connections, one setup `reserve`, one LOCK decision — the mutex serialises them; whichever wins, the other sees the post-state (attach includes the hold, or the hold admits against the attached parent); never a detached parent; **setup before approval refused** (base 0 → every admission refuses; no reservation, no charge); **setup never touches episode accounts** (after LOCK + spend + attribution: episode accounts hold only their own reservations/charges; allocations exist as rows only); **amendment wakeup**: a `RETRY_WAIT`/`defer_reason='BUDGET'` job gets `run_after=now()` in the amendment transaction; **direct-SQL amendment refused**: `UPDATE budget_accounts SET cap_micro_usd=…` (immutable trigger), amendment INSERT without a live session, amendment on a V1 account, amendment with deltas not summing to the change — all raise; **V1 accounts can't be amended** |
| A-T10 | `X/integration/v3/test_budget_concurrency.py` | ≥2 connections, one V3 season post-LOCK: reserve vs amendment (raise lands between two reserves — second admits against the new effective cap, or `StaleRevision` on a stale `expected_old_effective`); reserve vs settlement vs release vs late billing interleaved on sibling accounts — after every interleaving, invariant asserts `committed ≤ effective + overrun` at child **and** season, `Σ step counters = account counters`, parent counters = Σ children cash exposure; expired holds keep commitment (expire under race); **truthful overrun blocks**: a settlement beyond the child cap records `cost_overruns`, sets `paid_dispatch_blocked` on child and season, every further paid admission refuses, cleanup still admitted; **shutdown proceeds with exhausted caps**: cleanup reservation on an over-cap V3 account is admitted and its excess recorded as overrun (child + parent), while the same request on a V1 over-cap account is refused (today's behaviour); the settle-vs-reserve **inversion test**: conn A `settle_billed_lease` on episode 1, conn B `reserve` on episode 1's account, both V3 — serialised (no deadlock, no lock-wait inversion); `resolve_billing_recovery` racing a reserve on the target account |
| A-T11 | `X/integration/v3/test_cost_ledger.py` | exactly-once per canonical receipt: identical replay returns `replayed=True` (`_replay`), differing content → `IdempotencyConflict`; **multi-receipt operation**: ACCRUAL → SETTLEMENT → late ADJUSTMENT on one GPU reservation — each posts once, the settlement replaces accrued per `S/budget/ledger.py:331-349`, the adjustment adds to settled (`:316-330`); late restated SETTLEMENT refused; **late adjustment on a closed hold** recorded truthfully; **setup counted once**: setup charge + attribution to 3 episodes — cash/accrued/reserved panels unchanged by the attribution, attribution panel shows the shares, no episode counter moved; **unknown exposure retained**: EXPIRED hold counts until settlement reconciles; **cash/accrued/reserved/attribution/estimate/quota separate**: `SeasonCostsV3` fields populated from distinct sources (charges/counters/`llm_invocations`/`quota_observations`), `llm.subscription` invocations appear in the subscription panel and never as charges; forecast helper: committed + remaining × max(observed, plan), blocker above the effective cap |
| A-T16 (A2 part) | `X/integration/persistence/test_migrations.py` (extend; upgrade test at `:122` is the pattern) | 0032–0034 apply on a populated V1 database at 0031 head: every existing row unchanged, applied 0001–0031 checksums unchanged, `step_key` NULL on all V1 reservations/charges, `EXPECTED_TABLES` superset holds, the replaced 0003:27-28 predicate refuses the same V1 overage with the trigger's message, catalog tests green on the three new tables |
| contracts | `X/contract/contracts/test_v3_budget_contracts.py` | `BudgetScopeKind` exact; `_scope_and_bound` setup rule (season named, episode forbidden); `UNSUPPORTED_SCOPE` error schema; `SeasonCostsV3` + `budget.cap_amended` examples; generated-contract drift check green (`Makefile:33`) |

## 11. Open questions

| # | Question | Recommendation |
|---|----------|----------------|
| OQ-1 | LOCK validation refuses when setup commitment > count × base (e.g. $30 setup, 2 episodes → cap $20). No SEASON account exists yet to amend. | Refuse with both numbers in the error; the remedy is re-issuing `create_v3_episodes` with a higher count (the operator's lever), and the setup-approval UI should warn when the approved amount exceeds 10 × a plausible count. No pre-LOCK SEASON amendment. |
| OQ-2 | Exact step-key strings and their mapping (1–4 + teaser + launch setup-scope; 5–9 → `episode_production`). | As proposed in §2.2 (`step_01..step_10`, `launch`, `episode_production`); phase B's Script Maker brief should confirm no step needs splitting before A2 builds. |
| OQ-3 | Are teaser/launch step caps set at setup approval or later? | Created at setup approval inside the approved amount, `launch` defaulting to 0 (no paid launch work until amended) — one approval moment, later changes via §5. |
| OQ-4 | SEASON/SEASON_SETUP SQL sanity ceiling US$1,000 (§2.1). | Accept; policy limits stay in Python (Settings/`CostPolicy`); the ceiling only stops absurd corruption. |
| OQ-5 | Does `approve_setup_budget` also wake BUDGET-waiting jobs? | Yes — same command path (§5); pre-approval there is normally nothing to wake, but the semantics are uniform. |
| OQ-6 | Should V3 attribution reuse `cost_allocations` (source = setup account) or a V3-specific table? | Reuse: the table's shape fits (`M/0003…sql:132-144`) and the Costs API reads one attribution panel; the no-counter-move rule is the V3 difference. |
| OQ-7 | V3 cleanup admits past the cap (A-T10 wording) while V1 cleanup still must fit it (`S/budget/service.py:335-341`). | Keep the divergence: it is exactly master §12.3's "existing cleanup/shutdown exception, recorded truthfully", realised for V3 only; V1 alignment would change V1 behaviour, which phase A forbids. Flagged for the record. |

— end of note —
