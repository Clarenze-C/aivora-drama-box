# Phase G fact map — GLM swarm, 14 Nov 2026 (read-only; no files written)

Paths: `S/` = `microdrama/src/microdrama/`, `M/` = `microdrama/migrations/`, `X/` = `microdrama/tests/`, all under `/root/AIVORA/drama-box` (branch `feat/microdrama-m0-m4` @ `f8aef1a`). **WT** = exists only in a worktree, **not merged**: `.scratch/a0d-gateway` (branch `feat/a0d-gateway` @ `6974d5a`, contains A0-D), `.scratch/t031-r5` (branch `feat/t031-r5`), `/root/.claude/.claude/worktrees/a0r1-airoute` (branch `worktree-a0r1-airoute`, claude-configs).

G's obligation (SPEC-v3.md:884): V3-AT-14, 17, 32 (composed restore), **34** (all-gate end-to-end composition), AT-28's live half, LIVE §16.3; R-IDs R-11.1, R-12.10, R-12.11, R-12.13 (SPEC-v3.md:936).

---

## 1. Backups / restore today (§12.5 → §10.6)

§12.5 is a pointer only — SPEC-v3.md:818-820: "See §10.6." §10.6 requires: "Backup consistency: DB + objects + provenance, with a proven restore before domain activation" (SPEC-v3.md:735) and "**Phase G completes and qualifies this composition** (A builds the skeleton)" (SPEC-v3.md:736).

| Surface | What it does today | Cite |
|---|---|---|
| T046 drill backup | `pg_dump` of postgres + `tar` of the object-store volume, into `deployment/staging/drill-logs/` | `microdrama/deployment/staging/drill.sh:115-119` — `$COMPOSE exec -T postgres pg_dump …` + `tar cf - -C /data objects` |
| T046 drill restore | Fresh compose project (port 8092), `psql -v ON_ERROR_STOP` the dump, app up, then verify `/health` + owner login + the same season's intake page | drill.sh:121-141 |
| Nightly coverage | Runbook step only, NOT executed: "Add the staging PostgreSQL volume + object-store volume to the nightly restic set …, or run the drill's backup step on a timer" | `deployment/staging/DOMAIN-RUNBOOK.md:33-35` |
| DB-restore test | `pg_dump --format=custom` → `pg_restore` into a fresh DB; pre-0019 checkpoint rows + migration state asserted | `X/integration/persistence/test_migrations.py:252-281` |
| Provenance | No separate provenance backup: provenance rows (`asset_lineage`, `rights_registry`, `charges.receipt`) live in the DB, so pg_dump covers them; object tar covers bytes only | M/0003:99-124 (`receipt jsonb NOT NULL — contracts.UsageReceipt`) |

**Resume-after-restore mechanisms that exist (all DB-durable, so restored with the dump):**

| Mechanism | Decisive line | Cite |
|---|---|---|
| schedule_state | "Only prevents busy-spinning … effect dedupe stays with the jobs table's semantic keys, so lost rows can never double-fire an effect." | M/0017_schedule_state.sql:2-3; reader `S/scheduling/service.py:57-59` |
| Scheduler catch-up | "firing state (`schedule_state` rows) only prevents busy-spinning; missing state can never duplicate an effect because the semantic keys dedupe." | `S/scheduling/service.py:18-21` |
| Job enqueue | "Enqueue is idempotent on `semantic_key`: the same type and input return the existing job" | `S/core/jobs.py:6` (insert-or-return at :368) |
| Outbox | "Delivery is at least once. `OutboxDispatcher` may publish an event again after a crash between publish and commit; consumers dedupe with `consume_once`" | `S/core/events.py:5-7` |

**Notification-ambiguity handling today:**

- Publishing: "A timeout or ambiguous response after submission is `UNKNOWN`/`NeedsReconciliation`" (`S/contracts/providers.py:4`); recovery lookup by client token — "NOT_FOUND = safe to resubmit" (`providers.py:200`); the scheduler "proposes the reconcile job for slots whose submit went ambiguous" (`S/scheduling/service.py:20, 636-669`).
- The Dramabox Bot's own ambiguity rules (§3.3: durable outbox, one event per source event, ambiguous send retried at most once and flagged, dead letter, provider message IDs — SPEC-v3.md:203-208): **NOT FOUND** — no bot/Telegram/alert implementation exists in `S/` (grep `telegram|alert`: zero hits). Bot events are phase A's AT-16; G's AT-14 alert consumes them.

**Restore gap vs AT-32** ("Restore DB and objects together; resume scheduler/outbox/jobs without duplicate effects. Document notification ambiguity honestly" — SPEC-v3.md:923): the drill's restore verification stops at health/login/page-read (drill.sh:130-140); no step resumes scheduler/outbox/jobs after restore and proves no duplicate effects; no artifact documents restore-time notification ambiguity. The drill's worker/janitor drain (step 5, drill.sh:110-113) runs **before** the backup, not after the restore.

---

## 2. All-gate composition today (V3-AT-34)

No test composes all gates A–G (**NOT FOUND**; expected — G owns AT-34). Closest composed acceptance runs:

| Run | Composes | Cite |
|---|---|---|
| `make pilot` (T029 demo) | "proposal → Gate 1 → episode → fake render → real FFmpeg edit → QA → Gate 2 (identity lock) → fake publish → social → analytics → janitors"; refuses outside OFFLINE_MOCK | `microdrama/Makefile` pilot target; `S/pipeline/demo.py:1-14` |
| `X/integration/pipeline/test_full_mock_path.py` | Same whole path as one test: "exactly two human decisions, real playable FFmpeg exports, fake-labeled posts … GPU gone before the human wait" | :5-8 |
| `X/integration/pipeline/test_scheduler_driven_path.py` | Scheduler-driven variant of the path (W01–W12 from durable state) | file header |
| `X/integration/validation/test_t047_v2_composed_acceptance.py` | "candidates → Gate 1 → production stages → owner metadata manifest → Gate 2 → scheduled posts", records-vs-media QA, dispatch boundary fail-closed | :1-15 |
| `X/integration/pipeline/test_t045_canary_composed.py` | Composed paid-benchmark acceptance (offline lanes), 86 KB | file |
| `deployment/staging/drill.sh` (T046) | Ops-level: up → owner → intake → restart durability → worker → backup → restore | drill.sh:2-3 |

All providers in these are T007 fakes. The one live-effect composition seam is render-only: `S/pipeline/live_world.py:1-3` — "Explicit, effect-gated composition for a T045 paid benchmark. Construction wires clients and services but performs no provider I/O." No composition wires LLM+image+voice+render+publish with per-provider credentials (§10.6's qualified production composition) — see §7.

---

## 3. `dramabox-llm` + Pro off-pace (V3-AT-14)

AT-14: "`dramabox-llm` refuses while Pro is off pace, and production pauses with a bot alert rather than switching providers silently" (SPEC-v3.md:905).

| Piece | State | Decisive line | Cite |
|---|---|---|---|
| ai-route strict role `dramabox_llm` | Built, **WT-only, NOT merged into `/root/.claude` main**; live `models.json` has **no** `dramabox_llm` role (roles: plan, goldfish, build, build-luna, swarm, critique, review, fast) | "Week pace below the minimum → `REFUSED` / `PACE_WEEK` … Every refusal is pre-launch: `launched=false`." | Spec table phase-A0-spec.md:145-148; impl `/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py:1911` (`return "PACE_WEEK", week_reset_ms …`), config :1240, quota windows :1864; merge check: `grep -c dramabox_llm /root/.claude/scripts/ai_route.py` = 0 |
| Refusal → DeferReason mapping | Built (WT) | `{"QUOTA_UNREADABLE", "QUOTA_5H", "PACE_WEEK", "CONCURRENCY"} → DeferReason.*` | WT `S/llm/step.py:68-73` |
| §5.7 composition gate | Built (WT) | "the paid-external effect authorised, the subscription route selected, and the gateway healthy with the expected policy identity" — checked at startup and every dispatch | WT `S/llm/step.py:351-364`; `LlmRouteDisabled` :77-82; "The legacy `LLMProvider` path refuses `MICRODRAMA_LLM_ROUTE=subscription`" phase-A0-spec.md:380 |
| Production pause + bot alert | **NOT FOUND** | `LlmStep` only defers (`clamp(retry_at − now, 60 s, 6 h)`, phase-A0-spec.md:288) or blocks after 10 transport failures (`MAX_TRANSPORT_FAILURES = 10`, WT step.py:57) | No production-world pause wiring exists; `build_production_world` **NOT FOUND** anywhere (named as "phase A's" entry point in phase-A0-spec.md §5.7) |
| Gateway host service | Built (WT), operator-install pending | "stdlib-only Python service … accepts LLM invocations over an HTTP API on a Unix socket, durably records every launch step, runs each attempt in its own transient systemd unit" | WT `microdrama/deployment/llm-gateway/gateway.py:1-5` + `install/dramabox-llm-gateway.service`; INSTALL.md:5 "installed by the operator from these tested files"; architecture diagram phase-A0-spec.md:51-59 (worker → `/run/dramabox-llm/gw.sock` → gateway → systemd-run → ai-route → claude) |
| Quota metering (LLM) | Built (WT, LLM-only) | `quota_observations`: 5h/week before/after bp, resets, `unreadable`, `concurrent_jobs_ms`, `uncertainty` | WT M/0027_a0_llm_gateway.sql:106-118; writer WT `S/llm/step.py:203-215, 333-336` |
| Status | A0-D round-2 Codex = **FIX-REQUIRED**, stopped per rule 7 → OPERATOR QUEUE; no merge | | WEEKEND-GLM-RUNBOOK.md:104 (Q1), :109 (Q6 A0-R1, same queue) |

---

## 4. LIVE pilot scaffolding (V3-AT-17)

AT-17: "P0/P1/P2 pilots complete; `PILOT-REPORT.md` has measured per-episode cost and quota per provider" (SPEC-v3.md:908).

- **Pilot phases** (SPEC-v3.md:755-761, "in an isolated pilot profile"): P0 = full-season planning (steps 1–3, 24 eps) + reduced step 4 + **Nano Banana lock-throughput measurement**; P1 = 1 full episode (after T031 qualifies) + mixed-emotion exit check; P2 = 3 more episodes + **throughput vs §9.4 SLO**. No isolated pilot profile exists in `deployment/` (only the staging compose) — **NOT FOUND**.
- **`PILOT-REPORT.md`**: spec-defined contents only (measured vs forecast; cost per episode by provider cash/allocation/estimate; quota per episode; planning wall-clock, quota-pause counts, window pacing N12; throughput; §16.3 quality; frozen-workload LLM comparison; recommendation — SPEC-v3.md:763-773). No generator, template or artifact in the repo — **NOT FOUND** (grep `PILOT-REPORT`: spec + review docs only).
- **Screen/full convention (T031)**: screen = 3 samples `S01-R1, S03-R1, S07-R1` ("Start with S01-R1, S03-R1 and S07-R1 as a three-sample screen included in the 24" — T031-benchmark-packet.md:117; ids in WT `S/rendering/benchmark_experiments.py:16`); full admission from screen results ("Proposed screen continuation: all three samples technically complete and no critical speech/control defect" — packet:147-148; "the remaining full run fits is **reported from measured screen throughput**" — T031-run-readiness-spec.md:499).
- **Benchmark live seams (T031/T045 lineage):**
  - Offline benchmark drives the real paid pipeline shape against fakes: `S/rendering/presets_benchmark.py:2-6` ("driving the REAL paid pipeline end to end … against the T007 fake server"), cold/warm split :10-16, "outside OFFLINE_MOCK this tool refuses to run" :24.
  - Canary runner (T045 R11, reused by T031): `S/pipeline/canary.py:2-4` preflight/execute/invoice; execute "refuses on a sha mismatch, a passed hard stop, an expired quote, a mode other than PAID_BENCHMARK … and a cap above the episode cap" :10-13; "Ambiguity stops for a human and is never retried blind" :13-14; the default credential resolver refuses — "T031 supplies the real one under the operator's authority" :15-16.
  - Live render composition: `S/pipeline/live_world.py:1-3` (T045, render/RunPod only).
  - R5 run-readiness (built 13 Nov, Codex-review pending, unmerged): WT `.scratch/t031-r5` `S/rendering/benchmark_experiments.py:1` "Durable T031 coordination. No provider calls or secondary money ledger live here"; `UnresolvedItem` kinds U1–U6 derived from reservation/lease/job/operation linkage :18-27.
  - Paid run still operator-gated: $8 sign-off, image, weights, references, voices (HANDOFF.md, 12 Nov 05:40Z entry; image `ghcr.io/clarenze-c/drama-pika-h3-flex@sha256:e4ccc004…` pushed).
- **Cost/quota metering per provider today:**

| Table / module | Covers | Cite |
|---|---|---|
| `charges` | Per-provider spend: `provider`, `provider_receipt_id`, `cost_basis` ∈ SYNTHETIC_FAKE/PROVIDER_REPORTED/BILLED, `amount_micro_usd`, job/season/episode/pod_lease, `UNIQUE (provider, provider_receipt_id)` | M/0003:99-124 |
| `S/analytics/cost.py` | Effective cost truth rules: failed spend retained, committed counts, research attribution, published minutes | :1-24 |
| `pod_usage_intervals` + `runpod_billing_*` | GPU seconds and RunPod invoice reconciliation/finality | M/0003:195-210; M/0022, M/0025 |
| `quota_observations` | LLM subscription quota only (WT, see §3) | WT M/0027:106-118 |
| Quota for Nano Banana / ElevenLabs / YuE2 / RunPod | **NOT FOUND** — no QuotaObservation equivalent outside the LLM gateway | grep `QuotaObservation|quota_observation`: only WT llm |

---

## 5. Cross-system Nano Banana lock — live half (V3-AT-28)

AT-28: "Competing ARISA/Drama container processes share the same lock; crash/restart cannot allow overlapping provider processes" (SPEC-v3.md:919). Design (phase C, unbuilt): phase-C-spec.md:365-395 — flock + inode pinning + durable recovery admission + fairness; :409-411 — shared inode is ARISA's file, "Drama never creates a second lock file."

**ARISA side (read-only, verified today):**

| Fact | Detail | Cite |
|---|---|---|
| Canonical lock file exists | `/root/AIVORA/arisa/studio/sfw/vertex-generation.lock` (98 bytes) | `ls` verified |
| Lock primitive | Opens the file `'rb'`, `fcntl.flock(LOCK_EX \| LOCK_NB)`; `BlockingIOError` → `ProviderQuotaError('shared Vertex generator busy', retry_after=20)`; unlock in `finally` | `/root/AIVORA/arisa/studio/sfw/recovery.py:88-105` |
| Sole non-test call site | Wraps **transport only**: `with provider_generation_lock(): response = self.transport(payload)` — lock is **not** held through final poll, and there is no recovery admission | `/root/AIVORA/arisa/studio/sfw/providers/google_vertex.py:184-185` |
| Inode pinning (ARISA-side) | Staging pin checks `lock.stat().st_ino==shared.stat().st_ino` and hardlinks the lock into staging | `arisa/studio/sfw/deployment/pin_batch_runtime.py:44, 62-63` |
| Recovery-admission protocol on ARISA | **NOT FOUND** (grep `recovery_admission` in `arisa/studio`: zero) | — |

**Drama side:** **NOT BUILT.** `cross_process_generation_lock` and `PROVIDER_LOCK_BUSY` **NOT FOUND** in the main repo or any worktree (phase C/C3 unbuilt; spec drafts queue order is C, F, E, G, D — WEEKEND-GLM-RUNBOOK.md:95, Q7 :110). Drama's staging compose binds no ARISA paths (only named volumes `staging-pg`/`staging-objects` — `deployment/compose.staging.yaml:19-66`); PC5-2 requires binding the canonical **parent directory**.

**What a live AT-28 test needs:** (a) C3's lock implementation + `PROVIDER_LOCK_BUSY` defer (C-owned prerequisite); (b) ARISA-side adoption — shared recovery-admission protocol + submit-through-final-poll hold ("ARISA-side adoption is a prerequisite for live image jobs", SPEC-v3.md:697; coordinated with the ARISA owner); (c) mount topology where canonical-path replacement is visible, with the `fstat`-vs-pinned-inode check against a `provider_qualifications` row (phase-C-spec.md:372-385) — but `provider_qualifications` is **NOT FOUND** in any migrations (A6 pending; only `capability_registry`/`rights_registry`/`preset_registry` exist, M/0006); (d) two live container processes (ARISA workspace bind + drama compose) with crash/restart choreography — C-T6's kill-after-admission-before-submit scenario is the template.

---

## 6. Throughput measurement (§16.3 / MA11 / §9.4)

- SLO: "**≥ 1.25 approved episodes per day** at cost ≤ cap … Catch-up: ≥ 2/day for 2 days … Buffer: ≥3 days … the bot alerts below 2 … Measured: P2 and live operation" (SPEC-v3.md:616-623). LIVE acceptance: "Throughput ≥ the §9.4 SLO at cost ≤ cap" (SPEC-v3.md:969), thresholds operator-confirmed from P1/P2 and signed in `PILOT-REPORT.md` (:959-960).
- Code tracking: **NOT FOUND** — `throughput` has zero hits in `S/` (independently re-verified). `performance_snapshots` is **post** performance (H24/H72/D7 windows per platform_post, `S/analytics/snapshots.py:45-80`), not production rate. No approved-episodes/day counter, no buffer counter, no bot-alert consumer. (Matches the F fact map's independent conclusion, `docs/microdrama-system/v3-workflow/f-factmap.md:91-93`.) §16.2 also conditions LIVE claims: "LIVE qualification is claimed per destination. Destinations held by T032 stay `HELD`" (SPEC-v3.md:951-955).

---

## 7. Gaps — what G needs that doesn't exist today

| # | Gap | State | Nearest existing seam |
|---|---|---|---|
| 1 | Dramabox Bot + §3.3 durable outbox (Telegram) | Absent entirely (incl. AT-14's bot alert, "throughput below SLO" event, budget alerts) | `S/core/events.py` transactional outbox + `event_dispatches` (M/0001:133) is a different, internal mechanism; AT-16 is phase A's |
| 2 | Production pause wiring (AT-14 second half) | `build_production_world` NOT FOUND; no pause propagation from LLM defer/block to scheduler; no alert | LlmStep defer/block vocabulary (WT `S/llm/step.py`) |
| 3 | `dramabox_llm` role live in ai-route | WT-only, unmerged; live `models.json` lacks the role; gateway unit not operator-installed; A0-D/A0-R1 both in OPERATOR QUEUE after FIX-REQUIRED/round-2 | ai_route.py worktree; `deployment/llm-gateway/install/INSTALL.md` |
| 4 | §10.6 qualified production composition | Staging serves OFFLINE_MOCK only — serve "REFUSES any non-OFFLINE_MOCK mode (staging cannot serve a live composition until T045/T031)" (`microdrama/evidence/T046.md:7-9`); `live_world.py` wires render only | `S/pipeline/live_world.py`; effect flags in `S/config.py:27-50` (`paid_requests_enabled` … default False); DB mode gate `md_runtime_mode` ∈ OFFLINE_MOCK/PAID_BENCHMARK/CONTROLLED_ACCOUNT_TEST/PRODUCTION with fake-evidence guard (M/0008:65-95) |
| 5 | Composed restore proof (AT-32) | Drill stops at health/login/page after restore; no jobs/outbox/scheduler resume proof; no notification-ambiguity documentation artifact; objects via tar (restic only as an unexecuted runbook step) | drill.sh steps 6–7; idempotency surfaces in §1 |
| 6 | All-gate composition test (AT-34) | Nothing crosses all gates with live surfaces | `make pilot` + `test_t047_v2_composed_acceptance.py` are the skeletons |
| 7 | Cross-system lock live half (AT-28) | C3 unbuilt; ARISA lacks recovery admission + hold-through-final-poll; no `provider_qualifications` table; no bind topology | phase-C-spec.md:365-411; ARISA `recovery.py:88-105` |
| 8 | Throughput + buffer counters (§9.4) | None | W03 cadence + `episodes` durable state are the raw material |
| 9 | `PILOT-REPORT.md` generator/template | None | §11 content list (SPEC-v3.md:763-773); `charges`/`cost_allocations`/`quota_observations` are the data sources |
| 10 | Non-LLM provider quota observation | None | — |
| 11 | LIVE quality-measure capture (§16.3: Thai ASR ≥90% lines, face identity ≥95% shots, 0 CRITICAL continuity, Gate-2 ratings ≥90% shots, mixed-emotion ≥80%) | QA chain exists (W07 "technical → observation → comparison → repairs → package", `S/scheduling/service.py:17-18`); operator rating capture + the signed report flow NOT FOUND | QA findings tables (`qa_findings`, `qa_observations`) |
| 12 | Live providers still to wire (R-12.11, "Mostly NEW" — REQUIREMENTS.md:190): LLM, trend research, image, ElevenLabs, YuE2, SFX, Pika (T031), publishing (T032), analytics | Only render (T045 canary lane) has a live composition | `live_world.py`; adapter table SPEC-v3.md:699-711 |
| 13 | Migration numbering | Main ends at 0025; WT A0-D claims 0027; A1 note claims 0028–0031 | G's migrations start after the A-line lands |

**Context for the spec writer:** G builds on unmerged lines — A0-D (`feat/a0d-gateway`, OPERATOR QUEUE), A1 (note in OPERATOR QUEUE), C (spec draft pending, queue position 1 of C/F/E/G/D). The weekend runbook forbids building C–G this weekend (WEEKEND-GLM-RUNBOOK.md:110); this fact map is Q7 step (1) for G.
