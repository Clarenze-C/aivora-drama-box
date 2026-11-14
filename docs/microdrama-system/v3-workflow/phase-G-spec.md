# Phase G: live qualification — production composition, composed restore, all-gate composition, the LIVE pilot (v0.1 DRAFT)

Status: **v0.1 DRAFT**, 14 Nov 2026, GLM (weekend runbook). Goldfish review + Codex critique follow. Binding
inputs: `SPEC-v3.md` v0.4.6 (§3.1, §3.3, §9.4, §10.1–§10.6, §11, §12.5→§10.6, §15.1–§15.2, §16.1–§16.3),
`DECISIONS.md` (the T031 lineage rows incl. the $8 envelope conventions, 12 Nov; the Dramabox Bot rows,
11 Nov), [phase-A0-spec.md](phase-A0-spec.md) v0.4, [phase-A-spec.md](phase-A-spec.md) v0.3,
[A1-design-note.md](A1-design-note.md) v1.3, accepted **B v0.6 / C v0.4.1 / E v0.4**,
[phase-F-spec.md](phase-F-spec.md) v0.4 (round-2 rulings applied, Opus re-check queued), and the T031
run-readiness spec v0.3 ([../T031-run-readiness-spec.md](../T031-run-readiness-spec.md), cited "T031-R5"):
G's LIVE pilot inherits its authorization, metering, verification and admission discipline. **No phase-D
spec exists at this draft** (verified 14 Nov; the runbook's draft queue is C, F, E, G, D — FM §7): every
D-dependent obligation is stated as a prerequisite that D's spec pins when it lands (E's ED5 pattern).
Precedence: `DECISIONS.md` > `REQUIREMENTS.md` > SPEC-v3 v0.4.6 > accepted phase specs > this draft;
conflicts are open questions (§14), never silent. Code facts cite today's tree (`feat/microdrama-m0-m4`)
as `FM §n` ([g-factmap.md](g-factmap.md)) or `file:line`; unverifiable claims are `UNVERIFIED`. Path
shorthand `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, `X/` = `microdrama/tests/`
(the C/E/F convention). Migration numbers here are symbolic `G-1…`; real numbers are allocated in the G1
note after re-auditing the tail (main ends at 0025; the A-line allocates 0027–0035, B from 0036 — FM §7
gap 13). **Applied migration bytes are never edited.**

**G owns** (SPEC-v3.md:884, :936): V3-AT-14, V3-AT-17 (LIVE), V3-AT-32, **V3-AT-34**, the **live half** of
V3-AT-28 (C §0 owns the offline half), and LIVE §16.3; R-11.1, R-12.10, R-12.11, R-12.13
(REQUIREMENTS.md:169, 189–190; R-12.13's preamble row, :24–27).

---

## 0. Scope

**Problem.** After A0–F, every phase is accepted offline and nothing is live: staging serves
`OFFLINE_MOCK` only (`microdrama/evidence/T046.md:7-9`, FM §7 gap 4); the production composition is A6c's
skeleton with no qualified providers; no composed restore proves DB + objects resume without duplicate
effects (FM §5); no test crosses all six gates (FM §2); `dramabox-llm` exists only in unmerged worktrees
with no production pause wiring (FM §3); the pilot profile, `PILOT-REPORT.md` and every non-LLM quota
surface are absent (FM §4); throughput has no live measurement path beyond F's offline counters
(F §9; FM §6).

**Phase G builds the qualification layer, not new pipeline machinery:**

1. **Production composition completion (§10.6; R-12.10, R-12.11):** per-provider live switches,
   qualifications, fail-closed startup, worker CPU discipline, domain activation (R-11.1).
2. **Off-pace pause + bot alert (V3-AT-14):** what "off pace" reads, the pause, the alert, the
   no-fallback proof.
3. **Composed restore (V3-AT-32):** backup, restore, resume of scheduler/outbox/jobs with no duplicate
   effects; notification ambiguity documented honestly.
4. **All-gate composition test (V3-AT-34):** one season through every gate with all real handlers,
   offline, and what it proves that per-phase tests cannot.
5. **The LIVE pilot (V3-AT-17; §11, §16.3; R-12.13):** P0/P1/P2 in an isolated pilot profile under the
   T031 discipline; the `PILOT-REPORT.md` generator and sign-off flow.
6. **Cross-system lock, live half (V3-AT-28's live arm):** the live ARISA/Drama test procedure — G owns
   the procedure, never the lock (C §5 owns the mechanism).
7. **Live throughput measurement (§9.4/MA11):** reads F-6; G adds no counter.

**Not in G:** any new pipeline phase logic, adapter implementation (C/D/F own adapters; G qualifies and
switches them), the lock mechanism (C3), platform qualification itself (T032), publishing transports (F),
ARISA-side lock adoption (the ARISA owner, coordinated per master §10.2), API/compatible LLM adapters
(O-5, post-pilot), and **any autonomous spend** — every live or paid step stays operator-gated (§7);
G defines scaffolding, never executes money.

---

## 1. Binding decisions

1. **G adds no queue lane, no job type, no `DeferReason`, no `GateType`, no state machine** (master §10.0
   taken to its conclusion: the pilot and the live system run the existing job families through the
   existing compositions). G's additions are records (§2), wiring (§3–§4), procedures and tests (§5–§8).
2. **Records over schema — exactly one migration.** G's durable state is: operational documents in one
   new store (`G-1`, §2); A6c's `provider_qualifications` rows (phase-A §9.2.4) for per-provider
   evidence; existing metering tables (`charges`, `cost_allocations`, `llm_invocations`,
   `quota_observations`, `pod_usage_intervals`, F's `release_throughput_observations`) for everything
   measured. No new quota table: LLM quota is A0's `quota_observations` (the master's intent, §10.0);
   non-LLM constraints are either money (charges), throughput (pilot documents, §7), or operator
   attestation (Botnoi points — O-11 lineage). Rejected: a per-record table family and a second quota
   table (§16).
3. **The pilot is the flow, not a fixture.** P0–P2 drive one real V3 season per pilot run through the
   real commands and gates, in an **isolated pilot profile** (master §11): a dedicated compose project
   with its own DB and object volumes (the T046 drill's fresh-project pattern, `drill.sh:121-141`),
   running the same composition factory as production with per-provider switches enabled one leg at a
   time. Runtime mode is `PAID_BENCHMARK` for paid legs and `CONTROLLED_ACCOUNT_TEST` for live
   publication legs (`md_runtime_mode`, M/0008:65-95); `PRODUCTION` is entered only at domain activation
   (§3.5), never silently.
4. **Every live/paid step is operator-gated by a signed authorization** (T031-R5 §7's convention):
   per-phase authorization documents binding the phase plan hash + quote hash + envelope, signed by the
   operator (the file-byte sha256 is the binding — T031-R5 §3 R5d). The pilot runner refuses any live
   leg without the recorded authorization; envelopes are enforced by A2's accounts (hard stop, master
   §12.3), so exposure can never exceed the operator-approved cap.
5. **Screen/full admission discipline is inherited from T031** (T031-benchmark-packet.md:117, 147-148):
   **P1 is the pilot's screen** (one full episode); **P2 admits only after P1's durable quality PASS**
   (the §16.3 thresholds operator-signed) **and verification/billing clear** (the T031-R5 §3 R5f
   per-acquisition pattern: nothing pending, no unresolved effects). A FAIL at screen is terminal for
   the pilot run and routes to the contingency decisions (§7).
6. **"Off pace" reads exactly as A0's admission does** (A0 §3.1/§3.4): the `dramabox-llm` role refuses
   pre-launch with `PACE_WEEK` when the Pro week pace is below `min_week_bp_per_day_left`
   (800 bp/day left; `retry_at` = the week reset), `QUOTA_5H`/`CONCURRENCY` for the window/slot
   (retry at the reset / +5 min), and `QUOTA_UNREADABLE` when quota cannot be read (+10 min — A0
   §3.4; the role's live-merge status is FM §3's). `LlmStep` maps these to deferrals (A0 §5.1); G adds only the
   production-level semantics (§4): **per-window refusals defer per job with retry times; an unreadable
   quota pauses production at route level; both raise one bot alert per pause episode.**
7. **No silent provider switch is structural, not vigilance:** before O-5 the composition has exactly
   one live LLM route (`MICRODRAMA_LLM_ROUTE=subscription`); the API/OpenAI-compatible adapters are
   interface + fakes only (A0 §5.8) and the legacy `LLMProvider` path refuses the subscription route
   (A0 §5.5.6). The AT-14 proof asserts there is nothing to switch to (G-T2).
8. **Restore proof is operational, and the proof state is unclean on purpose.** The composed-restore
   drill backs up a world containing in-flight work (a submitted-but-unsettled provider operation, a
   `CLAIMED` notification attempt, a pending scheduler period), restores DB + objects into a fresh
   project, and then resumes scheduler, workers and sender — proving no duplicate effects from the
   unclean state, not from a drained one (the T046 drill drains *before* backup, `drill.sh:110-113`;
   FM §5).
9. **AT-34 uses the normal composition with fake providers and all real handlers** — no test gate
   handlers (`validate_for_production()` refuses them, A1 note §5): the test's point is that the real
   handler registry is complete and mutually consistent. Its run record is a **committed evidence
   artifact** (`microdrama/evidence/`), not a DB row — tests run against ephemeral databases (the
   operational records of §2 are the DB documents).
10. **LIVE qualification is claimed per destination** (master §16.2): `LiveClaimV3` per destination;
    destinations held by T032 stay `HELD` and are excluded from the claim (§7.6).
11. **Throughput reads F-6 only** (F §9: "the live measurement is G's"): closed, non-overlapping
    intervals; complete-interval reads; derived rolling aggregates; buffer per F §6.3. G adds no
    counter and no second window definition (FM §6: none exists today, and G keeps it that way).
12. **Heavy runs obey the workspace CPU discipline:** the all-gates target, the pilot profile's
    edit/render work and the restore drill run under `systemd-run -p CPUQuota=45%` where they load the
    host (the E §3 note's composition rule, made G's to ship).
13. **R-12.13's "metered API keys, never the team's subscriptions" is superseded for the pilot** by
    V3C-1 (master §1 rule 3: the operator's subscription-first instruction of 11 Nov; REQUIREMENTS
    preamble :26-27 loses on precedence). The full-season provider decision is the operator's after the
    report (O-5) — G's report is the evidence for exactly that decision.
14. **The bot token is rotated before go-live** (master §3.3; DECISIONS 11 Nov: the token was pasted in
    chat): rotation is a hard item on the domain-activation checklist (§3.5), recorded by reference.

---

## 2. Records (contract package, guardian-owned bump; one symbolic migration `G-1`)

Documents live in one new append-only, versioned, hash-sealed store **`v3_ops_documents`** (`G-1`),
mirroring B/C/E/F's stores (F-1's row is the template): PK `(contract_type, record_id, version)`, one
`current` row per record, hash re-verified on read, `contract_type` allowlist CHECK, standard guards (no
delete, no truncate, integer-only numbers). `record_id = uuid5(OPS_V3_NS, "<type>:<key>")`. No other
migration; every other G surface is an existing table or a file (decision 2).

| Migration | Object | Decisive columns / rules |
|---|---|---|
| `G-1` | **`v3_ops_documents`** | the ops document store above; guarded |

**Documents in `v3_ops_documents`:**

| Record | Key | Content |
|---|---|---|
| `PilotRunV3` | `pilot:<pilot_season_id>` | the pilot campaign for one real season: profile + runtime mode; envelope refs (the setup-budget approval event, episode caps); phases P0/P1/P2 — each with `state` (`PENDING`/`RUNNING`/`SCREEN_REVIEW`/`PASS`/`FAIL`/`ABORTED`), sub-phase (`screen`/`full` where applicable), the authorization refs (document sha256s only), the measured price/throughput landing refs, per-destination claim refs, the report reference + its sha256, and the §16.3 threshold sign-off refs |
| `LiveClaimV3` | `live-claim:<destination>` | destination (`YOUTUBE`\|`TIKTOK`\|`FACEBOOK`); `state` (`QUALIFIED` \| `HELD`); the T032 qualification refs; verified-post evidence refs (slot identities + verification records); the observation window; a `HELD` row names its blocking capability |
| `RestoreProofV3` | `restore:<backup_set_id>` | the restore point (DB dump sha256, objects archive sha256, migration head, source runtime mode, timestamp); the procedure run (fresh project id, resume steps performed); per-check evidence refs (scheduler catch-up, job resume/reconcile, outbox drain, publication dedupe — §5); the honest ambiguity statement (§5.4); verdict |
| `ProductionCompositionV3` | `composition:<config_hash>` | the qualified production composition: the composition configuration hash; per-provider qualification row refs (`provider_qualifications`); the current `RestoreProofV3` ref; scheduler health evidence; the bot token rotation ref; the operator's dated activation authorisation; the operator-created DNS record ref; `state` (`QUALIFIED`/`ACTIVATED`) |

**Files, not rows:** the all-gate composition run record (`microdrama/evidence/v3-allgates-<date>.md`,
decision 9), the AT-28 live evidence (`microdrama/evidence/at28-live-<date>.md`, §8), the T031-lineage
per-phase pilot evidence (`microdrama/evidence/pilot/`), and **`PILOT-REPORT.md`** at
`docs/microdrama-system/v3-workflow/PILOT-REPORT.md` — generated as a DRAFT by the §7.5 generator and
signed by the operator in a commit that records the report's sha256.

### 2.1 G contract crossings (the C-B1 pattern, C §2.2)

| # | Delta | Contract touched | Mechanism |
|---|---|---|---|
| GD1 | Schedule `g.quota_pause` (60 s interval) | A6b's schedule registry (phase-A §9.1; F added two entries the same way) | G-owned registration in G2's wiring; its durable period identity (`scheduler_firings`) deduplicates the pause-edge evaluation across ticks and restarts |
| GD2 | `track.wait_started` admits a **scope-level, jobless variant** (payload: season, `track='production'`, cause `QUOTA_UNREADABLE` \| `PACE_WEEK`, `retry_at`, `edges: rising`) | A6a's event registry and payload schemas (phase-A §8.4) | requested as an A-side register entry — this row is the note; A's owner admits the payload variant (master §3.3's "quota wait" event at production scope). No new event name; per-job waits keep A's per-job shape |

**Standing rule (C-B1 for G):** any further G identifier crossing an A–F enforced contract joins this
register before the G1 note is accepted.

---

## 3. Production composition completion and domain activation (§10.6; R-11.1, R-12.10, R-12.11)

### 3.1 What "completed" means

A6c (phase-A §9.2) built the skeleton: role selection (`--composition production`), role-specific
startup dependencies, fail-closed exits, `provider_qualifications`, and A0's dispatch-time checks stay.
**G completes it in place — no second composition entry point:**

- **Per-provider completion checks, at startup and dispatch** (the C §5 predicate generalized, master
  §1 rule 5): a provider is live-enabled only when *all* hold — the per-provider switch (default
  **off**), a current `provider_qualifications` row (configuration hash, evidence ref, unexpired), the
  applicable rights/capability records, and (paid kinds) a known price/quote. Any missing piece keeps
  the provider disabled — never zero-priced (C §1.7's rule).
  - **LLM:** gateway health OK with the expected policy identity (A0 §5.7), `dramabox-llm` qualified
    per A0 §7's live qualification (`A0-LIVE-REPORT.md` current, policy identity matching).
  - **Image:** C's predicate plus the cross-system lock's pinned-inode qualification row on the real
    mount topology (C §5; §8 here).
  - **Render:** the T031 qualification record and `feat/t031-fix3` merged (master §4.6 N36), the
    production native-render adapter (D's contract — prerequisite pinned by D's spec).
  - **SFX / music:** C8's qualified routes and prices.
  - **Publishing / analytics:** per-destination capability records flipped by T032 evidence (F §7.3);
    T032-held destinations hold slots, never fail them.
- **Worker CPU discipline:** the deployment units for worker/scheduler/sender run under the workspace
  `CPUQuota` (decision 12) — shipped as tested files the operator installs (the A0 §4.1 pattern).
- **Mode honesty:** the production composition refuses to start in `OFFLINE_MOCK` (staging is the mock
  composition and stays unchanged, phase-A §9.2.6); the pilot profile runs `PAID_BENCHMARK` /
  `CONTROLLED_ACCOUNT_TEST` per leg (decision 3).

### 3.2 R-12.11's split, stated plainly

R-12.11 ("live providers still to wire and qualify") is *wired* by C (image, SFX, music), D (render, clip
QA), F (publishing), A0 (LLM), T032 (platforms); **G qualifies and switches them**, and owns only the
qualification procedure, the records and the composition-level proof that the switches fail closed. G
builds no adapter (§16 rejects that reading of R-12.11).

### 3.3 Backup coverage (R-12.10)

The drill's backup step (pg_dump of postgres + tar of the object-store volume, `drill.sh:115-119`)
covers provenance rows too (they live in the DB — `asset_lineage`, `rights_registry`, `charges.receipt`;
FM §1). G ships the backup script **timer-ready** (a systemd timer unit, operator-installed; the
DOMAIN-RUNBOOK.md:33-35 nightly step remains the operator's restic decision — O-G2). Every backup writes
its `RestoreProofV3` point fields at creation; the §5 proof completes the record.

### 3.4 Final qualification

The `ProductionCompositionV3` record is G's **final qualification** artifact: it binds the composition
configuration hash, every enabled provider's qualification row, the scheduler singleton's health
evidence (A6b), and the current `RestoreProofV3`. It is written by the qualification procedure (G5) and
is the input to domain activation.

### 3.5 Domain activation (R-11.1; master §3.1)

`authorize_domain_activation` (an operator command, §10) is refused unless **all** of: a current
`ProductionCompositionV3` (`QUALIFIED`); a proven restore (a `RestoreProofV3` verdict PASS, taken within
a config-owned freshness window, default 7 days — master §3.1 "a proven restore before domain
activation"); the scheduler service healthy; **the bot token rotated** (decision 14) with the rotation
recorded by reference; the operator's dated authorisation (a DECISIONS entry or signed file); and the
operator-created DNS record referenced (D5: DNS, TLS and deploy are operator-authorised; the
DOMAIN-RUNBOOK stays the deploy procedure). The record flips to `ACTIVATED`; Traefik/TLS steps remain
the runbook's, executed by the operator.

---

## 4. `dramabox-llm` off-pace: pause and alert (V3-AT-14)

**The pause is derived, never stored** (AR-4): `llm_route_paused(season)` is true while (a) the latest
quota observation for the route is unreadable, or (b) any active `PACE_WEEK` deferral exists (the week
reset is days away — refusal with a retry time is, in production effect, a pause; master
SPEC-v3.md:665-667 "Persisted refusals carry retry times; an unreadable quota pauses production /
No silent provider fallback").

- **Route-level pause (QUOTA_UNREADABLE):** `LlmStep`'s dispatch gate (A0 §5.7) treats unreadable quota
  as a failed composition check — every LLM-dependent job (B planning, D directing, F prefill) defers
  `WAITING_QUOTA` and no new LLM dispatch admits until quota is readable again. Non-LLM work (render of
  already-directed shots, edit, publish) continues — waits are scope-keyed and never suspend unrelated
  approved releases (master §2.2).
- **Per-job waits (QUOTA_5H, CONCURRENCY):** existing behaviour (A0 §5.1 deferral with `retry_at`),
  projected `WAITING_QUOTA` through `track_waits` (A1 note §2.4) — no scope alert.
- **The alert:** the `g.quota_pause` schedule (GD1) evaluates the predicate each tick; on a **rising
  edge** it emits one scope-level `track.wait_started` (GD2) → the Dramabox Bot's quota-wait alert with
  the cause, the pace numbers, and `retry_at`. One alert per pause episode (the firing identity
  deduplicates; no per-job spam); recovery is visible on Home and in the 09:00 summary (A §8.4).
- **No fallback:** decision 7 — the proof (G-T2) asserts the composition exposes exactly one live LLM
  route and that enabling any API adapter is refused (they are not live-capable before O-5).
- **Pilot pacing input:** pause episodes, counts and window pacing are pilot-report content (N12,
  master §11) — §7.4.

---

## 5. Composed restore (V3-AT-32; §12.5 → §10.6)

### 5.1 The procedure (extends the T046 drill; the drill's steps stay)

1. **Seed an unclean world** (test profile): one provider operation `SUBMITTED` (external id unknown to
   the local row), one notification intent with an unfinished `CLAIMED` attempt (crash mid-send), one
   calendar trigger whose period has fired on the source but whose marker is uncommitted, plus ordinary
   settled work. Backup: `pg_dump` + objects tar (drill.sh:115-119) → the point fields of a
   `RestoreProofV3`.
2. **Restore** into a fresh compose project (drill.sh:121-141: `pg_restore` with `ON_ERROR_STOP`,
   objects extracted, app up, health + owner login + page-read).
3. **Resume, in order:** the scheduler singleton starts (catch-up fires **at most the latest missed
   period** per trigger — phase-A §9.1.4; `S/scheduling/service.py:18-21`); workers start (the
   janitor/reconciler path resolves the in-flight operation via its client token —
   `S/contracts/providers.py:200` "NOT_FOUND = safe to resubmit"; adopt-by-external-id otherwise); the
   sender re-claims the `CLAIMED` intent (A §8.3's `AMBIGUOUS` path: one retry, flagged
   `possible_duplicate`, then dead letter).
4. **Assert and record:** §5.2's checks; the `RestoreProofV3` verdict.

### 5.2 What must hold (the AT-32 assertions)

- **Jobs:** the interrupted operation is reconciled, never blindly resubmitted; the fake provider
  records **zero duplicate submits**; a `NOT_FOUND` outcome re-arms exactly once (the existing
  reconcile semantics, FM §1).
- **Scheduler:** no duplicated firings or effects across the restore boundary (`scheduler_firings`
  uniqueness; "missing state can never duplicate an effect because the semantic keys dedupe",
  `S/scheduling/service.py:18-21`, `M/0017_schedule_state.sql:2-3`).
- **Outbox/notifications:** delivery is at-least-once with consumer dedupe (`S/core/events.py:5-7`);
  the ambiguous send is retried at most once and flagged (A §8.3).
- **Publication:** no post is duplicated — slot dedupe keys and client tokens survive the dump; a post
  row is never re-created (F §1.11's invariants, restored with the DB).

### 5.3 Why the unclean state is the honest test

`pg_dump` is MVCC-consistent per snapshot but the live system is multi-transaction: a submit committed
and its local persistence not yet written is exactly the crash window the job system is built for
(master §1 hard rule 1). Draining before backup (the drill's step 5) hides that window; the proof
restores *into* it.

### 5.4 Notification ambiguity, documented honestly (the AT-32 wording)

The `RestoreProofV3` carries this statement, verified against the run: **money effects are exactly-once
(ProviderOperation identity + reconcile-before-resubmit); publication is exactly-once (slot identities +
adopt-by-external-id); notifications are at-least-once — a send ambiguous at backup time may be
delivered twice after restore, the duplicate flagged `possible_duplicate` (A §8.3), and a dead-lettered
intent is shown on Home.** No claim of exactly-once notification is made anywhere (master §19.2
superseded the v0.1 "exactly once" wording).

---

## 6. All-gate composition test (V3-AT-34)

**One season, every gate, all real handlers, fake providers** — a `make v3-allgates` target (not in
every `make check` run: CPU — O-G6) executing an integration suite against real PostgreSQL:

1. **Fixture season:** intake (24 episodes — B's band is 20–30, no fixture shortcut), LOCK approve;
   bible + 24 packs through A0's fake gateway (B's scenario scripts); STORY LOCK approve; picks + votes
   through C's fake image provider; CAST LOCK approve.
2. **Produced subset:** episodes 1–5 + the teaser through D (fake render adapter), E (real ffmpeg on
   small fixtures — the E seam, not a mock), F (metadata via fake LLM; Gate 2 ×5; teaser cut;
   `TEASER_FINAL`; calendar; LAUNCH approve).
3. **Release:** compressed calendar; release admission + fake publish + verification per qualified
   destination; buffer/throughput counters tick (F-6).
4. **Cross-phase stress:** one amendment through A4 (an asset re-roll pre-publication) — fence bumps,
   stale results quarantined, dependent rebuilds; one reschedule (F §8.1) — date-bearing content
   rebuilt, published media untouched; a stale-hash decision refused at each gate.
5. **Record:** the evidence artifact (decision 9): parameters, fixture hashes, per-gate bindings,
   timings, verdict — committed.

**What it proves that per-phase tests don't:** (a) the **complete real handler registry** — no
`NOT_AVAILABLE` anywhere in the normal composition (A §2.7's refusal is per-unshipped-phase; after F
nothing may refuse); (b) **authority chains across phase boundaries** — STORY→CAST→Gate-2→TEASER→LAUNCH
bindings and hashes are mutually consistent in one lifecycle; (c) **the fence and revision discipline
propagate across every phase** in a single season (amendment visibility end to end); (d) **dispatch
requires both authorities** (F §7.1) at the composition level; (e) the **track model runs IDEA →
`PUBLISHED_VERIFIED` → `COMPLETE` without dead ends**; (f) one composition object graph serves every
phase — the wiring the pilot and production will run. It does **not** duplicate F-T8's 30-episode
release storm (V3-AT-29 stays F's; §6's release pass exercises the gates, not the failure catalogue).

**Bound:** target ≤ 15 min wall-clock under the CPU quota (a target, not a promise — the T031-R5 §4
honesty convention; the fixture pack sizes are tuned in G4 to keep it true).

---

## 7. The LIVE pilot (V3-AT-17; §11; §16.3; R-12.13)

### 7.1 The pilot profile and the runner

`deployment/pilot/` (compose project, port 8094 — the drill's fresh-project pattern; volumes
`pilot-pg`/`pilot-objects`; same image; O-G1). A pilot CLI (`python -m microdrama.ops.pilot`) with
`prepare / authorize-check / status / report` subcommands — offline-testable, no network in tests. The
runner **drives** the flow (it does not bypass it: every step goes through the real commands and gates);
its live legs are refusal-first without the recorded authorization (decision 4).

### 7.2 P0 — planning, reduced cast, lock throughput (needs A0–C; master §11)

1. **Calibration batch (operator-authorized, bounded):** live Nano Banana through C's lock + fairness
   (prerequisite: C3 merged, ARISA-side adoption per master §10.2 — §8) — measures the **lock
   throughput (images/hour)** and the **real per-image price**; results land in `PilotRunV3` and feed
   C's forecast config (O-C7's defaults, re-measured — master §10.4: the measurement is
   operator-visible **before CAST generation starts**). Price bootstrap: O-G3 — the operator records a
   provisional rate-card quote; measured receipts replace it and the forecast recomputes.
2. **Full planning, steps 1–3:** 24 episodes through the real `dramabox-llm` subscription (Opus
   bible/architect/season critic; Sonnet translation — B §7.2, master §10.1 roles).
3. **Reduced step 4:** 2 characters, 2 locations, voices for both (Botnoi Studio manual upload — O-C1's
   decided intake), under the setup sub-budget (approved via A2 `approve_setup_budget` — the pilot
   envelope).
4. **N12 records:** planning wall-clock, quota-pause counts and window pacing from
   `llm_invocations`/`quota_observations` + scheduler firings.

### 7.3 P1 — one full episode, the screen (needs D accepted + T031 qualified; master §4.6 N36)

One episode end to end — directing (Sonnet via the gateway), render (the production native-render
adapter over the accepted T031 transport/recovery primitives), clip QA, edit, metadata, Gate 2 — plus
the **mixed-emotion exit check** (master §6 MA12: ≥80% of emotional/mixed-emotion shots reading
correctly, judged by the recorded Gate-2 human assessment; T031's S05/S06 lineage is the first
evidence). Below threshold: the **pre-agreed contingency** (split coverage at speech-safe boundaries)
needs an operator decision with its projected clip/cost impact — the pilot run goes `SCREEN_REVIEW` →
operator decision, not an automatic switch. P1 PASS is durable (operator-signed thresholds, §7.6) and
gates P2 (decision 5); billing/verification clear per the T031-R5 R5f pattern before P2 admission.

### 7.4 P2 — three more episodes, throughput vs SLO

Three further episodes; the release calendar runs **compressed** (operator-chosen dates) so F-6's closed
intervals capture the sustained rate and, where the schedule allows, the ≥2/day × 2-day catch-up window;
buffer readings per F §6.3. LIVE acceptance numbers: sustained ≥1.25 approved episodes/day, catch-up,
buffer ≥3 (alert <2), **at cost ≤ cap** read from A2's accounts (master §9.4, §16.3). Non-LLM quota
capture per decision 2: images (counts + throughput), GPU seconds (`pod_usage_intervals`), SFX/YuE2
(charges), Botnoi points (operator attestation).

### 7.5 `PILOT-REPORT.md` (master §11's contents, generated)

`pilot report` renders the DRAFT deterministically from the tables — measured vs forecast clearly
marked; cost per episode by provider (cash / allocation / estimate — never summed blindly, master §11);
quota per episode per provider; planning wall-clock, quota-pause counts, window pacing; throughput
(F-6); the §16.3 quality measures; the **frozen-workload LLM comparison** (k frozen workloads per role
run under both Opus and Sonnet, usage from `llm_invocations`; O-G5); per-destination live claims; a
recommendation for the operator's §11 decision (LLM plan, pace, season start). The operator signs by a
commit recording the report's sha256; threshold confirmations land in `PilotRunV3`.

### 7.6 Per-destination LIVE claims (§16.2)

Each destination gets a `LiveClaimV3`: `QUALIFIED` with T032 refs + verified posts from the pilot's
release legs, or `HELD` naming the blocking capability. Held destinations are excluded from every LIVE
claim; the report says so per destination (master §16.2 — the claim is never "all platforms" while one
is held).

---

## 8. Cross-system lock, live half (V3-AT-28's live arm)

G owns **only the live test procedure**; C §5 owns the mechanism (flock + pinned inode + recovery
admission + fairness; C-T6 proved the offline half on isolated mounts). Prerequisites, all checked
before stage 1: C3 merged and the lock's `provider_qualifications` row current on the **real mount
topology** (the parent-directory bind — a file-only bind is ineligible, C's PC5-2); **ARISA-side
adoption** evidence (the shared recovery-admission protocol and the submit-through-final-poll hold in
ARISA's code — today absent, FM §5; coordinated with the ARISA owner, master §10.2); the operator's
authorization for any live submission (§7 discipline; a mini-envelope bounds it — O-G4).

- **Stage 1 — dry choreography (zero provider calls):** with the ARISA owner's coordination window,
  both real containers acquire/release the **real canonical inode**
  (`/root/AIVORA/arisa/studio/sfw/vertex-generation.lock`, read-only, seconds-scale holds): each side
  observes the other's hold as
  exclusion; the kill-after-admission-before-submit recovery choreography (C-T6's template) runs on an
  **isolated copy** of the topology — the canonical inode is never swapped or replaced while generators
  may run (C §5's PC-7 rule), so the swap→typed-BLOCKED case is proven only on the copy.
- **Stage 2 — one live pair (operator-authorized):** one real ARISA generation and one Drama live image
  job, interleaved; assert mutual exclusion, the fairness bounds (≤8 images / ≤120 s per hold), no
  overlap of provider processes across a container restart. Evidence → `microdrama/evidence/
  at28-live-<date>.md` + the qualification row's evidence ref.

---

## 9. Live throughput reporting (§16.3 / MA11)

No new surface: the report reads F-6 (closed intervals; complete-interval only; rolling aggregates
derived — F §9) and A2's accounts for cost-to-date. The SLO breach alert is F's bot wiring (`slo.below`,
`buffer.low`); G's live operation simply runs it (FM §6: the counters and alerts are F9's offline
deliverables — G's obligation is the *live measurement* and the report's throughput section). §16.3's
final row — "Throughput ≥ the §9.4 SLO at cost ≤ cap" — is signed with the thresholds (§7.6).

---

## 10. G commands (A1 note §6 format) and schedules

| Command | Actor | Prerequisites | Effect | Events | Replay identity |
|---|---|---|---|---|---|
| `record_pilot_authorization(phase, doc_sha256s)` | Operator (human session + CSRF) | the signed authorization file exists; the phase is `PENDING` | binds the authorization to the `PilotRunV3` phase (unlocks that leg's runner gate) | `pilot.authorized` | idempotency key |
| `record_live_claim(destination, state, evidence)` | Operator | pilot release legs or T032 evidence exists | appends a `LiveClaimV3` version | `pilot.claim_recorded` | idempotency key |
| `confirm_live_thresholds(measures, adjustments)` | Operator | P1/P2 evidence present | records the §16.3 confirmations in `PilotRunV3`; feeds the report's sign-off block | `pilot.thresholds_confirmed` | idempotency key |
| `authorize_domain_activation(composition ref, restore ref, rotation ref, authorization ref, dns ref)` | Operator | §3.5's checklist all present | writes/updates `ProductionCompositionV3` → `ACTIVATED` | `ops.domain_activated` | idempotency key |
| `record_restore_proof` (drill-internal) | System | §5's procedure ran | writes the `RestoreProofV3` verdict | `ops.restore_proven` | the backup-set identity |

**Schedules G adds:** `g.quota_pause` (GD1; 60 s). **Jobs G adds:** none (decision 1).

---

## 11. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

Prerequisites: **A0–F accepted** (D's spec pending at this draft — its render/QA contracts are pinned
prerequisites, §7.3); T031 qualified with `feat/t031-fix3` merged for anything render-live (N36);
T032 records for any publication-live leg. Real migration numbers allocated in the G1 note from the
tail.

| Package | Builds | Gate | Design note |
|---|---|---|---|
| **G1** | `G-1` store + `OpsV3Store`; contracts bump (the four document types); the §2.1 crossing register delivered (GD1/GD2 requested) | G-T1 | **Critiqued first** (migrations + crossings) |
| **G2** | Off-pace pause: the derived predicate, `g.quota_pause`, the scope-level alert, Home surface; the no-fallback composition proof | G-T2 (V3-AT-14) | With the diff |
| **G3** | Composed restore: the drill extension (unclean seed, resume steps), `RestoreProofV3` writer, the ambiguity statement; the backup timer files | G-T3 (V3-AT-32) | **Critiqued first** (ops-critical) |
| **G4** | The all-gate composition suite + fixtures + `make v3-allgates` + the evidence writer | G-T4 (V3-AT-34) | With the diff |
| **G5** | Composition completion: per-provider completion checks, CPU-quota deployment units, the qualification procedure, `ProductionCompositionV3`, the activation checklist + command | G-T5 | With the diff |
| **G6** | Pilot scaffolding: the pilot profile, the runner CLI, authorization/envelope gates, the frozen-workload harness, the `PILOT-REPORT.md` generator | G-T6 | **Critiqued first** (money paths) |
| **G7** | Live procedures pack: the AT-28 live procedure (§8), the P0–P2 runbooks (dry-run modes), the live-claim and threshold flows | G-T7 | **Critiqued first** (money/locks) |

**Routing:** GLM builds each package (`ai-route build -w`); Codex critiques the G1/G3/G6/G7 notes and
reviews every diff; one package at a time. **All offline gates run under the workspace CPU quota.**

---

## 12. Acceptance (offline unless marked LIVE; real PostgreSQL for transaction tests; pytest
`--basetemp` under the session scratchpad)

| Test | Package | Proves |
|---|---|---|
| G-T1 | G1 | `G-1` applies on a populated V1+V2+V3 database; guards + catalog present; documents roundtrip hash-verified; applied migrations unchanged; generated contracts zero drift |
| **G-T2 (V3-AT-14)** | G2 | Through the production composition with A0's fake-gateway scenarios: `PACE_WEEK` refusal → LLM-dependent jobs defer `WAITING_QUOTA` with `retry_at` = the week reset; `QUOTA_UNREADABLE` → the route pause holds new dispatch and every LLM job defers; **the scope-level alert fires exactly once per pause episode** (rising edge; no spam across ticks/restarts — GD1's firing identity); per-job `QUOTA_5H` stays per-job; **exactly one live LLM route exists and enabling an API adapter is refused** (A0 §5.8); recovery resumes work; non-LLM tracks continue |
| **G-T3 (V3-AT-32)** | G3 | The §5 procedure on the unclean world: restore + resume with **zero duplicate submits** (fake provider counts), at most the latest missed period fired, the ambiguous notification retried once and flagged then dead-lettered or delivered, no duplicated publication; `RestoreProofV3` verdict PASS and its ambiguity statement matches the observed behaviour; a drained-world control run also passes |
| **G-T4 (V3-AT-34)** | G4 | The §6 suite: every gate approves through the real decision transaction; stale hash refused at each gate; the STORY→CAST→Gate-2→TEASER→LAUNCH chain consistent; dispatch requires both authorities; the amendment fences cross-phase work with stale quarantine; the reschedule rebuilds date-bearing content only; published media immutable; the five produced episodes
reach `PUBLISHED_VERIFIED` per destination and the season reaches `COMPLETE` with the unproduced
remainder closed out through F's `close_out_episode` (its first composed exercise); the evidence
artifact written; the runtime bound held |
| G-T5 | G5 | Fail-closed completion: each enabled provider missing switch/qualification/rights/price refuses startup or dispatch (typed); an expired qualification row refuses; the activation checklist refuses without the restore proof / scheduler health / rotation / authorisation / DNS refs; staging unchanged (`OFFLINE_MOCK` guards intact) |
| G-T6 | G6 | The runner refuses every live leg without the recorded authorization (hash-bound; a wrong sha refused); the envelope is the account hard-stop (a leg over the setup budget is refused); the report generator over a seeded pilot-shaped dataset produces every §11 section with measured-vs-forecast marked and per-provider quota lines (LLM/images/GPU/SFX/YuE2/Botnoi); the frozen-workload harness records both roles' usage; no test touches the network |
| G-T7 | G7 | The AT-28 dry choreography (isolated copy: exclusion, kill-after-admission recovery, swap→typed BLOCKED; real-inode holds coordinated in the runbook); the P0–P2 runbooks' dry-run modes execute end to end against fakes; a T032-held destination records `HELD` and is excluded from claims |
| G-T8 | all | `make check` + V1 `make pilot` green at every package gate; `make v3-allgates` green at G4 and before any live qualification |
| **LIVE** | execution | V3-AT-17 and §16.3 complete only through the operator-gated P0–P2 execution with evidence: pilots complete; `PILOT-REPORT.md` signed with measured per-episode cost and quota per provider; §16.3 thresholds confirmed; AT-28's live stage recorded; per-destination claims recorded. **G's packages never spend — these rows pass outside the build, by the operator's hand** |

---

## 13. Requirement trace

| R-ID / AT | Where |
|---|---|
| R-11.1 (domain, owner login, TLS) | §3.5, §10; G-T5 |
| R-12.10 (scheduler, backups, per-provider live switch) | §3.1, §3.3, §3.5; G-T3, G-T5 |
| R-12.11 (live providers wired and qualified) | §3.1–§3.2 (G qualifies; C/D/F/T032 wire); G-T5 |
| R-12.13 (cost/quota meter + pilot before pace) | §7 (superseded-for-pilot per V3C-1, §1.13); G-T6 |
| V3-AT-14 | §4; G-T2 |
| V3-AT-17 (LIVE) | §7; G-T6 + LIVE |
| V3-AT-32 | §5; G-T3 |
| V3-AT-34 | §6; G-T4 |
| V3-AT-28 (live half) | §8; G-T7 + LIVE |
| §16.3 / MA11 | §7.4, §9; LIVE |

---

## 14. Open questions (each with a recommendation)

| # | Question | Recommendation |
|---|---|---|
| O-G1 | Pilot profile topology: separate compose project + volumes vs a schema in the shared DB | **Separate compose project** (port 8094, own volumes, same image — the drill pattern); a shared-DB schema risks the operator's real data and weakens mode isolation |
| O-G2 | Nightly backup execution (the runbook's restic step is unexecuted — FM §1) | Ship the **timer-ready backup script + systemd unit** (operator-installed), proof per §5 on each timer window's set; restic inclusion stays the operator's separate decision |
| O-G3 | Image price bootstrap: C's forecast is BLOCKED on an unknown price (O-C4), but measuring requires spending | The operator records a **provisional rate-card quote** admitting the bounded calibration batch inside the envelope; measured receipts replace it and the forecast recomputes — the cap bounds exposure either way |
| O-G4 | AT-28 live-test scheduling risk (ARISA-side adoption is the long pole — FM §5) | Two stages (dry choreography, then **one** live pair), both operator-authorized; a mini-envelope bounds the live spend; the procedure declares adoption a hard prerequisite and escalates to the operator if lagging |
| O-G5 | Frozen-workload comparison size (subscription quota is the scarce resource) | **k=2 per role** (bible, architect, director, metadata), bounded `max_budget_microusd` per call (A0 §3.1) — enough for the §10.1 comparison without eating the pilot's window |
| O-G6 | Is the all-gate suite in `make check`? | **No** — a dedicated `make v3-allgates` target at gates and pre-live (CPU); a one-season smoke variant may join `make check` later if it stays <60 s |
| O-G7 | `PILOT-REPORT.md` location | `docs/microdrama-system/v3-workflow/PILOT-REPORT.md` (the master names it bare; beside the specs is where the §11 decision is read) |
| O-G8 | Does the pilot profile need the sender/bot live? | The bot sends to the operator's real chat with the **test-then-rotate** token (§3.5); recommend live sends during P1/P2 (the alert paths are part of what the pilot measures — pause episodes) with the rotation recorded before activation |

---

## 15. Risks and limits

| Risk | Limit / mitigation | Owner |
|---|---|---|
| Subscription quota exhausts mid-pilot (24×2 calls × roles through a max-concurrency-1 gateway) | the pause/alert path is *part of the pilot's evidence* (N12); window pacing reported; the operator paces or pauses between phases | Operator |
| Live image spend exceeds the envelope | the setup sub-budget is a hard stop (A2); the calibration batch is bounded; measured prices replace provisional ones | Operator (O-G3) |
| T032 delays keep destinations `HELD` | §16.2 per-destination claims by design — held destinations are excluded, never faked | T032 |
| ARISA-side lock adoption lags | AT-28's live stage is a hard-prerequisite procedure; the pilot's image legs stay disabled until adoption + qualification (master §10.2) | ARISA owner |
| The unclean-restore drill grows brittle with schema drift | G-T3 runs at every package gate; the drill is versioned with the composition | G3 builder |
| Host CPU contention (all-gates suite, pilot edit/render) | CPUQuota on every heavy run (decision 12); the suite's runtime bound is a gate | G builders |
| Pilot-profile drift from the production composition | both build from the one composition factory; the qualification record pins the config hash | G5 builder |

Master-level risks and their owners: master §18 (quota terms, throughput SLO, cap changes).

---

## 16. Alternatives rejected (one per major choice)

| Choice | Rejected alternative | Why rejected |
|---|---|---|
| One ops document store (`G-1`) | Per-record tables | mirrors B/C/E/F: one guard/hash/allowlist story; per-record tables duplicate the sealing machinery per type |
| Existing tables + documents for quota | A second (non-LLM) `QuotaObservation` table | LLM quota is A0's table (master §10.0's intent); image constraint is throughput; the rest is money (charges) or attestation — a second table would model nothing that exists |
| Generated `PILOT-REPORT.md` DRAFT + operator sign-off | A hand-written report | §11 demands measured numbers from five tables; hand-copying invites exactly the blind-summing §11 forbids |
| The pilot is the flow | A fixture-driven pilot | the pilot's product *is* evidence about the real flow (quota pauses, window pacing, lock throughput); fixtures cannot measure those |
| AT-34 with all real handlers + fake providers | Test gate handlers (the A-T17 idiom) | the composition's completeness is the thing AT-34 proves; test handlers would prove the shell only (A §2.7) |
| Jobless `track.wait_started` variant (GD2) | A new `production.paused` event name | master §3.3's event list is binding vocabulary; a scope-level "quota wait" is within it — extend the payload, not the name |
| Evidence file for the all-gates run record | A DB row | tests run against ephemeral databases; the durable record must survive them (the T031 evidence convention) |
| G qualifies C/D/F adapters | G builds/rebuilds the live adapters | R-12.11's wiring is phase-owned (C §5, D, F); a second adapter lineage would fork the fail-closed switches G exists to prove |
