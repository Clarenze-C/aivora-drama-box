# Phase G: live qualification — production composition, composed restore, all-gate composition, the LIVE pilot (v0.2 DRAFT)

Status: **v0.2 DRAFT**, 14 Nov 2026, GLM (weekend runbook). v0.1 → v0.2 applies the Goldfish rulings
([phase-g-goldfish-rulings.md](phase-g-goldfish-rulings.md) — all 61 ACCEPTED: the 19 Majors per each
one's Fix direction in
[phase-g-review/consolidated_review_report.md](phase-g-review/consolidated_review_report.md), the 42
nits as mechanical sweeps). Codex critique follows. Binding
inputs: `SPEC-v3.md` v0.4.6 (§3.1, §3.3, §9.4, §10.1–§10.6, §11, §12.5→§10.6, §15.1–§15.2, §16.1–§16.3),
`DECISIONS.md` (the T031 lineage rows incl. the $8 envelope conventions, 12 Nov; the Dramabox Bot rows,
11 Nov), [phase-A0-spec.md](phase-A0-spec.md) v0.4, [phase-A-spec.md](phase-A-spec.md) v0.3,
[A1-design-note.md](A1-design-note.md) v1.4, accepted **B v0.6**
([phase-b-recritique-rulings.md](phase-b-recritique-rulings.md)), **C v0.4.1** (round-3
APPROVE-WITH-CHANGES + PC6-1; [phase-c-recritique-rulings.md](phase-c-recritique-rulings.md)), **E
v0.4** ([phase-e-recritique-rulings.md](phase-e-recritique-rulings.md)) and
[phase-F-spec.md](phase-F-spec.md) v0.4 ([phase-f-recritique-rulings.md](phase-f-recritique-rulings.md))
— all four applied by GLM this weekend and all four carry the family's pending Opus re-check Mon (F's
header flags it; B, C and E state the same), and the T031
run-readiness spec v0.3 ([../T031-run-readiness-spec.md](../T031-run-readiness-spec.md), cited "T031-R5"):
G's LIVE pilot inherits its authorization, metering, verification and admission discipline. **No phase-D
spec exists at this draft** (verified 14 Nov; the weekend runbook's draft queue is C, F, E, G, D —
[WEEKEND-GLM-RUNBOOK.md](WEEKEND-GLM-RUNBOOK.md) Q7, D last): every
D-dependent obligation is stated as a prerequisite that D's spec pins when it lands (E's ED5 pattern).
Precedence: `DECISIONS.md` > `REQUIREMENTS.md` > SPEC-v3 v0.4.6 > accepted phase specs > this draft;
conflicts are open questions (§14), never silent. Code facts cite today's tree (`feat/microdrama-m0-m4`)
as `FM §n` ([g-factmap.md](g-factmap.md)) or `file:line`; unverifiable claims are `UNVERIFIED`. Path
shorthand `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, `X/` = `microdrama/tests/`
(the C/E/F convention); the staging drill is `microdrama/deployment/staging/drill.sh`, cited `drill.sh`
after this first use. Migration numbers here are symbolic `G-1…`; real numbers are allocated in the G1
note after re-auditing the tail (main ends at 0025, 0026 is unallocated, the A-line — the A0/A/A1/A2/A3/
A6 specs and notes — takes 0027–0035 and B starts at 0036; full bounds from
[phase-B-spec.md](phase-B-spec.md):213, beside FM §7 gap 13). **Applied migration bytes are never
edited.**

**Reference conventions.** "master" always means `SPEC-v3.md` v0.4.6, and a reference to it is always
written "master §n" — a bare "§n" is this document's own section. "Home" is the operator dashboard's
home page (master §3.3: waits, blocked, quota waits, today's releases, budget state), fed by A1's
`track_waits` view and alert machinery. "V1 `make pilot`" is the pre-V3 pilot suite target in
`microdrama/Makefile` (the family's regression gate); a "populated V1+V2+V3 database" is one migrated
through the full line with representative rows in each era's tables (the F-T1/G-T1 fixture).

**G owns** (SPEC-v3.md:884, :936): V3-AT-14, V3-AT-17 (LIVE), V3-AT-32, **V3-AT-34**, the **live half** of
V3-AT-28 (C §0 owns the offline half), and LIVE master §16.3; R-11.1, R-12.10, R-12.11, R-12.13
(REQUIREMENTS.md:169, 189–190; R-12.13's preamble row, :24–27).

---

## 0. Scope

**Problem.** After A0–F, every phase is accepted offline and nothing is live: staging serves
`OFFLINE_MOCK` only (`microdrama/evidence/T046.md:7-9`, FM §7 gap 4); the production composition is A6c's
skeleton with no qualified providers; no composed restore proves DB + objects resume without duplicate
effects (FM §1; FM §7 gap 5); no test crosses all six gates (FM §2); `dramabox-llm` exists only in unmerged
worktrees with no production pause wiring (FM §3); the pilot profile, `PILOT-REPORT.md` and every non-LLM quota
surface are absent (FM §4); throughput has no live measurement path beyond F's offline counters
(F §9; FM §6).

**Phase G builds the qualification layer, not new pipeline machinery:**

1. **Production composition completion (master §10.6; R-12.10, R-12.11):** per-provider live switches,
   qualifications, fail-closed startup, worker CPU discipline, domain activation (R-11.1).
2. **Off-pace pause + bot alert (V3-AT-14):** what "off pace" reads, the pause, the alert, the
   no-fallback proof.
3. **Composed restore (V3-AT-32):** backup, restore, resume of scheduler/outbox/jobs with no duplicate
   effects; notification ambiguity documented honestly.
4. **All-gate composition test (V3-AT-34):** one season through every gate with all real handlers,
   offline, and what it proves that per-phase tests cannot.
5. **The LIVE pilot (V3-AT-17; master §11, master §16.3; R-12.13):** P0/P1/P2 in an isolated pilot
   profile under the T031 discipline; the `PILOT-REPORT.md` generator and sign-off flow.
6. **Cross-system lock, live half (V3-AT-28's live arm):** the live ARISA/Drama test procedure — G owns
   the procedure, never the lock (C §5 owns the mechanism).
7. **Live throughput measurement (master §9.4/MA11):** reads F-6; G adds no counter.

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
   measured. No new quota table: LLM quota is A0's `quota_observations` (master §10.0's intent);
   non-LLM constraints are either money (charges), throughput (pilot documents, §7), or operator
   attestation (Botnoi points — O-11: Botnoi's commercial basis is `OPERATOR_ATTESTED`, DECISIONS 11 Nov,
   master §20 O-11). Rejected: a per-record table family and a second quota table (§16).
3. **The pilot is the flow, not a fixture.** P0–P2 drive one real V3 season per pilot run through the
   real commands and gates, in an **isolated pilot profile** (master §11): a dedicated compose project
   with its own DB and object volumes (the T046 drill's fresh-project pattern,
   `microdrama/deployment/staging/drill.sh:121-141`), running the same composition factory as production
   with per-provider switches enabled one leg at a time. Runtime mode is `PAID_BENCHMARK` for paid legs
   and `CONTROLLED_ACCOUNT_TEST` for live publication legs (`md_runtime_mode`, M/0008:65-95);
   `PRODUCTION` is entered only at domain activation (§3.5), never silently.
4. **Every live/paid step is operator-gated by a signed authorization** (T031-R5 §7's convention):
   per-phase authorization documents binding the phase plan hash + quote hash + envelope, signed by the
   operator (the file-byte sha256 is the binding — T031-R5 §3 R5d). The pilot runner refuses any live
   leg without the recorded authorization; envelopes are enforced by A2's accounts (hard stop, master
   §12.3), so exposure can never exceed the operator-approved cap.
5. **Screen/full admission discipline is inherited from T031** (T031-benchmark-packet.md:117, 147-148):
   **P1 is the pilot's screen** (one full episode); **P2 admits only after P1's durable quality PASS**
   (the master-§16.3 thresholds operator-signed) **and verification/billing clear** (the T031-R5 §3 R5f
   per-acquisition pattern: nothing pending, no unresolved effects). A FAIL at screen is terminal for
   the pilot run and routes to the contingency decisions (§7).
6. **"Off pace" reads exactly as A0's admission does** (A0 §3.1/§3.4): the `dramabox-llm` role —
   `dramabox-llm` is the LLM gateway **host service**: a stdlib-only Python service accepting
   invocations over an HTTP API on a Unix socket, running each attempt in its own transient systemd
   unit, operator-installed from tested files as `dramabox-llm-gateway.service` (FM §3) — refuses
   pre-launch with `PACE_WEEK` when the Pro week pace is below `min_week_bp_per_day_left`
   (800 bp/day left; `retry_at` = the week reset), `QUOTA_5H`/`CONCURRENCY` for the window/slot
   (retry at the reset / +5 min), and `QUOTA_UNREADABLE` when quota cannot be read (+10 min — A0
   §3.4; the role's live-merge status is FM §3's). `LlmStep` maps these to deferrals (A0 §5.1); G adds only the
   production-level semantics (§4): **per-window refusals (`QUOTA_5H`/`CONCURRENCY`) defer per job with
   retry times and never raise a scope alert; the two pause causes — an unreadable quota
   (`QUOTA_UNREADABLE`) and a week-exhausted route (`PACE_WEEK`) — each raise one scope-level bot alert
   per pause episode.**
7. **No silent provider switch is structural, not vigilance:** before O-5 the composition has exactly
   one live LLM route (`MICRODRAMA_LLM_ROUTE=subscription`); the API/OpenAI-compatible adapters are
   interface + fakes only (A0 §5.8) and the legacy `LLMProvider` path refuses the subscription route
   (A0 §5.5.6). The AT-14 proof asserts there is nothing to switch to (G-T2 g).
8. **Restore proof is operational, and the proof state is unclean on purpose.** The composed-restore
   drill backs up a world containing in-flight work (a submitted-but-unsettled provider operation, a
   `CLAIMED` notification attempt, a pending scheduler period), restores DB + objects into a fresh
   project, and then resumes scheduler, workers and sender — proving no duplicate effects from the
   unclean state, not from a drained one (the T046 drill drains *before* backup, `drill.sh:110-113`;
   FM §1).
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
12. **Heavy runs obey the workspace CPU discipline, unconditionally** (the E §3 composition rule, made
    G's to ship): the all-gates target, the pilot profile's edit/render work and the restore drill run
    under `systemd-run -p CPUQuota=45%`.
13. **R-12.13's "metered API keys, never the team's subscriptions" is superseded for the pilot** by
    V3C-1 (master §1 rule 3: the operator's subscription-first instruction of 11 Nov; REQUIREMENTS
    preamble :26-27 loses on precedence). The full-season provider decision is the operator's after the
    report (O-5) — G's report is the evidence for exactly that decision.
14. **The bot token is rotated before it is ever live.** The token pasted in chat (DECISIONS 11 Nov)
    is never used for a live send: rotation happens **before P1's first live bot send** and is a hard
    item on the domain-activation checklist (§3.5, re-checked at activation), recorded by reference.

---

## 2. Records (contract package, guardian-owned bump; one symbolic migration `G-1`)

Documents live in one new append-only, versioned, hash-sealed store **`v3_ops_documents`** (`G-1`),
mirroring B/C/E/F's stores (F-1's row is the template): PK `(contract_type, record_id, version)`, one
`current` row per record, hash re-verified on read, `contract_type` allowlist CHECK, standard guards (no
delete, no truncate, integer-only numbers). The merged tree already runs **one physical sealed store
with many types** (`M/0019_v2_contract_documents.sql`): G's four types are a fifth type family in that
pattern, and the G1 note **reuses the existing sealing implementation** rather than reimplementing it
(the family-level consolidation question this deepens is recorded for the master's next revision — §16).
`record_id = uuid5(OPS_V3_NS, "<type>:<key>")`. No other migration; every other G surface is an existing
table or a file (decision 2).

| Migration | Object | Decisive columns / rules |
|---|---|---|
| `G-1` | **`v3_ops_documents`** | the ops document store above; guarded |

**Documents in `v3_ops_documents`:**

| Record | Key | Content |
|---|---|---|
| `PilotRunV3` | `pilot:<pilot_season_id>` | the pilot campaign for one real season — unpacked in §2.1a below |
| `LiveClaimV3` | `live-claim:<destination>` | destination (`YOUTUBE`\|`TIKTOK`\|`FACEBOOK`); `state` (`QUALIFIED` \| `HELD`); the T032 qualification refs; verified-post evidence refs (slot identities + verification records); the observation window; a `HELD` row names its blocking capability |
| `RestoreProofV3` | `restore:<backup_set_id>` | the restore point (DB dump sha256, objects archive sha256, migration head, source runtime mode, timestamp); the procedure run (fresh project id, resume steps performed, proof kind per §5.5); per-check evidence refs (scheduler catch-up, job resume/reconcile, outbox drain, publication dedupe — §5); the honest ambiguity statement (§5.4); verdict |
| `ProductionCompositionV3` | `composition:<config_hash>` | the qualified production composition: the composition configuration hash; per-provider qualification row refs (`provider_qualifications`); the current `RestoreProofV3` ref; scheduler health evidence; the bot token rotation ref; the operator's dated activation authorization; the operator-created DNS record ref; `state` (`QUALIFIED`/`ACTIVATED`) |

### 2.1a `PilotRunV3` unpacked (one attribute group per line)

- **Campaign header:** the pilot profile + runtime mode per leg; envelope refs (the setup-budget
  approval event, episode caps).
- **Phases P0/P1/P2:** each with `state` (`PENDING`/`RUNNING`/`SCREEN_REVIEW`/`PASS`/`FAIL`/`ABORTED`),
  sub-phase (`screen`/`full` where applicable), the authorization refs (document sha256s only), and the
  measured price/throughput landing refs.
- **Claims and closure:** per-destination claim refs; the report reference + its sha256; the
  master-§16.3 threshold sign-off refs (recorded by §10's `confirm_live_thresholds`).

### 2.1b Durable-home rule (decision 9 generalized — where each record lives and survives)

Records produced inside **ephemeral profiles** (the pilot DB's `PilotRunV3` landing refs;
`RestoreProofV3`s written from scratch projects; the calibration results) are evidence only while their
profile lives, and the drill pattern ends `down -v` (drill.sh:141). Therefore:

- **Every such record must reference committed, sha256-bound file artifacts under
  `microdrama/evidence/pilot/`** — the runner exports a phase-close evidence bundle (the `PilotRunV3`
  current row + its landing refs + the calibration artifacts) at every phase transition.
- **The authoritative `v3_ops_documents` for LIVE claims and domain activation is the production
  store**: `record_live_claim` and `authorize_domain_activation` (§10) write there, never into the
  pilot DB. A LIVE claim whose evidence dangles after teardown is not a qualification artifact.
- **Retention-then-teardown:** the pilot profile is torn down only after the report sign-off (the LIVE
  row) — never `down -v` before the phase-close export is committed.
- **The P0 → production bridge:** calibration results feed C's forecast config only through the
  committed export (the config change cites the exported artifact's sha256), never by pointing
  production config at pilot-DB rows.

**Files, not rows:** the all-gate composition run record (`microdrama/evidence/v3-allgates-<date>.md`,
decision 9), the AT-28 live evidence (`microdrama/evidence/at28-live-<date>.md`, §8), the T031-lineage
per-phase pilot evidence (`microdrama/evidence/pilot/`, written by the phase-close export above), and
**`PILOT-REPORT.md`** at
`docs/microdrama-system/v3-workflow/PILOT-REPORT.md` — generated as a DRAFT by the §7.5 generator and
signed by the operator in a commit that records the report's sha256.

### 2.2 G contract crossings (the C-B1 pattern, C §2.2)

| # | Delta | Contract touched | Mechanism |
|---|---|---|---|
| GD1 | Schedule `g.quota_pause` (300 s interval — the schedule catalog's fastest class, `S/scheduling/registry.py:129/:135`; §4 records why a poller at this cadence, and §16 the rejected event-driven alternative) | A6b's schedule registry (phase-A §9.1; F added two entries the same way) | G-owned registration in G2's wiring; each firing durably records its evaluation — the episode memory §4 reconstructs across ticks and restarts |
| GD2 | `track.wait_started` admits a **scope-level, jobless variant** (payload: season, `track='production'`, cause `QUOTA_UNREADABLE` \| `PACE_WEEK`, `retry_at`, `edges: rising`) | A6a's event registry and payload schemas (phase-A §8.4) | requested as an A-side register entry — this row is the note; A's owner admits the payload variant (master §3.3's "quota wait" event at production scope). No new event name; per-job waits keep A's per-job shape. `track='production'` because the pause halts the one shared subscription route, which no single content track owns — affected jobs keep their own per-track waits (`track_waits`), so the scope alert names the route, not a track |
| GD3 | The §10 command-event families `pilot.*` (`pilot.authorized`, `pilot.claim_recorded`, `pilot.thresholds_confirmed`) and `ops.*` (`ops.domain_activated`, `ops.restore_proven`) | A1 §6's command-event convention; A §8.4's bot-event registry (checked: no overlap — these are not bot events, not schedule/job identifiers, not gate vocabulary) | declared **command-audit appends**: each §10 command appends its events inside its own transaction (A1 §6's exact convention); sink = the transactional event log. Names are G-owned and namespaced clear of A's enforced `track.*`/`gate.*` vocabulary; this row is the registration record |

**Standing rule (C-B1 for G):** any further G identifier crossing an A–F enforced contract joins this
register before the G1 note is accepted.

---

## 3. Production composition completion and domain activation (master §10.6; R-11.1, R-12.10, R-12.11)

### 3.1 What "completed" means

A6c (phase-A §9.2) built the skeleton: role selection (`--composition production`), role-specific
startup dependencies, fail-closed exits, `provider_qualifications`, and A0's dispatch-time checks stay.
**G completes it in place — no second composition entry point:**

- **Per-provider completion checks, at startup and dispatch** (the C §5 predicate generalized, master
  §1 rule 5): a provider is live-enabled only when *all* hold — the per-provider switch (default
  **off**), a current `provider_qualifications` row (configuration hash, evidence ref, unexpired), the
  applicable rights/capability records, and (paid kinds) a known price/quote. Any missing piece keeps
  the provider disabled — never zero-priced (C §1.7's rule). **Startup vs dispatch:** a provider
  **enabled in configuration** (switch on) missing any piece refuses **startup**, naming the provider
  and the piece (fail-closed); a switch-off provider is merely disabled (its jobs defer typed — the
  normal pre-qualification state); a piece expiring after startup (e.g. a qualification row) refuses
  **dispatch** typed, as defense in depth. G-T5 asserts the matrix.
  - **LLM:** gateway health OK with the expected policy identity (A0 §5.7), `dramabox-llm` qualified
    per A0 §7's live qualification (`A0-LIVE-REPORT.md` current — A0 §7's prospective report, written
    by that procedure when it runs, not yet on disk at this draft; policy identity matching).
  - **Image:** C's predicate plus the cross-system lock's pinned-inode qualification row on the real
    mount topology (C §5; §8 here).
  - **Render:** the T031 qualification record and `feat/t031-fix3` merged (master §4.6 N36), the
    production native-render adapter (D's contract — prerequisite pinned by D's spec).
  - **SFX / music:** C8's qualified routes and prices (YuE2 = the music-generation library job C8
    qualifies, beside the SFX routes).
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

Provenance rows live in the DB (`asset_lineage`, `rights_registry`, `charges.receipt` — FM §1), so the
backup step (pg_dump of postgres + tar of the object-store volume, drill.sh:115-119) covers them with
the DB. G ships the backup **timer-ready** as **one shared, tested backup entrypoint** (a script + a
systemd timer unit, operator-installed — the A0 §4.1 pattern) that the nightly timer **and** the drill's
step 6 both call — never two backup implementations (§5.5; §16). Every backup writes its
`RestoreProofV3` point fields at creation; a proof completes the record per §5.5's matrix. The
DOMAIN-RUNBOOK.md:33-35 nightly step remains the operator's restic decision — O-G2.

### 3.4 Final qualification

The `ProductionCompositionV3` record is G's **final qualification** artifact: it binds the composition
configuration hash, every enabled provider's qualification row, the scheduler singleton's health
evidence (A6b), and the current `RestoreProofV3`. It is written by the qualification procedure (G5) and
is the input to domain activation.

### 3.5 Domain activation (R-11.1; master §3.1)

`authorize_domain_activation` (an operator command, §10) is refused unless **all** of: a current
`ProductionCompositionV3` (`QUALIFIED`); a proven restore (a `RestoreProofV3` verdict PASS, **of either
§5.5 proof kind**, taken within a config-owned freshness window, default 7 days — master §10.6's "a
proven restore before domain activation"); the scheduler service healthy; **the bot token rotated**
(decision 14) with the rotation recorded by reference; the operator's dated authorization (a DECISIONS
entry or signed file); and the operator-created DNS record referenced (D5: DNS, TLS and deploy are
operator-authorized; the DOMAIN-RUNBOOK stays the deploy procedure). The record flips to `ACTIVATED`;
Traefik/TLS steps remain the runbook's, executed by the operator.

---

## 4. `dramabox-llm` off-pace: pause and alert (V3-AT-14)

**The pause is derived, never stored** (AR-4 — phase-A-spec's architecture-rule appendix: side states
are derived, never stored): `llm_route_paused(season)` is true while (a) the latest quota observation
for the route is unreadable, or (b) any **active `PACE_WEEK` deferral** exists — active meaning a
non-terminal deferral with `defer_reason=PACE_WEEK` **regardless of its `retry_at`** (A0 §5.1's
60 s–6 h clamp shortens retries, never episodes), the week reset being days away — refusal with a retry
time is, in production effect, a pause (master SPEC-v3.md:665-667 "Persisted refusals carry retry
times; an unreadable quota pauses production / No silent provider fallback").

**One source for enforcement and alert.** The predicate reads the stored observation stream A0's quota
reader produces (one `quota_observations` row per read, unreadable reads included) — the same stream the
dispatch gate's health check consults (A0 §5.7), so enforcement and alert cannot silently disagree. The
**un-pause reader** is the gate itself: deferred jobs retry per their `retry_at`, each retry
re-evaluates the gate, a readable observation lands, and the pause clears.

- **Route-level pause (QUOTA_UNREADABLE):** `LlmStep`'s dispatch gate (A0 §5.7) treats unreadable quota
  as a failed composition check — every LLM-dependent job (B planning, D directing, F prefill) defers
  `WAITING_QUOTA` and no new LLM dispatch admits until quota is readable again. Non-LLM work (render of
  already-directed shots, edit, publish) continues — waits are scope-keyed and never suspend unrelated
  approved releases (master §2.2).
- **Per-job waits (QUOTA_5H, CONCURRENCY):** existing behaviour (A0 §5.1 deferral with `retry_at`),
  projected `WAITING_QUOTA` through `track_waits` (A1 note §2.4) — no scope alert.
- **The alert — polled, with the choice recorded.** The `g.quota_pause` schedule (GD1) evaluates the
  predicate each tick; each firing durably records its evaluation, and **an episode is a maximal run of
  true evaluations, reconstructed on restart from the last recorded evaluation**. On a **rising edge**
  it emits one scope-level `track.wait_started` (GD2) → the Dramabox Bot's quota-wait alert. One alert
  per pause episode (no per-job spam); **no recovery event exists or is needed** (A §8.4 has no
  wait-ended event and GD2 extends payloads, never names) — recovery is visible on Home and in the
  09:00 summary. **Why a poller, not event-driven emission at the dispatch gate:** the falling edge has
  no event source at all, and once every LLM job has deferred, dispatch traffic stops — gate-side
  emission would go silent exactly during the longest pauses; the poller is traffic-independent and its
  firing rows are the episode memory (§16 records the rejected alternative). **Cadence:** 300 s, the
  catalog's fastest class — alert latency stays far inside A0's +10 min `QUOTA_UNREADABLE` retry
  horizon, so nothing faster buys anything.
- **Alert content:** the cause and `retry_at` always; **pace numbers only on a `PACE_WEEK` cause** — an
  unreadable quota has none, and its alert carries the read error instead.
- **Home surface:** the route pause renders as a scope-level banner on Home (master §3.3's "quota
  waits" row), derived from the episode record — never from per-job rows (A1 note: the `track_waits`
  view is built exclusively from `jobs` rows, so the jobless scope pause needs its own reader). The
  banner is dismissable (A1's scope-alert dismissal — scope alerts key on neither job nor operation)
  and clears on recovery. G-T2(i) asserts it.
- **No fallback:** decision 7 — the proof (G-T2 g) asserts the composition exposes exactly one live LLM
  route and that enabling any API adapter is refused (they are not live-capable before O-5).
- **Pilot pacing input:** pause episodes, counts and window pacing are pilot-report content (N12,
  master §11) — §7.4.

---

## 5. Composed restore (V3-AT-32; master §12.5 → master §10.6)

### 5.1 The procedure (extends the T046 drill; the drill's steps stay)

1. **Seed an unclean world** (test profile): one provider operation `SUBMITTED` (external id unknown to
   the local row), one notification intent with an unfinished `CLAIMED` attempt (crash mid-send), one
   calendar trigger whose period has fired on the source but whose marker is uncommitted, plus ordinary
   settled work. Backup: `pg_dump` + objects tar (drill.sh:115-119, via the shared backup entrypoint,
   §3.3) → the point fields of a `RestoreProofV3`.
2. **Restore** into a fresh compose project (drill.sh:121-141: postgres up, **`psql -v ON_ERROR_STOP=1`
   load of the dump** (drill.sh:127 — the drill restores through psql, not `pg_restore`), app up,
   health + owner login + page-read). **Delta on the drill, new G work:** the drill never restores the
   objects archive (the tar written at drill.sh:118 is not extracted today) — the composed-restore
   extension adds objects extraction into the fresh project's volume.
3. **Resume, in order:** the scheduler singleton starts (catch-up fires **at most the latest missed
   period** per trigger — phase-A §9.1.4's A6b bound, a spec bound on today's dedupe semantics, not a
   line of code: `S/scheduling/service.py:21-22` is what makes a missed marker safe); workers start (the
   janitor/reconciler path resolves the in-flight operation via its client token —
   `S/contracts/providers.py:200` "NOT_FOUND = safe to resubmit"; adopt-by-external-id otherwise); the
   sender re-claims the `CLAIMED` intent (A §8.3's `AMBIGUOUS` path: one retry, flagged
   `possible_duplicate`, then dead letter).
4. **Assert and record:** §5.2's checks; the `RestoreProofV3` verdict (proof kind recorded per §5.5).

### 5.2 What must hold (the AT-32 assertions)

- **Jobs:** the interrupted operation is reconciled, never blindly resubmitted; the fake provider
  records **zero duplicate submits**; a `NOT_FOUND` outcome re-arms exactly once (the existing
  reconcile semantics, FM §1).
- **Scheduler:** no duplicated firings or effects across the restore boundary (`scheduler_firings`
  uniqueness; "missing state can never duplicate an effect because the semantic keys dedupe",
  `S/scheduling/service.py:21-22`, `M/0017_schedule_state.sql:2-3`).
- **Outbox/notifications:** delivery is at-least-once with consumer dedupe (`S/core/events.py:8-10`);
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

### 5.5 Proof kinds and cadence (the matrix §3.3/§3.5/O-G2 rest on)

| Proof kind | World | Sender transport | Cadence | What it completes |
|---|---|---|---|---|
| **Unclean-world proof** (§5.1) | the seeded unclean **test-profile** world | fake | at G3's gate, pre-live, and whenever the composition or backup path changes | the full §5.2 assertion set |
| **Nightly control proof** | the production timer's latest backup set — natural state, nothing injected | **fake-transport composition** — a resumed sender with the real transport could deliver real duplicate Telegram messages (§5.4's own at-least-once admission), so the nightly proof never resumes a real sender | nightly, on the timer window's set | a clean restore+resume `RestoreProofV3` PASS (the §5.2 checks that need no injected ambiguity) |

Activation (§3.5) accepts the **freshest PASS of either kind** within the freshness window. **One backup
entrypoint** (§3.3): the timer script and the drill's step 6 call the same tested implementation — the
proof validates exactly what production runs; the two never fork (§16).

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
3. **Release:** compressed calendar; release admission + fake publish + verification per destination
   with a **seeded capability record** (T032's qualification itself is live-only — the offline suite
   seeds the records it flips); buffer/throughput counters tick (F-6).
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
requires both authorities** (F §7.1) at the composition level; (e) **the track model runs IDEA →
`PUBLISHED_VERIFIED` → `COMPLETE` without dead ends**; (f) one composition object graph serves every
phase — the wiring the pilot and production will run. It does **not** duplicate F-T8's 30-episode
release storm (V3-AT-29 stays F's; §6's release pass exercises the gates, not the failure catalogue).

**Bound:** target ≤ 15 min wall-clock under the CPU quota — a target that drives fixture tuning in G4,
not a promise; the gate itself is a **hard fail beyond 2× the target (30 min)**, with the measured time
recorded in the artifact (the T031-R5 §4 honesty convention).

---

## 7. The LIVE pilot (V3-AT-17; master §11, master §16.3; R-12.13)

### 7.1 The pilot profile and the runner

`deployment/pilot/` (compose project, port 8094 — the drill's fresh-project pattern; volumes
`pilot-pg`/`pilot-objects`; same image; O-G1). A pilot CLI (`python -m microdrama.ops.pilot`) with
`prepare / authorize-check / status / report` subcommands — offline-testable, no network in tests. The
runner **drives** the flow (it does not bypass it: every step goes through the real commands and gates);
its live legs are refusal-first without the recorded authorization (decision 4). The runner is also the
**sole writer of `PilotRunV3` phase/version rows** through those driven steps (§10's commands bind
authorization and threshold fields; nothing else appends phases).

### 7.2 P0 — planning, reduced cast, lock throughput (needs A0–C; master §11)

1. **Calibration batch (operator-authorized, bounded):** live Nano Banana through C's lock + fairness
   (prerequisite: C3 merged, ARISA-side adoption per master §10.2 — §8) — measures the **lock
   throughput (images/hour)** and the **real per-image price**; results land in `PilotRunV3` and feed
   C's forecast config (O-C7's defaults, re-measured — master §10.4: the measurement is
   operator-visible **before CAST generation starts**) **through the committed export** (§2.1b). Price
   bootstrap: O-G3 — the operator records a provisional rate-card quote; measured receipts replace it
   and the forecast recomputes.
2. **Full planning, steps 1–3** (B's planning steps: 1 Script Maker → LOCK, 2 bible, 3 episodes → STORY
   LOCK — B §3–§5; **step 4 is C's cast step**, started when C's handler registers, B:438): 24 episodes
   through the real `dramabox-llm` subscription (Opus bible/architect/season critic; Sonnet translation
   — B §7.2, master §10.1 roles).
3. **Reduced step 4:** 2 characters, 2 locations, voices for both (Botnoi Studio manual upload — O-C1's
   decided intake), under the setup sub-budget (approved via A2 `approve_setup_budget` — the pilot
   envelope).
4. **N12 records:** planning wall-clock, quota-pause counts and window pacing from
   `llm_invocations`/`quota_observations` + scheduler firings.

**Critical path (honest):** the pilot is **ARISA-blocked end to end** — the calibration batch, step 4's
cast generation and every P1/P2 episode's image work all wait on C3 + ARISA-side adoption (§8). Steps
1's planning half (item 2) and the voices (item 3) run ahead of that gate, with O-C7's configured
defaults as the interim forecast until the calibration lands.

### 7.3 P1 — one full episode, the screen (needs D accepted + T031 qualified; master §4.6 N36)

One episode end to end — directing (Sonnet via the gateway), render (the production native-render
adapter over the accepted T031 transport/recovery primitives), clip QA, edit, metadata, Gate 2 — plus
the **mixed-emotion exit check** (master §6 MA12: ≥80% of emotional/mixed-emotion shots reading
correctly, judged by the recorded Gate-2 human assessment; T031's S05/S06 — the grief and anger
emotion-coverage runs from neutral references — are the first evidence). Below threshold: the
**pre-agreed contingency** — **split coverage at speech-safe boundaries**: re-cut a mixed-emotion shot
into clips cut where no speech is mid-utterance (master §6's clip-length rule), so each clip carries one
expression — pre-agreed in the master itself (master §6 MA12, SPEC-v3.md:550-553). Switching to it
needs an operator decision with its projected clip/cost impact — the pilot run goes `SCREEN_REVIEW` →
operator decision, and **FAIL is that operator's terminal decision inside `SCREEN_REVIEW`** (decision
5), never an automatic switch. **The bot token is rotated before P1's first live send** (decision 14).
P1 PASS is durable (operator-signed thresholds, §7.5 + the §10 `confirm_live_thresholds` command) and
gates P2 (decision 5); billing/verification clear per the T031-R5 R5f pattern before P2 admission.

### 7.4 P2 — three more episodes, throughput vs SLO

Three further episodes; the release calendar runs **compressed** (operator-chosen dates) so F-6's closed
intervals capture the sustained rate. **Measurement window, stated:** P2's evidence is the
**release-interval span since LAUNCH approve** (complete intervals only — F-6's rule); F's rolling
7-day sustained rate is the *production* SLO's definition (F §9), which a ~2–3-day pilot span cannot
honestly fill — the pilot reports the span rate and **names the window** in the report's throughput
section (§7.5). **Catch-up:** the operator-chosen compressed calendar **must schedule one ≥2
episodes/day × 2-day catch-up window** (F §9's catch-up definition); if the chosen dates cannot fit it,
catch-up is recorded **UNMEASURED** and the operator signs the adaptation through
`confirm_live_thresholds`. LIVE acceptance numbers: sustained ≥1.25 approved episodes/day over the
pilot span, catch-up as scheduled or UNMEASURED-with-signed-adaptation, buffer ≥3 (alert <2), **at cost
≤ cap** read from A2's accounts (master §9.4, master §16.3). Non-LLM quota capture per decision 2:
images (counts + throughput), GPU seconds (`pod_usage_intervals`), SFX/YuE2 (charges), Botnoi points
(operator attestation).

### 7.5 `PILOT-REPORT.md` (master §11's contents, generated)

`pilot report` renders the DRAFT deterministically from the metering tables (decision 2's enumeration —
`llm_invocations`, `quota_observations`, `charges`, `cost_allocations`, `pod_usage_intervals`,
`release_throughput_observations`) — measured vs forecast clearly marked; cost per episode by provider
(cash / allocation / estimate — never summed blindly, master §11); quota per episode per provider;
planning wall-clock, quota-pause counts, window pacing; **throughput with its window named** (§7.4's
release span; F-6); the master-§16.3 quality measures; the **frozen-workload LLM comparison** (k frozen
workloads per role run under both Opus and Sonnet, usage from `llm_invocations`; O-G5); per-destination
live claims; **the disposition of the pilot's published output** (episodes and posts on the controlled
accounts are evidence, never the launch product — keep or retire is the operator's sign-off item); and
a recommendation for the operator's master-§11 decision (LLM plan, pace, season start). The operator
signs by a commit recording the report's sha256; threshold confirmations land in `PilotRunV3` (§10's
`confirm_live_thresholds`).

### 7.6 Per-destination LIVE claims (master §16.2)

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
  observes the other's hold as exclusion; the kill-after-admission-before-submit recovery choreography
  (C-T6's template) runs on an **isolated copy of the topology that mirrors the parent-directory bind**
  (a file-only copy would prove nothing about PC5-2's rule) — the canonical inode is never swapped or
  replaced while generators may run (C §5's PC-7 rule), so the swap→typed-BLOCKED case is proven only on
  the copy.
- **Stage 2 — one live pair (operator-authorized):** one real ARISA generation and one Drama live image
  job, interleaved; assert mutual exclusion and **configuration conformance** with the fairness bounds
  (≤8 images / ≤120 s per hold) — one live pair checks that the deployed configuration matches C's
  bounds and that exclusion holds; behavior *under contention* is C-T6's simulated-competitor result,
  not this pair's. No overlap of provider processes across a container restart. Evidence →
  `microdrama/evidence/at28-live-<date>.md` + the qualification row's evidence ref.

---

## 9. Live throughput reporting (master §16.3 / MA11)

No new surface: the report reads F-6 (closed intervals; complete-interval only; rolling aggregates
derived — F §9) and A2's accounts for cost-to-date; **the pilot's window is §7.4's release span, named
in the report**. The SLO breach alert is F's bot wiring (`slo.below`, `buffer.low`); G's live operation
simply runs it (FM §6: the counters and alerts are F9's offline deliverables — G's obligation is the
*live measurement* and the report's throughput section). Master §16.3's final row — "Throughput ≥ the
master-§9.4 SLO at cost ≤ cap" — is signed with the thresholds (§7.5 + the §10
`confirm_live_thresholds` command).

---

## 10. G commands (A1 note §6 format) and schedules

| Command | Actor | Scope / revision owner | Prerequisites | Effect | Events | Replay identity | Activation |
|---|---|---|---|---|---|---|---|
| `record_pilot_authorization(phase, doc_sha256s)` | Operator (human session + CSRF) | pilot run / the `PilotRunV3` phase | the signed authorization file exists; the phase is `PENDING` | binds the authorization to the phase (unlocks that leg's runner gate) | `pilot.authorized` | idempotency key | **G** |
| `record_live_claim(destination, state, evidence)` | Operator (human session + CSRF) | destination / the `LiveClaimV3` row | pilot release legs or T032 evidence exists | appends a `LiveClaimV3` version **in the production store** (§2.1b) | `pilot.claim_recorded` | idempotency key | **G** |
| `confirm_live_thresholds(measures, adjustments)` | Operator (human session + CSRF) | pilot run / `PilotRunV3` | P1/P2 evidence present | records the master-§16.3 confirmations (and any UNMEASURED-with-adaptation entry, §7.4); feeds the report's sign-off block | `pilot.thresholds_confirmed` | idempotency key | **G** |
| `authorize_domain_activation(composition ref, restore ref, rotation ref, authorization ref, dns ref)` | Operator (human session + CSRF) | production composition / `ProductionCompositionV3` | §3.5's checklist all present | writes/updates `ProductionCompositionV3` → `ACTIVATED` | `ops.domain_activated` | idempotency key | **G** |
| `record_restore_proof` (drill-internal) | System | backup set / the `RestoreProofV3` row | §5's procedure ran | writes the `RestoreProofV3` verdict (proof kind per §5.5) | `ops.restore_proven` | the backup-set identity | **G** |

**Invocation surface:** operator commands run from the operator admin console — A1 §6's human-session +
CSRF surface, the family convention. **`PilotRunV3` writers:** the runner (§7.1) appends phase/version
rows through the driven flow; the §10 commands above bind the listed fields; nothing else writes the
document.

**Schedules G adds:** `g.quota_pause` (GD1; 300 s). **Jobs G adds:** none (decision 1).

---

## 11. Build packages (in order; `make check` + V1 `make pilot` green at every gate)

Prerequisites: **A0, A, B, C, E and F accepted; D's spec is pending** (none exists at this draft —
header) and its render/QA contracts are pinned prerequisites (§7.3). **D acceptance gates the
render-live legs — G4's suite needs D's handlers in the composition, G5's render qualification and G6's
P1/P2 runbooks need D's contracts — not G1–G3** (store, pause/alert, restore are D-free and may build
ahead; G7 is C/ARISA-pinned, not D-pinned). T031 qualified with `feat/t031-fix3` merged for anything
render-live (N36); T032 records for any publication-live leg. Real migration numbers allocated in the
G1 note from the tail.

| Package | Builds | Gate | Design note | Create / modify |
|---|---|---|---|---|
| **G1** | `G-1` store + `OpsV3Store`; contracts bump (the four document types); the §2.2 crossing register delivered (GD1–GD3) | G-T1 | **Critiqued first** (migrations + crossings) | **Create** (migration, store module; the contracts bump modifies the generated contracts) |
| **G2** | Off-pace pause: the derived predicate, `g.quota_pause`, the scope-level alert, the Home banner reader; the no-fallback composition proof | G-T2 (V3-AT-14) | With the diff | **Modify** (schedule-registry registration and composition/gate wiring in A6b/A6c/A0 territory); Create: the banner reader |
| **G3** | Composed restore: the drill extension (unclean seed, resume steps, objects extraction), `RestoreProofV3` writer, the ambiguity statement; **the shared backup entrypoint + timer files** (§3.3) | G-T3 (V3-AT-32) | **Critiqued first** (ops-critical) | **Modify** `microdrama/deployment/staging/drill.sh` (steps 5–7 extended, step 6 routed through the shared entrypoint); Create: backup script + timer units |
| **G4** | The all-gate composition suite + fixtures + `make v3-allgates` + the evidence writer | G-T4 (V3-AT-34) | With the diff | **Modify** `microdrama/Makefile` (new target); Create: suite, fixtures, writer |
| **G5** | Composition completion: per-provider completion checks (the §3.1 startup/dispatch matrix), CPU-quota deployment units, the qualification procedure, `ProductionCompositionV3`, the activation checklist + command | G-T5 | With the diff | **Modify** composition startup/dispatch checks (A6c territory); Create: units, procedure |
| **G6** | Pilot scaffolding: the pilot profile, the runner CLI, authorization/envelope gates, the frozen-workload harness, the `PILOT-REPORT.md` generator, the phase-close evidence export (§2.1b) | G-T6 | **Critiqued first** (money paths) | **Create** |
| **G7** | Live procedures pack: the AT-28 live procedure (§8), the P0–P2 runbooks (dry-run modes) at `deployment/pilot/runbooks/`, the live-claim and threshold flows | G-T7 | **Critiqued first** (money/locks) | **Create** |

**Routing:** GLM builds each package (`ai-route build -w`); Codex critiques the G1/G3/G6/G7 notes and
reviews every diff; one package at a time. **All offline gates run under the workspace CPU quota.**

---

## 12. Acceptance (offline unless marked LIVE; real PostgreSQL for transaction tests; pytest
`--basetemp` under the session scratchpad)

**Bolding key:** a bold row carries a master V3-AT id (G-T2/T3/T4 and the LIVE execution row); in §11,
bold marks the critiqued-first packages. G-T2, G-T4 and G-T5 hold their assertions in the enumerated
lists below the table — one observable per bullet, so each can be ticked independently.

| Test | Package | Proves |
|---|---|---|
| G-T1 | G1 | `G-1` applies on a populated V1+V2+V3 database; guards present (no delete, no truncate, integer-only numbers) and the store's document-type catalog lists exactly the four G types; documents roundtrip hash-verified; applied migrations unchanged; generated contracts zero drift |
| **G-T2 (V3-AT-14)** | G2 | Off-pace pause, alert and Home surface through the production composition — assertions (a)–(i) below |
| **G-T3 (V3-AT-32)** | G3 | The §5.1 procedure on the unclean world: restore + resume with **zero duplicate submits** (fake provider counts), at most the latest missed period fired, the ambiguous notification **retried at most once, flagged `possible_duplicate`, then delivered or dead-lettered**, no duplicated publication; `RestoreProofV3` verdict PASS and its ambiguity statement matches the observed behaviour; a drained-world control run also passes; the timer unit files are present and invoke the one shared backup entrypoint the drill uses (§3.3) |
| **G-T4 (V3-AT-34)** | G4 | The §6 suite over one season, all real handlers, fake providers — assertions (a)–(j) below |
| G-T5 | G5 | Fail-closed completion and activation per the §3.1 startup-vs-dispatch matrix — assertions (a)–(f) below |
| G-T6 | G6 | The runner refuses every live leg without the recorded authorization (hash-bound; a wrong sha refused); the envelope is the account hard-stop (a leg over the setup budget is refused); the report generator over a seeded pilot-shaped dataset produces every master-§11 section with measured-vs-forecast marked and per-provider quota lines (LLM/images/GPU/SFX/YuE2/Botnoi); the frozen-workload harness records **each role's usage under both models** (4 roles × 2 — O-G5); the threshold flow (§10 `confirm_live_thresholds`) records the master-§16.3 confirmations and feeds the sign-off block; the phase-close evidence export (§2.1b) is written sha256-sealed; no test touches the network |
| G-T7 | G7 | The AT-28 dry choreography on an isolated copy mirroring the parent-directory bind topology, with **C-T6's simulated-competitor harness playing the ARISA side**: exclusion, kill-after-admission recovery, swap→typed BLOCKED (real-inode holds coordinated in the runbook); the P0–P2 runbooks' dry-run modes execute end to end against fakes; a T032-held destination records `HELD` and is excluded from claims |
| G-T8 | all | `make check` + V1 `make pilot` green at every package gate; `make v3-allgates` green at G4 and before any live qualification |
| **LIVE** | execution (operator) | V3-AT-17 and master §16.3 complete only through the operator-gated P0–P2 execution with evidence: pilots complete; `PILOT-REPORT.md` signed with measured per-episode cost and quota per provider; master §16.3 thresholds confirmed; AT-28's live stage recorded; per-destination claims recorded. **G's packages never spend — this row passes outside the build, by the operator's hand** |

**G-T2 assertions (one observable each):**

- **(a) Test seam:** the production composition is built by the one composition factory with the
  production role's configuration, against real PostgreSQL; the only substitution is the LLM gateway —
  A0's fake (A0 §5.8's interface + fakes) bound at the gateway interface, with qualification rows seeded
  for the fake's identity. No second composition is created; the production composition's own
  `OFFLINE_MOCK` refusal is G-T5(e)'s assertion, not loosened here.
- (b) `PACE_WEEK` refusal → LLM-dependent jobs defer `WAITING_QUOTA` with `retry_at` = the week reset.
- (c) `QUOTA_UNREADABLE` → the route pause holds new dispatch and every LLM job defers.
- (d) a `PACE_WEEK` deferral whose `retry_at` A0 §5.1 clamped (60 s–6 h) keeps the episode open — no
  spurious falling/rising pair mid-pause.
- (e) the scope-level alert fires exactly once per pause episode (rising edge; no spam across ticks or
  restarts — the durable firing evaluations of §4).
- (f) per-job `QUOTA_5H`/`CONCURRENCY` stays per-job (no scope alert).
- (g) exactly one live LLM route exists and enabling an API adapter is refused (A0 §5.8).
- (h) recovery resumes work; non-LLM tracks continue throughout.
- (i) the route pause renders on Home as a scope-level banner derived from the episode record (never
  from per-job `track_waits` rows), is dismissable (A1's scope-alert dismissal), and clears on recovery.

**G-T4 assertions (one observable each):**

- (a) every gate approves through the real decision transaction;
- (b) a stale hash is refused at each gate;
- (c) the STORY→CAST→Gate-2→TEASER→LAUNCH authority chain is consistent in one lifecycle;
- (d) dispatch requires both authorities (F §7.1) at the composition level;
- (e) the amendment fences cross-phase work, with stale results quarantined;
- (f) the reschedule rebuilds date-bearing content only; published media stay immutable;
- (g) the five produced episodes reach `PUBLISHED_VERIFIED` per destination;
- (h) the season reaches `COMPLETE` with the unproduced remainder closed out through F's
  `close_out_episode` (its first composed exercise);
- (i) the evidence artifact is written with parameters, fixture hashes, per-gate bindings and timings;
- (j) the runtime bound holds as a hard gate: fail beyond 30 min (2× the §6 target), measured time
  recorded.

**G-T5 assertions — the startup-vs-dispatch matrix (§3.1):**

- (a) a provider **enabled in configuration** (switch on) missing its qualification row, rights record
  or (paid kinds) price → **startup refuses**, naming the provider and the missing piece (never
  zero-priced);
- (b) a provider whose switch is off is merely disabled — the composition starts and its jobs defer
  with the typed reason (the normal pre-qualification state);
- (c) a qualification row expiring after startup → **dispatch refuses typed** (defense in depth);
- (d) the activation checklist refuses without each of: restore proof, scheduler health, bot-token
  rotation record, operator authorization, DNS ref (§3.5);
- (e) staging unchanged: `OFFLINE_MOCK` guards intact, including the production composition's refusal
  to start in it;
- (f) the CPU-quota deployment units (§3.1) ship as tested files.

---

## 13. Requirement trace

| R-ID / AT | Where |
|---|---|
| R-11.1 (domain, owner login, TLS) | §3.5, §10; G-T5 |
| R-12.10 (scheduler, backups, per-provider live switch) | §3.1, §3.3, §3.5; G-T3, G-T5 |
| R-12.11 (live providers wired and qualified) | §3.1–§3.2 (G qualifies; C/D/F/T032 wire); G-T5 |
| R-12.13 (cost/quota meter + pilot before pace) | §7 (superseded-for-pilot per V3C-1, decision 13); G-T6 **+ LIVE** |
| V3-AT-14 | §4; G-T2 |
| V3-AT-17 (LIVE) | §7; G-T6 + LIVE |
| V3-AT-32 | §5; G-T3 |
| V3-AT-34 | §6; G-T4 |
| V3-AT-28 (live half) | §8; G-T7 + LIVE |
| MA11 (master §16.3 LIVE thresholds) | §7.4, §9; the LIVE row |

---

## 14. Open questions (each with a recommendation)

| # | Question | Recommendation |
|---|---|---|
| O-G1 | Pilot profile topology: separate compose project + volumes vs a schema in the shared DB | **Separate compose project** (port 8094, own volumes, same image — the drill pattern); a shared-DB schema risks the operator's real data and weakens mode isolation |
| O-G2 | Nightly backup execution (the runbook's restic step is unexecuted — FM §1) | Ship the **timer-ready backup script + systemd unit** (operator-installed), with the nightly **control proof** of §5.5 on each timer window's set (fake transport); the unclean-world proof runs per §5.1 at G3's gate and pre-live; restic inclusion stays the operator's separate decision |
| O-G3 | Image price bootstrap: C's forecast is BLOCKED on an unknown price (O-C4), but measuring requires spending | The operator records a **provisional rate-card quote** admitting the bounded calibration batch inside the envelope; measured receipts replace it and the forecast recomputes — the cap bounds exposure either way |
| O-G4 | AT-28 live-test scheduling risk (ARISA-side adoption is the long pole — FM §5) | Two stages (dry choreography, then **one** live pair), both operator-authorized; a mini-envelope bounds the live spend; the procedure declares adoption a hard prerequisite and escalates to the operator if lagging |
| O-G5 | Frozen-workload comparison size (subscription quota is the scarce resource) | **k=2 per role** over the four per-episode LLM roles (bible, architect, **directing**, metadata — the master-§10.1 role split's recurring per-episode steps across B/D/F, the ones the O-5 decision prices), bounded `max_budget_microusd` per call (A0 §3.1) — enough for the master-§10.1 comparison without eating the pilot's window |
| O-G6 | Is the all-gate suite in `make check`? | **No** — a dedicated `make v3-allgates` target, run at G4 and before any live qualification (G-T8's cadence); a one-season smoke variant may join `make check` later if it stays <60 s |
| O-G7 | `PILOT-REPORT.md` location | `docs/microdrama-system/v3-workflow/PILOT-REPORT.md` (the master names it bare; beside the specs is where the master-§11 decision is read) |
| O-G8 | Does the pilot profile need the sender/bot live? | The bot sends to the operator's real chat with a **token rotated before P1** (decision 14 — the chat-exposed token is never live); recommend live sends during P1/P2 (the alert paths are part of what the pilot measures — pause episodes), with §3.5's checklist re-checking the rotation record at activation |

---

## 15. Risks and limits

| Risk | Limit / mitigation | Owner |
|---|---|---|
| Subscription quota exhausts mid-pilot (a full season's planning calls — 24 episodes through every planning role — through a max-concurrency-1 gateway) | the pause/alert path is *part of the pilot's evidence* (N12); window pacing reported; the operator paces or pauses between phases | Operator |
| Live image spend exceeds the envelope | the setup sub-budget is a hard stop (A2); the calibration batch is bounded; measured prices replace provisional ones | Operator (O-G3) |
| T032 delays keep destinations `HELD` | master §16.2 per-destination claims by design — held destinations are excluded, never faked | T032 |
| ARISA-side lock adoption lags — and it blocks the pilot's critical path end to end (calibration, cast, every P1/P2 episode; §7.2) | AT-28's live stage is a hard-prerequisite procedure; the pilot's image legs stay disabled until adoption + qualification (master §10.2); planning steps 1–3 and voices run ahead with O-C7 defaults | ARISA owner |
| The unclean-restore drill grows brittle with schema drift | G-T3 runs at G3's gate and pre-live (the heaviest test deliberately not on every package gate); the drill is versioned with the composition | G3 builder |
| Host CPU contention (all-gates suite, pilot edit/render) | CPUQuota on every heavy run, unconditionally (decision 12); the suite's runtime bound is a gate (G-T4 j) | G builders |
| Pilot-profile drift from the production composition | both build from the one composition factory; the qualification record pins the config hash | G5 builder |
| The alert episode's durable state is mis-reconstructed after a restart | the episode is a maximal run of durably recorded firing evaluations (§4); G-T2(d)/(e) assert exactly this across ticks and restarts — a wrong reconstruction fails loudly at G2's gate | G2 builder |
| Pilot/restore evidence lost at profile teardown (the drill pattern ends `down -v`) | the durable-home rule (§2.1b): sha256-bound file exports at every phase close; teardown only after the report sign-off; G-T6 asserts the export | G6 builder |
| P2's window cannot express the production SLO's rolling 7-day rate | the pilot reports the release-span rate with the window named (§7.4); catch-up either scheduled or UNMEASURED-with-adaptation signed by the operator | Operator |
| Upstream volatility: no D spec yet, T031-fix3 unmerged until N36, A-line worktrees unmerged | every D-dependent obligation is a pinned prerequisite (header); D-pinned packages (G4–G6) wait; prerequisites re-checked at each package gate | Orchestrator |

Master-level risks and their owners: master §18 (quota terms, throughput SLO, cap changes).

---

## 16. Alternatives rejected (one per major choice)

| Choice | Rejected alternative | Why rejected |
|---|---|---|
| One ops document store (`G-1`) | Per-record tables | mirrors B/C/E/F: one guard/hash/allowlist story; per-record tables duplicate the sealing machinery per type. The merged tree already runs one physical sealed store with many types (M/0019) — G's four types are a fifth type family in it; the family-level consolidation question this deepens is recorded for the master's next revision, and the G1 note reuses the existing sealing implementation rather than reimplementing it |
| Existing tables + documents for quota | A second quota-observations table (non-LLM) | LLM quota is A0's `quota_observations` (master §10.0's intent); image constraint is throughput; the rest is money (charges) or attestation — a second table would model nothing that exists |
| Generated `PILOT-REPORT.md` DRAFT + operator sign-off | A hand-written report | master §11 demands measured numbers from the metering tables (decision 2's enumeration); hand-copying invites exactly the blind-summing master §11 forbids |
| The pilot is the flow | A fixture-driven pilot | the pilot's product *is* evidence about the real flow (quota pauses, window pacing, lock throughput); fixtures cannot measure those |
| AT-34 with all real handlers + fake providers | Test gate handlers (the A-T17 idiom) | the composition's completeness is the thing AT-34 proves; test handlers would prove the shell only (A §2.7) |
| Jobless `track.wait_started` variant (GD2) | A new `production.paused` event name | master §3.3's event list is binding vocabulary; a scope-level "quota wait" is within it — extend the payload, not the name |
| Polled pause edge at the catalog's fastest cadence, 300 s (§4) | Event-driven emission at the A0 §5.7 dispatch gate | the falling edge has no event source (A §8.4 has no wait-ended event; GD2 extends payloads, never names), and once every LLM job has deferred, dispatch traffic stops — gate-side emission goes silent exactly during the longest pauses; the poller is traffic-independent and its firing rows are the episode memory, all for alert latency already bounded by A0's ~+10 min retry horizon. 300 s keeps the cadence inside the existing catalog class (`registry.py:129/:135`) |
| Production store authoritative + sha256-bound file exports for ephemeral-profile records (§2.1b) | Pilot-DB-only records | a LIVE claim whose evidence dangles after `down -v` is a qualification artifact without durable evidence (decision 9 generalized); the export step makes every phase's landing refs verifiable from the committed tree |
| One shared backup entrypoint for drill and timer (§3.3/§5.5) | A standalone timer script beside the drill's inline shell | two implementations fork exactly the code path AT-32's proof rests on — the nightly proof would validate whatever the timer runs while the drill exercises something else |
| Evidence file for the all-gates run record | A DB row | tests run against ephemeral databases; the durable record must survive them (the T031 evidence convention) |
| G qualifies C/D/F adapters | G builds/rebuilds the live adapters | R-12.11's wiring is phase-owned (C §5, D, F); a second adapter lineage would fork the fail-closed switches G exists to prove |
