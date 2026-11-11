# Phase A: Foundations

**Version 0.3, 11 Nov 2026.** Author: Opus orchestrator.

**Status:** both Codex rounds are applied:
- Round 1: [codex-a-critique.md](codex-a-critique.md), AC-1..23.
- Round 2: [codex-a-recritique.md](codex-a-recritique.md), AR-1..6.

The next checks are the pre-code critiques of the package design notes (§10).

**Master:** [SPEC-v3.md](SPEC-v3.md) v0.4.2. **Depends on:** [phase-A0-spec.md](phase-A0-spec.md) v0.4.

**Facts:** [a-factmap.md](a-factmap.md), plus the reader/writer inventory in codex-a-critique.md. Code
references are relative to `microdrama/src/microdrama/`; migrations to `microdrama/migrations/`.

**Owns:** V3-AT-1, 2, 13, 16, 20, 21 and R-11.2..R-11.6, R-12.6, R-12.7.

---

## 0. How v0.2 is organised

1. **Binding decisions (§2–§9):** v0.2 settles every choice that v0.1 left to the builder.
2. **Codex's replacement wording is binding.** Every AC-n replacement wording in codex-a-critique.md is
   a requirement, except where §2–§9 choose differently; §12 maps each one.
3. **The build is split into six ordered packages** (§10), A1–A6, each with its own gate.
4. **Design notes for the first three packages are critiqued before code.**
   - **A1–A3** (contracts, money, fencing) each start with a **design note**: exact DDL, the command table
     and the lock audit. The note gets a scoped Codex critique **before code**.
   - **A4–A6** submit the note with the diff.

## 1. Principle: V1 is preserved by enforcement, not by convention

- **`seasons.workflow_version`** (AC-5):
  - `text NOT NULL DEFAULT 'v1' CHECK IN ('v1','v3')`;
  - **immutable** (a guard trigger);
  - episodes can't be re-parented (a guard on `episodes.season_id`);
  - episodes and jobs derive their version through the season FK, so there is no second column.
- **Every legacy entry point checks the version before executing.** One shared helper,
  `require_workflow(tx, season_id, 'v1')`, is called from:
  - every service, handler and scheduler selector in the critique's inventory (research, intake, story,
    references, editing, QA repair, packaging, publishing, analytics);
  - replayed jobs.

  **A V3 row reaching a legacy path is refused with `WORKFLOW_MISMATCH`.** It is never silently
  processed.
- **Shared janitors** (job, GPU, billing) keep covering both versions through per-version adapters, not
  blanket filters.
- **V3 seasons keep the legacy `seasons.state` at `PROPOSED`, and their episodes at `PLANNED`, forever.**
  - V3 code never writes legacy state. Legacy readers never see V3 rows, because of the guards above.
  - **No SQL rule keyed on `SEASON_APPROVED` is touched in phase A** (AC-6; the v0.1 pin is dropped).
- **The V1 command/action contracts are unchanged**: `GATE_ACTIONS`, `ApprovalCommand`, the generated
  contracts and their exact tests. V3 adds parallel, version-selected validation (AC-1).
- V1 tests are never weakened; V3 behaviour gets new tests (AC-23).

## 2. Gates (A1; AC-1..4, AC-22)

1. **Values.** `GateType` gains `STORY_LOCK`, `CAST_LOCK`, `TEASER_FINAL`, `LAUNCH`.
2. **Actions** (`V3_GATE_ACTIONS`, used only for V3 seasons): **master §2.1 as written**,
   Approve/Revise/Reject on every V3 gate.
   - **Reject never cancels a season** (AR-3):
     - **Reject CAST_LOCK** leaves planning at `CASTING` without cast authority.
     - **Reject LAUNCH** leaves the **release** track at `CALENDAR_PROPOSED` without launch authority. The
       planning track is not touched.
   - **Every decision closes its activation** and advances the decision revision. Another decision needs a
     new activation.
   - Changes that affect earlier authority go through scoped amendment invalidation (§7), which keeps
     unrelated approved releases.
   - V1 `SEASON_CONCEPT` Revise stays refused at its existing boundary.
3. **SQL.**
   - The 0002 gate/entity/action CHECKs are replaced by version-aware constraint triggers. V1 rows keep
     exactly today's rules.
   - The feedback CHECK becomes gate-specific:
     - `EPISODE_FINAL` Revise requires timecoded feedback (unchanged);
     - V3 season-gate Revise requires an **empty** feedback array **and** ≥1 `season_revision_notes`
       row (a deferred constraint trigger).
   - All 0007–0021 approval guards are preserved unchanged for V1. Any V3 equivalent is added beside
     them.
4. **Revision notes** (AC-2): `season_revision_notes` (append-only):
   - `approval_event_id`, `season_id`, `gate`, `text`;
   - `targets`: typed `{kind, id}` refs, validated against the gate's binding units;
   - `created_at`.

   They are written by the V3 decision command, never into `feedback_events`.
5. **Gate activation** (AC-22): `gate_activations` (append-only):
   - `gate`, scope (`season_id`, optional `episode_id`);
   - `binding_sha256`, `content_revision`;
   - `opened_at`, `opened_by_job`;
   - `superseded_by`.

   **A gate is open only when its phase handler activates it** with a binding. "Waiting for you" lists
   open activations without a decision. Future gates are never shown as open.
6. **The decision transaction** (AC-3). One caller-owned transaction, in the §6 lock order:
   1. idempotency-key replay check first (a replay returns the stored response);
   2. lock the scope rows and the track;
   3. resolve ownership (owner scope), workflow version, the active activation, its binding hash and the
      **authoritative content revision**;
   4. compare with the command's expected hash and revision;
   5. evaluate `conditions(tx, …)`;
   6. record the approval event;
   7. run the handler callback in the same transaction (its writes, job enqueues, events);
   8. store the idempotent response.

   **Any failure rolls everything back.** The binding resolver is version-aware: V1 keeps
   `core/approvals.py:64` unchanged.
7. **The handler registry** (AC-4):
   - normal compositions register **no** handler for a V3 gate whose phase hasn't shipped. Such a gate
     returns `NOT_AVAILABLE` **before any recording or callback**;
   - test handlers can only be registered through explicit test-world injection, which
     `build_production_world` refuses;
   - a missing V3 handler **never falls back to V1**;
   - tested for all three Gate 2 actions through both the JSON and HTML routes.
8. **Human-session, CSRF and service-credential rules** are reused unchanged and tested negatively
   (§11).

## 3. Tracks (A1; AC-6, AC-7)

- **`season_tracks`:**
  - `season_id`, `planning_state`, `release_state`;
  - **`content_revision`**: the amendment fence, bumped only by amendments and lock decisions;
  - `revision`: optimistic display/command revision.
- **`episode_tracks`:**
  - `episode_id`, `production_state`, `release_state`;
  - **`content_revision`**, `revision`.
- **`season_extensions`** (replaces v0.1's `extending` flag; master §2.2):
  - `extension_id`, `season_id`, `planning_state`, `episode_range`, `content_revision`;
  - a scope with its own planning track. `EXTENDING` is derived as "an open extension exists".
- **Side states are derived, never stored** (AC-7, AR-4). V3 jobs carry `work_scope`:
  - `season_id`, `episode_id?`, `extension_id?`;
  - **`track`** (`planning` / `production` / `release`);
  - **`logical_work_id`**, plus `replaces_job_id`: a replacement identity separate from the UNIQUE
    `jobs.semantic_key` (0001:78).

  **`track_waits(scope, track)`** is computed from:
  - **non-terminal jobs** for that scope and track:
    - `RETRY_WAIT` + `defer_reason` (A0 §5.2) → `WAITING_QUOTA` / `WAITING_PROVIDER` /
      `WAITING_BUDGET`, with `retry_at`;
    - `NEEDS_RECONCILIATION` → `BLOCKED (reconcile)`;
  - **unresolved provider operations** (in flight or `UNKNOWN`) linked to the scope's jobs → `BLOCKED
    (reconcile)`. This holds **even for cancelled or stale jobs**, until reconciliation settles them;
  - **terminal `FAILED` jobs** under the current content authority whose `logical_work_id` has no later
    successful replacement → `BLOCKED (failed)`;
  - **cancellation**: the track's own cancelled state.

  Rules:
  - Several waits show together. One job resuming can't clear another's wait.
  - **An operator acknowledgement (`alert_dismissals`) only hides an alert.** It never establishes
    completion or approval.
- **The phase A command table** (A1's design note gives the full columns per AC-6: actor, scope, expected
  revision, source → target, hash-bound prerequisites, writes, jobs, events, replay identity):

| Command | Notes |
|---------|-------|
| `create_v3_season(intake_ref)` | Creates the season (`v3`, legacy `PROPOSED`) + `season_tracks(IDEA)` + the `SEASON_SETUP` account (§5) |
| `create_v3_episodes(season, count)` | At STORY LOCK (called by the B handler; phase A exposes it to test handlers): episodes (legacy `PLANNED`) + `episode_tracks` + `EPISODE` accounts + the `SEASON` account (§5.1) |
| `open_gate(gate, scope, binding)` / `supersede_gate(...)` | Gate activation (§2.5) |
| `advance_planning(to)` | Only edges whose prerequisites are met (including an approval event for gate edges); all other master edges are **unavailable** until their phase |
| `reject_to(previous)` | From a V3 Reject (§2.2) |
| `cancel_season` / `cancel_episode` | Terminal; cancels queued jobs through the transaction-owned helper (§7.4) |
| `rewind_for_amendment(scope, to)` | Only through the amendment coordinator (§7) |
| `create_extension(season, range)` | Opens a `season_extensions` scope |

Later-phase transitions stay unavailable (`NOT_AVAILABLE`) until their phases register them.

## 4. Runtime and queues (A3; AC-7, AC-10, AC-23)

- **A0 owns the runtime contract changes:**
  - `Deferred`, `defer_reason`, `refund_attempt`;
  - the signal translation;
  - `REFUSED_PRELAUNCH`;
  - the unmetered kind.

  Phase A **consumes** them and adds no second variant.
- **Phase A adds no new queue lanes.** Each later phase adds its lanes through one checklist:
  - the queue SQL CHECKs on jobs and reservations;
  - `budget/policy.py` ownership;
  - the worker process set;
  - the generated contracts.
- **Per-queue worker processes:** `api/worker.py --queues …` in the production composition.

## 5. Budget hierarchy (A2; AC-10..14; master §12.3)

### 5.1 Accounts and lookup (AC-10)

| Kind | When | Base cap | Reservations |
|------|------|----------|--------------|
| `SEASON_SETUP` | Created at season creation | The **setup budget**, proposed by the system (default US$30), **effective only after the operator's recorded approval** (`approve_setup_budget`, human session); **no paid setup work before it** (AC-13) | Yes |
| `SEASON` | Created at STORY LOCK | **episode count × the approved per-episode base cap.** Setup **consumes** this envelope; it is never added to it (AR-1, master §12.3). Any increase is a separately recorded `SEASON` amendment | **None; aggregate-only** |
| `EPISODE` (V3) | At STORY LOCK | US$10 | Yes |

- Each V3 season has a **unique** `SEASON` and `SEASON_SETUP` account (unique index).
- `SEASON_SETUP` and `EPISODE` accounts reference their `SEASON` parent once it exists.
- **Before STORY LOCK** (AR-2):
  - admission checks the approved setup budget and the step limits;
  - **every setup commitment mutation takes the season budget mutex** (`season_budget_mutex`, one row per
    V3 season, created with the season; §6 #7).
- **STORY LOCK takes the same mutex.** Atomically, it:
  1. creates the `SEASON` account;
  2. attaches the existing setup exposure;
  3. creates the episode accounts;
  4. validates that current commitments fit the `SEASON` base cap.
- **After attachment,** every mutation takes mutex → `SEASON` → child. A missing parent after LOCK is an
  error.
- **Lookup is explicit per scope kind.** An unsupported kind is rejected with `UNSUPPORTED_SCOPE`.
  Today's non-EPISODE → research fallback (`budget/service.py:372`) is kept **for V1 only**.
- The reservation and receipt contracts, account factories, ledger loading, policy, SQL CHECKs and every
  reader listed in the critique are updated.

### 5.2 Step budgets (AC-13; R-12.7)

- **`budget_steps`:** `season_id`, `step_key` (master steps 1–10 + `launch` + `episode_production`),
  `cap_micro_usd`, set with the setup approval and at LOCK.
- **Every V3 reservation carries a `step_key`.**
- **Admission checks, in order:**
  1. unit price/ceiling;
  2. the step cap;
  3. the child account (cap + category);
  4. the `SEASON` aggregate.
- **No spill between steps without an amendment.**

### 5.3 Commitment and serialisation (AC-8, AC-12)

- **Season commitment** = Σ over the child accounts of the canonical counters (reserved + accrued +
  settled), retaining expired and unknown exposure. Attribution allocations are excluded, so nothing is
  counted twice.
- **Every commitment-changing path for a V3 account takes the `SEASON` lock before the child lock:**
  reserve, release, expiry, GPU accrual, usage posting, settlement, adjustment and transfers.
  - Shared ledger helpers that lock a child first (`budget/billing.py:1296`) get the ancestor lock
    **before entry**.
  - V1 paths are unchanged.
- **Admission can never exceed a cap at any level.**
  - Actual billing beyond a cap (a provider overcharge, a late adjustment) is **recorded truthfully**
    (`budget/ledger.py:443` semantics), and blocks further paid work in that scope (`BLOCKED (overrun)`).
  - **Cleanup and shutdown are never refused** (the existing exception), and are recorded.

### 5.4 Cap amendments (AC-11)

- **The base cap (`cap_micro_usd`) stays immutable.**
- **`account_cap_amendments`** (append-only, guarded):
  - `account_id`, `account_revision`, `old_effective`, `new_effective`;
  - the category deltas (they must sum to the change);
  - the actor + human session, `reason`, `idempotency_key`, `approved_at`.
- **The effective cap** is computed by one SQL function, `md_effective_cap(account_id)` (latest approved
  amendment, else base). It is used by the SQL guards **and** by Python ledger loading.
  - The US$10 EPISODE rule applies to the **base**. V3 episode amendments may raise the effective cap.
  - **V1 accounts can't be amended.**
- **An amendment serialises with admission** (§6 lock order) and validates the ancestor limits: raising a
  child never raises `SEASON`; `SEASON` needs its own amendment.
- **In the same transaction**, it sets `retry_at = now` on `RETRY_WAIT` jobs in that scope with
  `defer_reason = BUDGET`. That is the durable wakeup.
- **Direct mutation is refused by a guard trigger.**
- **Episode-count changes and extensions** are `SEASON` amendments (count × the episode cap).

### 5.5 Forecasts

Checkpoints before CAST LOCK and before rendering:
`forecast = committed (including setup) + remaining episodes × max(observed average, plan estimate)`.
Because setup consumes the `SEASON` envelope, the capacity left for episode production is the cap minus
the setup commitment.

- A forecast above the cap is a **gate condition** (blocker) with a "raise the cap or cut scope" action.

### 5.6 Costs page (AC-14)

Separate quantities, from ledger semantics:
- **cash**: settled charges;
- **accrued/unsettled**;
- **reserved exposure**;
- **attribution**: allocations, never new cash and never episode-cap consumption.

Plus:
- **Setup is counted once.**
- **Step and provider attribution are persisted** on the reservation and receipt.
- **Separate panels:** subscription allocation, LLM estimates (`llm_invocations`) and quota.
- **Receipts:** exactly-once posting per canonical receipt, including **operations with several receipts**
  (GPU accrual → settlement).

## 6. Lock order (A1–A3; AC-8)

**One order for every transaction that takes more than one of these.** Each package's design note audits
every caller-owned transaction it touches against this table, and adds a competing-transaction test for
each inversion it finds.

| # | Lock |
|---|------|
| 1 | Command idempotency row |
| 2 | `season_tracks`, then `season_extensions` |
| 3 | `episode_tracks` (id order) |
| 4 | Scope domain rows (seasons, episodes, approvals) |
| 5 | Jobs (id order) |
| 6 | `provider_operations` → leases (GPU) |
| 7 | Budget: `season_budget_mutex` → `SEASON` → child accounts (id order) → `budget_steps` → categories → reservations → charges/receipts. The audit includes provider-operation advisory locks and caller-owned billing transactions |

- **Fence reads take a SHARE lock on the track (2/3); amendments take FOR UPDATE.**
- **A worker completion that needs both track and job locks takes the track first.**

## 7. Amendments and the fence (A3 + A4; AC-15, AC-16; master §12.6)

### 7.1 The fence (A3)

- **Every V3 job input carries `expected_content_revision`** for its scope.
- **It is validated:**
  - at enqueue and at admission;
  - **before every canonical mutation**, holding the track SHARE lock through that mutation's
    transaction.

  This includes collectors, acceptance, continuations and reconciliation adoption.
- **A stale result is never installed as current content.**
  - Provider outputs and receipts are kept as **quarantined evidence** (`stale_artifacts`: job, operation,
    artifact refs, expected vs actual revision).
  - Money is still accounted normally.

### 7.2 Approval supersession (A4)

- **`approval_supersessions`** (append-only): `approval_event_id`, `amendment_id`, `at`.
- **One reader, `effective_approval(tx, gate, scope)`**, returns the latest non-superseded approval. It is
  used by **every authority reader** in the critique's inventory:
  - `identity_lock`, QA repairs, `load_approved_metadata`, publishing admission, memberships,
    qualification;
  - plus the UI.

  V1 behaviour is unchanged: V1 approvals are never superseded.

### 7.3 The coordinator (A4)

- **`amendments`** (append-only):
  - the scope, the trigger, the changed roots, the computed closure (`DependencyProvider` registry;
    phase A wraps `targeted_invalidation` and `invalidated_shot_ids`);
  - the cost estimate;
  - **`impact_sha256`** over all of that.
- **Confirm** requires the human session + CSRF and the shown `impact_sha256` + scope revision. Both are
  revalidated in the apply transaction.
- **Apply** is one transaction, in the §6 order:
  1. bump `content_revision` on the affected tracks;
  2. write the supersessions;
  3. **fence the affected work**: cancel queued and waiting V3 jobs **and queued continuations** through
     the transaction-owned helper (§7.4); invalidate unpublished submission authority (queued publication
     submissions);
  4. emit `amendment.applied`.

  **Published media is never touched.**

### 7.4 Cancellation (A3)

- **`JobService.cancel_in(tx, job_id, reason)`**: a transaction-owned variant of `cancel()`
  (`core/jobs.py:875`), so cancelling joins the amendment transaction.
- **The external operations of cancelled jobs** are left for the **authorised reconciliation path**
  (A0 §5.3 for LLM; the existing reconciliation for paid kinds). Exposure and receipts are retained.
- **Stale workers can't finish cancelled jobs**: their lease is revoked, and they stop under the lease
  guard.

## 8. Outbox and Dramabox Bot (A6; AC-17..19)

1. **Fan-out through the existing `OutboxDispatcher`** (AC-17):
   - each event is dispatched once to a list of registered handlers **in the dispatch transaction**;
   - the bot handler only inserts a **`notification_intents`** row, unique per `(event_id, channel)`, and
     records `event_consumptions(consumer='dramabox_bot')`;
   - irrelevant event types are ignored;
   - **events dispatched before the handler was registered are not notified** (no backfill);
   - the handler list is fixed at composition;
   - **the handler API receives the caller's transaction;**
   - **every production dispatcher registers the required consumers**, including A0's
     `llm_gateway_cancel`.
2. **A sender process** claims intents. Per attempt (AC-18):
   1. insert a uniquely numbered **`notification_attempts`** row (`CLAIMED`) and commit;
   2. call `sendMessage` (10 s timeout, outside any transaction);
   3. persist the outcome.
3. **Outcomes:**

| Telegram response | Outcome |
|-------------------|---------|
| `ok:true` with a `message_id` | `DELIVERED` |
| `429` with `retry_after` | `NOT_SENT`; retry at that time |
| Other 4xx | `FAILED_PERMANENT`; dead letter |
| 5xx, timeout, malformed response, or a `CLAIMED` attempt found unfinished at recovery | **`AMBIGUOUS`** |

   - After an ambiguous attempt, **one** retry is allowed, flagged `possible_duplicate`. That retry is
     durable and counted globally per intent.
   - Then the intent stops visibly (`DEAD_LETTER`, shown on Home).
   - Backoff timestamps are persisted. **The sender never sleeps inside a transaction.**
4. **Event names** (AC-19):
   - `gate.waiting`, `picks.waiting`, `review.ready`;
   - `release.published`, `release.failed`, `release.partial`;
   - `track.wait_started`, `track.blocked`;
   - **`budget.threshold_reached`** (integer `threshold_pct`, scope, revision; deduped per crossing);
   - `buffer.low`, `slo.below`, `summary.daily`.

   Each is registered with a payload schema.
5. **Messages** carry a deep link (configurable base URL) and **no approval actions**.
   - The token and chat ID come from FILE credentials.
   - The fake transport is the default. The live send needs the public-effect switch.

## 9. Scheduler and production composition (A6; AC-20, AC-21)

### 9.1 The scheduler

1. **Singleton** (AR-5):
   - the scheduler calls **`pg_try_advisory_lock(<namespaced key>)`** on a **dedicated connection**;
   - **false → skip the tick;**
   - release in `finally`;
   - if ownership is lost, stop starting new actions;
   - a crash releases the lock.
2. **Durable periods:** `scheduler_firings(trigger, period_key)` is unique.
   - Each period identity is **committed together with its database effects, or with durable effect
     intents**.
   - **Multi-transaction direct actions** (the GPU and worker sweeps, `scheduling/service.py:822–835`)
     record intents. Their external actions keep their own canonical operation and recovery identities.
   - **Unfinished effects stay recoverable** independently of the firing marker.
3. **Calendar triggers:** `CalendarTrigger(local_time, tz='Asia/Bangkok')`, with `period_key` = the local
   date. Used for the 09:00 summary and SLO checks.
4. **Catch-up:** after a first run or downtime, each trigger fires **at most its latest missed period**.
   There is no backlog storm.
5. **Definitions:**
   - the **SLO window** is a rolling 7 days (master §1);
   - **the buffer** = approved, unpublished, scheduled episodes ahead of today;
   - **health** = the last successful tick ≤ 3 × the interval, and errors per tick recorded.

### 9.2 Production composition

1. **Selection:** `--composition production` on **serve, worker, scheduler and sender**.
   `scheduling/__main__.py` no longer always builds the offline world for production.
2. **Startup dependencies are role-specific:**
   - DB + migrations at the expected head;
   - the object store (serve/worker);
   - the gateway (worker, if `LlmStep` is enabled);
   - scheduler freshness (serve readiness only; **never** a dependency of the scheduler itself).
3. **Fail closed:** a missing dependency → exit non-zero with the list.
4. **`provider_qualifications`:**
   - provider, configuration hash, evidence ref, `qualified_at`, **`expires_at`**;
   - required, together with the existing capability/rights/preset gates, for every enabled provider.
5. **A0's dispatch-time checks stay.**
6. **Staging is a separate composition** with separate configuration. Its guards and defaults are
   unchanged.

## 10. Build packages (in order; each with its own review and receipt; `make check` + V1 `make pilot` green at every gate)

**Prerequisites:** pin the accepted T031 merge and the A0 commits. Re-audit the migration tail; A0 = 0027,
phase A from 0028, and the numbers are **allocated per package in the A1 note**. **Applied migration bytes
are never edited.**

| Package | Builds | Gate (beyond the acceptance list in §11) | Design note |
|---------|--------|------------------------------------------|-------------|
| **A1** | Discriminator + `require_workflow` guards; gates, actions, revision notes, activations, the decision transaction and handler registry; tracks + extensions + the command table; `track_waits` view | Expanded A-T1..A-T6; migration upgrade on a populated V1 database; generated-contract drift check | **Critiqued first** |
| **A2** | Accounts, lookup, step budgets, hierarchy serialisation, cap amendments, forecasts, cost reconciliation, Costs data API | A-T9..A-T11 + lock/concurrency/shutdown tests | **Critiqued first** |
| **A3** | Fence, `cancel_in`, stale quarantine, cancelled-operation reconciliation, per-queue workers; consumes A0 runtime | A-T8, A-T12a, A-T18 | **Critiqued first** |
| **A4** | Supersession + `effective_approval` in every authority reader; coordinator, impact, Confirm | A-T12b + rollback/race/published-immutability tests | With the diff |
| **A5** | UI shell: typed progress, selected episode, Home/waiting/recovery/costs/amendment screens, polling | A-T7 with real routes and templates | With the diff |
| **A6a** | Outbox fan-out, intents/attempts/sender | A-T13 | With the diff |
| **A6b** | Scheduler: try-lock singleton, calendar triggers, periods + effect intents, catch-up | A-T14 | **Critiqued first** (AR-5) |
| **A6c** | Production compositions (all roles), qualifications, final shell pilot | A-T15..A-T17 + `make v3-pilot` | With the diff |

**Commands become active only when their dependencies ship** (AR-6):
- account-backed creation (`create_v3_season`, `create_v3_episodes`) in **A2**;
- cancellation and fencing integration (`cancel_*`, `rewind_for_amendment`) in **A3**.

Until then, earlier compositions return `NOT_AVAILABLE` for those commands, and their behavioural gates
move with activation.

**Routing:**
- GLM builds each package (`ai-route build -w`, its own worktree).
- Codex critiques the A1–A3 notes and reviews every package diff.
- One package at a time.

## 11. Acceptance

All of these are offline, use real runtime/composition with fakes, and include the critique's acceptance
gaps.

| ID | Proves |
|----|--------|
| A-T1 | Gate values; version-aware CHECKs; **V1 gate rows, actions and contract tests unchanged** |
| A-T2 (V3-AT-2) | The decision transaction, positive and negative: a foreign owner, a service credential, missing CSRF, the wrong gate/scope/hash/revision, a stale page, a callback failure rolling back, concurrent decisions, idempotent replay; `RevisionNotes` stored and targeted; production refuses test handlers |
| A-T3 | V3 Gate 2 → `NOT_AVAILABLE` for all three actions through JSON and HTML, with nothing recorded; no fallback to V1 |
| A-T4 | Every §3 command: allowed and refused sources, replay, events; unavailable later-phase edges |
| A-T5 | `require_workflow` refuses V3 rows on every inventoried legacy entry point (selectors, services, handlers, replayed jobs); the version is immutable; re-parenting is refused |
| A-T6 | `track_waits` derivation for concurrent waits, terminal failure, acknowledgement and resume; V3 human waits enforced at gate/pick activation and lease admission, heartbeat, adoption/transfer and janitor cause |
| A-T7 (V3-AT-1; R-11.2..11.5) | Typed `TabVector` for every combination; selected episode; open vs unopened gates; status precedence; one primary action per tab; unavailable phases; polling without overlap, with a visible recovery from a failure |
| A-T8 | A0 runtime consumed correctly; per-queue processes: a 60 s production handler doesn't delay publication |
| A-T9 (V3-AT-21) | Unit/step/child/season admission; **setup inside the season envelope (10 episodes + $30 setup ≤ $100)**; **a setup mutation racing STORY LOCK attachment is serialised by the mutex**; setup before approval refused; setup never touches episode accounts; amendment wakeup; direct-SQL amendment refused; V1 accounts can't be amended |
| A-T10 (V3-AT-21) | Concurrent workers on separate connections: reserve vs amendment vs settlement vs release vs late billing; expired holds; no cap exceeded at any level; a truthful overrun blocks further work; **shutdown proceeds with exhausted caps** |
| A-T11 (V3-AT-13) | Exactly-once per canonical receipt including multi-receipt operations; accrual → settlement replacement; late adjustment; setup counted once; unknown exposure retained; cash/accrued/reserved/attribution/estimate/quota kept separate |
| A-T12a | Fence: a race between an amendment and a mutation under the locks; intermediate writes; season-scope work; stale results quarantined; cancelled-operation reconciliation |
| A-T12b (R-12.6) | The supersession reader in every authority path; queued publication invalidated; Confirm revalidation (stale impact refused); published media untouched; rollback on failure |
| A-T13 (V3-AT-16; R-11.6) | Crash before send, after send and before outcome persistence; concurrent senders; restart during an ambiguous retry and during backoff; dead letter; pre-registration events not sent; no approval path |
| A-T14 | Scheduler: concurrent ticks → one runs, **the other skips without blocking**; lost ownership stops new actions; a multi-transaction sweep's unfinished effects stay recoverable; crash replay of a direct action → no-op; calendar 09:00 Bangkok; catch-up fires only the latest missed period |
| A-T15 | Each production role fails closed per dependency; expired qualification refused; the scheduler starts without its own health; staging is unchanged |
| A-T16 | Migrations 0028+ apply on a populated V1 database; every new table is guarded and in the catalog; applied migrations unchanged |
| A-T17 | `make check` + V1 `make pilot` green; `make v3-pilot` runs the shell end to end with test handlers |
| A-T18 (V3-AT-20) | A generic paid unit through `ProviderOperation` with a crash at each intent/submit/result/receipt boundary; a stable request identity; UNKNOWN without an external ID; cancel plus a late success; no exposure release; no blind resubmit |

## 12. Finding → resolution

| Finding | Resolved in |
|---------|-------------|
| AC-1 | §1, §2.2–2.3 |
| AC-2 | §2.3–2.4 |
| AC-3 | §2.6 |
| AC-4 | §2.7 |
| AC-5 | §1 |
| AC-6 | §1 (no `SEASON_APPROVED` pin), §3 |
| AC-7 | §3 (derived waits) |
| AC-8 | §5.3, §6 |
| AC-9 | §3, A-T6 (wait checks at activation and lease admission); A1 note |
| AC-10 | §4, §5.1 |
| AC-11 | §5.4 |
| AC-12 | §5.3 |
| AC-13 | §5.1, §5.2, §5.5 |
| AC-14 | §5.6 |
| AC-15 | §3 (`content_revision` on both scopes), §7.1 |
| AC-16 | §7.2–7.4 |
| AC-17 | §8.1 |
| AC-18 | §8.2–8.3 |
| AC-19 | §8.4 |
| AC-20 | §9.1 |
| AC-21 | §9.2 |
| AC-22 | §2.5, A5 note, A-T7 |
| AC-23 | §1, §4, §10 |
| AR-1 | §5.1 (setup inside the season envelope), §5.5 |
| AR-2 | §5.1 (season budget mutex, the atomic STORY LOCK attach), §6 #7 |
| AR-3 | §2.2 |
| AR-4 | §3 (`work_scope`, `logical_work_id`, operation blockers, dismissals) |
| AR-5 | §9.1 |
| AR-6 | §10 (dependency-gated commands; A6 split into a/b/c) |

## 13. Requirement trace

| Requirement | Section |
|-------------|---------|
| R-11.2 (stepper) | §3, A5 |
| R-11.3 (episodes board) | A5 |
| R-11.4 (waiting for you) | §2.5, §3 |
| R-11.5 (live progress + costs) | §5.6, A5 |
| R-11.6 (bot) | §8 |
| R-12.6 (amendment/invalidation) | §7 |
| R-12.7 (budget) | §5 |
