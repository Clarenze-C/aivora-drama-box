# Automated Thai Micro-Drama — V2 Task Breakdown

Version 2.0 · 28 October 2026 · Executes [SPEC.md](SPEC.md) v2.0. Current code contracts remain 1.6.0 until the V2 contract task is accepted.

T001–T030 are historical accepted V1 software tasks. The [26 October remediation record](../../microdrama/evidence/build-review-2026-10-25-remediation.md) closes the prior F01–F09 review. The current full offline check fails at the fixed-date human-session integration fixture (V2-F12), which T048 must repair. T031–T035 remain pending live/reliability tasks; T036–T048 are V2 work defined by the [current-build review](build-review-v2-2026-10-28.md). A task entry is not an implementation or deployment receipt. A review/plan does not itself launch a pod, spend through providers or post to accounts.

## 1. Orchestrator instructions

Read the SPEC fully, then this file and applicable repository instructions. Current user decisions and the SPEC govern this project; unrelated Arisa/trading/Mission Control task rules are not inherited. Target implementation is the isolated `microdrama/` module; this documentation lives in `docs/microdrama-system/`.

**Development agents are different from runtime story/critic agents.** The team builds the application; application models later execute bounded jobs through its services. Giving a development agent a task does not grant it unrestricted provider spending or public-action authority.

Working protocol:

1. Orchestrator owns integration, shared contracts/schema/API registration, status tracking and task dispatch. Workers edit only claimed paths. Reads can cross modules; writes cannot without reassignment.
2. Begin with no more than three worker lanes plus the orchestrator. Do not dispatch dependent tasks until predecessor acceptance evidence is reviewed and merged. Disjoint paths do not remove semantic dependencies.
3. Complete foundation/contracts/schema first. Freeze contract version and shared file signatures before parallel consumers. A worker encountering a missing field submits a contract-change proposal; it cannot invent a local incompatible schema.
4. Use isolated branches/worktrees if available and appropriate. If sharing one checkout, claim file ownership and serialize shared mutations. Never run conflicting whole-repository formatting/migration generators from different agents.
5. Only the integrator edits root dependency/lock files, `contracts/`, migration ordering, application route/job registration, deployment compose or this task status ledger unless explicitly assigned a foundation task. Module owners export factories; they do not register themselves in shared roots.
6. Each task returns a bounded handoff: task ID, files changed, contract version, evidence commands/results, implementation limits, external prerequisites, cost/public-action effects (normally none), and proposed next tasks. Never claim a future target command was executed.
7. Default all implementation/test runs to mock/offline mode. Fake responses must be labeled and must not report real rendered quality, cost or public URLs. Live-task activation requires actual configured credentials/rights, authorized spending and appropriate application Gate 1/Gate 2 records. Missing external prerequisites block only affected work; continue offline tasks.
8. A validator/reviewer independent of the implementing task checks cross-module invariants. Fixes return to the owning lane; do not let an audit agent modify multiple owners' code concurrently.
9. No mandatory new routine creative human gates. Integration reviews and contract freezes are engineering checkpoints; runtime keeps season approval plus final-episode approval only.
10. Do not mark the overall system complete because scaffolds, imports or mock flows pass. Track software integration, real provider qualification, first episode and ten-episode qualification as separate milestones.

Model assignment: use the session's permitted models and available specialist roles; no task hardcodes an unverified API model ID. A permitted less expensive model such as GPT-6 Luna can handle bounded source checks, fixture preparation or documentation. Assign transactional budget/state/recovery work and final integration review to an appropriately capable agent. Production Claude writer/model choices are runtime configuration under the SPEC.

## 2. Roles, ownership and shared contracts

Roles are logical specialties, not a requirement to launch all of them simultaneously. Reuse at most three active workers as dependencies permit.

| Lane | Exclusive primary paths below `microdrama/` | Responsibility |
|---|---|---|
| Integrator / contract guardian | Root scaffold/config/locks; `contracts/`, `migrations/`, `persistence/`, `api/`, `workers/`, final registration | Bootstrap, schemas, shared repository/queue integration; assign sequential subtasks |
| Core / cost | `src/microdrama/core/`, `src/microdrama/budget/` | State/auth/job/outbox/idempotency and exact spending; run core/cost tasks sequentially if shared tests overlap |
| Story / references | `research/`, `story/`, `references/` | Provenance, original writing/canon/playbook and versioned image/voice assets |
| GPU | `rendering/` | Pod lifecycle, Comfy submission, presets/routing, janitor and benchmark tools |
| Media / QA | `editing/`, `qa/` | FFmpeg/captions/hooks, actual-media analysis, blind review and repair planning |
| Review | `review/` | Two-gate routes/UI, feedback capture and media/policy-bound review package |
| Distribution | `publishing/` | Capability-specific adapters, release DAG, schedule and reconciliation |
| Social / membership | `community/`, `memberships/` | Bounded metadata/replies/DM/moderation/entitlement/catalog services |
| Analytics | `analytics/` | Attribution, cost/intervention reports and ten-episode qualification |
| Validator / operations | Assigned `tests/integration/`, `deployment/`, `evidence/` after registration freeze | Fault tests, isolation, redacted evidence and live-readiness audit |

Module tests live in `tests/unit/<module>/` and `tests/contract/<module>/`; do not share one catch-all file across workers. Integrator owns common fixtures/protocols, integration fixtures and global test configuration. During task handoff, reassign a path explicitly before a new worker changes it.

Service directory names in lane/task descriptions are shorthand for `src/microdrama/<module>/` beneath the implementation root. Schema, test, deployment, workflow and documentation paths are relative to `microdrama/` unless explicitly placed in `docs/microdrama-system/`.

Canonical contract groups are in SPEC §4.2. Any change states downstream impact, migration/compatibility handling and tests; guardian versions it and notifies affected lanes before resumption. Environment setting names and provider interfaces are frozen alongside schema, not independently guessed by each adapter.

## 3. Milestones and dispatch waves

Waves express readiness, not mandatory batches; tasks may start earlier only when every declared dependency is satisfied and file ownership permits. No wave completion is human approval to publish.

| Milestone | Tasks / dispatch guidance | Exit evidence |
|---|---|---|
| M0 Contracts ready | T001 → T002 → T003; T007 can follow T002 independently | New module exists; schemas/interfaces/examples and migrations accepted; mock mode denies external effects |
| M1 Runtime invariants | T004, T005, T006, then T008; independent T007 | State/outbox/approval boundaries, transactional budget, registry and minimal gate interface pass meaningful tests |
| M2 Production services | Story T009 → T010 → T011; GPU T012 → T013; media T015 → T016/T017 → T018; T014 once its dependencies pass | Accepted module handoffs, complete fake media flow, real-provider mode still disabled |
| M3 Distribution/social | T020 → T021/T022/T023/T024; T025 and T026 after their dependencies; T019 feedback repair | Supported adapters implemented offline, one release protocol and no speculative capabilities enabled |
| M4 System integration | T027, T028 → T029 → T030 | Full two-gate mock path, isolated queues, retries/cost/approval/security/fault evidence |
| M4.5 V1 correctness | T036, T037 and T048 | Prop/outfit mapping, metadata/rearmed publication recovery, and repeatable offline approval-session tests |
| M5 V1 provider readiness | T045 → T031; T032 follows qualified routes and authorized accounts | Bounded manual Runpod canary plus real V1 adapter/Thai/quality/rights/cost evidence; mock or manual-only success is insufficient |
| M5 V2 production semantics | T038 → T039/T040 → T041 → T042/T043 → T044 → T047 | Canonical V2 contracts, story/asset/shot state, QC/creatives, owner progress and composed mock integration |
| M5 V2 private app staging | T046 after T044/T047 | Authenticated, durable private deployment and restart/progress evidence; proposed domain is not public until separately configured |
| M6 First episode | T033 after T031/T032/T047 | One actual original Thai episode, actual costs, only the agreed runtime gates, supported verified release and management evidence |
| M7 Reliability qualification | T034 → T035 final closeout | Ten consecutive qualifying productions plus corresponding seven-day management windows; honest blocked/pending statuses |

The two-week pilot reaches as far as evidence allows; M7 can require the season's real release cadence and must not be compressed into a false completion claim.

## 4. Task index and dependency DAG

`Size` is relative complexity (S/M/L), not a delivery-time or model-token promise. `Live` means externally gated evidence; an offline implementation milestone may finish before its live evidence does. Required dependencies refer to accepted task deliverables, not merely started work.

| ID | Task | Size | Depends on | Owner |
|---|---|---|---|---|
| T001 | Isolated scaffold and reproducible check commands | M | — | Integrator |
| T002 | Canonical schemas/interfaces and fixtures | L | T001 | Contract guardian |
| T003 | Durable schema/repositories/object-store metadata | L | T002 | Integrator / database |
| T004 | Workflow state, outbox, jobs and idempotency | L | T003 | Core |
| T005 | Atomic US$10 budget/usage accounting | L | T003 | Cost |
| T006 | Config, credential references, rights/capability/preset registries | M | T003 | Core / registry |
| T007 | Deterministic fake-provider/media fixture harness | M | T002 | Validator |
| T008 | Two-gate review APIs/UI and approval binding | L | T004, T005, T006, T007 | Review |
| T009 | Bounded source research/proposals/provenance | M | T005, T006, T007 | Story |
| T010 | Bible/canon/scripts/directing playbook/prompts | L | T004, T009 | Story |
| T011 | Reference/voice pipeline and identity lock | L | T008, T010 | References |
| T012 | Runpod leases/acquisition/cleanup/janitor | L | T004, T005, T006, T007 | GPU |
| T013 | ComfyUI API graph and job recovery adapter | L | T012 | GPU |
| T014 | Shot routing, compatible preset benchmark tooling | M | T011, T013 | GPU |
| T015 | Deterministic FFmpeg EDL/audio/subtitle exports | L | T010, T011, T007 | Media |
| T016 | Platform variants/covers/three hook candidates | M | T015 | Media |
| T017 | Technical, audio/ASR and visual QA | L | T015, T006 | QA |
| T018 | Observation-first comparison and evidence coverage | L | T017 | QA |
| T019 | Targeted repairs and scoped feedback memory | L | T008, T011, T014, T015, T018 | QA / feedback |
| T020 | Release DAG/scheduling/provider protocol/reconciliation | L | T004, T005, T006, T008 | Distribution |
| T021 | YouTube adapter | M | T020, T007 | Distribution |
| T022 | TikTok eligible-provider adapter | L | T020, T007 | Distribution |
| T023 | Instagram adapter | M | T020, T007 | Distribution |
| T024 | Facebook adapter with explicit full/short route | M | T020, T007 | Distribution |
| T025 | Organic agency/community and metadata workers | L | T005, T006, T010, T020 | Social |
| T026 | Membership/early-access catalog and permitted DM delivery | L | T005, T006, T020 | Membership |
| T027 | Metrics/experiments/effective cost/qualification | L | T004, T005, T016, T020, T025, T026 | Analytics |
| T028 | Queue isolation/shared rate limiter/worker runtime | L | T004, T005, T012, T020, T025 | Integrator / workers |
| T029 | In-app scheduling/composition/complete two-gate mock workflow | L | T008–T028 | Integrator |
| T030 | Independent invariants/fault/security/readiness validation | L | T029 | Validator |
| T031 | Real rights/Thai quality/GPU cost/provider configuration qualification | L / Live | T014, T018, T030, T045 | GPU + QA + registry |
| T032 | Controlled real publication/community/membership tests | L / Live | T021–T026, T030, T031, T037 | Distribution + social |
| T033 | First actual end-to-end episode and asset lock | L / Live | T031, T032, T047 | Integrator |
| T034 | Ten-episode production and seven-day management qualification | L / Live | T033, T027 | Operations + analytics |
| T035 | Final traceability, evidence and operational handoff | M | T030, T031, T032, T033, T034, T046 | Integrator + independent reviewer |
| T036 | Correct V1 prop/outfit routing and pin draft-to-render regression | M | T010, T011 | Story / references |
| T037 | Repair W09 absent-post rearm and remove live mock metadata fallback | M | T020, T030 | Distribution |
| T038 | V2 contract/kit crosswalk, migrations and compatibility | L | T002, T030 | Contract guardian |
| T039 | Three-step Script Maker, candidate concepts, rich bible and episode packs | L | T038, T009, T010 | Story |
| T040 | Style/asset sheets and per-character wardrobe/prop/location state | L | T038, T039, T011 | References |
| T041 | Typed shot state/reference resolver and prompt compiler | L | T036, T038, T039, T040, T014 | Story + references + GPU |
| T042 | Keyframe preflight and actual-media continuity coverage | L | T041, T017, T018 | GPU + QA |
| T043 | Poster, optional preview and creative lineage | M | T039, T040, T016 | Media |
| T044 | Owner workbench and durable progress projection | L | T038, T041, T042, T043, T008 | Review + API |
| T045 | Real Runpod/Comfy/provider composition and paid benchmark path | L / Live-ready | T036, T048, T012, T013, T030 | GPU + integrator |
| T046 | Private staging/deployment and proposed domain readiness | M | T044, T047 | Operations |
| T047 | Independent V2 composed mock/fault acceptance | L | T036–T044, T048 | Validator |
| T048 | Time-independent integration pilot fixture and approval regression | M | T030 | Integrator + validator |

Ranges mean every task in the inclusive range. T029 requires all T008 through T028; T032 requires T021 through T026 plus T031/T037; T047 requires T036 through T044 and T048. Do not infer that T045 launches a pod: it builds the live-capable path; T031 contains the bounded authorized canary and measured qualification. No consumer redefines shared contracts merely because another lane is still busy.

## 5. Detailed work packets and acceptance

### T001 — scaffold and checks

- **Writes:** root project files, base `deployment/compose.local.yaml`, empty package boundaries and test configuration. No production ports/accounts inherited from other services.
- **Build:** isolated package, pinned supported dependencies, config/mock execution mode, reproducible local DB/Redis/private-storage services, standard future make targets from SPEC §13.
- **Accept:** new module imports/builds; `make check` runs documented offline checks; paid/cloud/public-action switches default off; local test resources do not alter existing AIVORA services. Record actual dependency choices.

### T002 — contracts and interface freeze

- **Writes:** `contracts/`, exported protocol/type definitions and valid/invalid examples; guardian-owned compatibility notes.
- **Build:** all SPEC §4.2 payloads, money/time/hash/error/state conventions, provider submit/status/reconcile interfaces and minimum service route/job signatures. Version zero-cost fake usage separately from measured receipts.
- **Accept:** schemas reject malformed/stale/unsupported required controls; all consumers have examples; serialize/hash deterministically; expected approval revisions/idempotency included; missing evidence/coverage stays representable as unknown. `make contracts` and contract tests pass.

### T003 — persistence

- **Writes:** ordered `migrations/`, `persistence/`, storage metadata adapter, database integration tests.
- **Build:** SPEC entity groups, semantic unique keys, optimistic revisions, transaction/outbox support, immutable approval/observation records and object lineage. Initial schemas serve offline implementation; do not apply them to unrelated live DBs.
- **Accept:** fresh create/upgrade/restart round trip succeeds in isolated test DB; duplicate semantic jobs/slots are rejected; private asset references/hashes survive process restart. Shared migration/API signatures freeze before dependent work.

### T004 — deterministic core

- **Writes:** `core/` state/jobs/outbox/auth primitives; core-local tests.
- **Build:** transitions, retries/cancel/failure types, capability and approval hooks, durable job claims, outbox consumer dedupe and semantic idempotency.
- **Accept:** only valid transitions occur; crashes/replays resume without repeated semantic work; worker/model principals cannot write human approvals; typed uncertainty does not become success. AT-02 foundations pass using fixtures.

### T005 — budget service

- **Writes:** `budget/`, cost-local tests.
- **Build:** exact micro-USD reservations/accruals/settlements, research/setup allocation, failed job charges, protected reserves, bounded provider estimates and observed-overrun reporting.
- **Accept:** AT-01 under genuine concurrent transactions; no reset on new attempt/job name; in-flight shared reservations cannot double-spend; GPU interval attribution counted once; metered management cannot consume committed render/shutdown funds; unknown price blocks dispatch. Never stub budget checks with an always-true function.

### T006 — configuration and evidence registries

- **Writes:** assigned `core/registry/` and config submodule; registry-local tests. Coordinate directory ownership with T004; no overlapping edit sessions.
- **Build:** rights territories/commercial scope/expiry, account capabilities/version/readback coverage, preset compatibility and credential-store references. Import accepted policy as settings, not proof of provider readiness.
- **Accept:** unknown/ineligible/unexpired-versus-expired distinctions work; missing required rights/account controls block execution despite green QA; credentials never appear in UI/model payloads/evidence logs. AT-13 registry cases pass.

### T007 — fakes and media fixtures

- **Writes:** guardian-assigned common fixture/fake directories; no changes to other modules.
- **Build:** deterministic source/model/Runpod/Comfy/publisher/DM/payment fakes with timeout/duplicate/denied/late-billing cases. Supply small original or licensed sample media and seeded caption/audio/video defects. No copyrighted film clips or private customer records.
- **Accept:** strict offline mode catches accidental paid/public network calls; fixtures label synthetic/unmeasured provenance; complete and partial media outputs distinguishable; replay scenarios reproducible.

### T008 — review and the two gates

- **Writes:** `review/` routes/templates/local tests, exported registration factory only.
- **Build:** season package approval and episode review with actual media, subtitles/variants/covers/cast anchors, QA coverage, costs and policy preview; approve/revise/reject with timecodes.
- **Accept:** authenticated owner actions only; stale/hash-mismatched package cannot approve; replay idempotent; no auto-approval timer; material media changes invalidate; metadata policy changes within already approved scope are distinct. Include identity-lock service hook, implemented by T011, without hardcoded bypass. AT-02.

### T009 — original research

- **Writes:** `research/` and local tests.
- **Build:** bounded source adapters, provenance/date/source-quality ledger, comment/theme dedupe, originality/ressemblance screening and season proposals. Shared preapproval research consumes a real configured reservation.
- **Accept:** source failure/missing data remains unknown; comments cannot override policy; rejected proposals retain spend; repeated schedule triggers do not reset research allowance; generation never copies comparator scenes/personas. Mock citations distinguish actual sources from fixture URLs.

### T010 — story/canon/playbook compiler

- **Writes:** `story/` and local tests; read shared directing example as input, not a writable global library.
- **Build:** approved-scope bible/arc compilation, exact Thai lines/translations, actual/estimated timing contracts, structured shot manifests, six directing patterns, canon/character-knowledge checks and bounded complexity rewrite.
- **Accept:** planned/final/published facts separate; unsupported staging is simplified without losing the specified dramatic change; every shot has required playbook/routing fields; later trend evidence cannot silently change approved arc; critic failure consumes budget and terminates at limit. IMP-02.

### T011 — recurring references/voices/identity lock

- **Writes:** `references/` and local tests; consume T008 lock hook without editing its implementation files.
- **Build:** eligible image/voice adapters, full-key caching, character/outfit/set anchors, actual dialogue durations, provisional/accepted/locked versions and dependent invalidation.
- **Accept:** episode-one Gate 2 atomically locks only included reviewed asset versions; later render request before lock is denied; new/unseen cast does not inherit a lock; explicit changes version references and use ordinary final gate. Live Thai quality is T031 evidence, not this mock acceptance. AT-03, IMP-01.

### T012 — pods and independent janitor

- **Writes:** `rendering/pods*`, `rendering/leases*`, `rendering/janitor*` and corresponding tests/tools.
- **Build:** allowed hardware/price/RAM filters, deployment ID/tag reconciliation, health/warmup, timed owned lease, actual cost accrual, durable asset completion hooks and independent cleanup command/process.
- **Accept:** fault tests for ambiguous create, unavailable GPU, dead worker, expired heartbeat, budget stop and shutdown failure; no orphan/duplicate acquisition in fake scenarios; cannot stop unrelated resources; no GPU left waiting on human. Real resources are T031 only. AT-04.

### T013 — ComfyUI adapter

- **Writes:** `rendering/comfy*`, `rendering/workflows/`, Comfy-local tests.
- **Build:** API-format graph validation/parameter binding, actual node capability checks, submit/store `prompt_id`, websocket progress plus history/status recovery, complete asset fetch/checksum.
- **Accept:** UI graph is not mistaken for runnable API payload; reconnect does not rerender an existing completed job; sampler progress is not treated as complete saved audiovisual output; malformed/missing nodes produce typed errors without arbitrary installation. AT-04.

### T014 — compatible quality routing and benchmark tooling

- **Writes:** `rendering/routing*`, `rendering/presets*`, redacted benchmark command/tools and local tests.
- **Build:** fast/quality/control preset registry, shot-hard-control filter, routing by quality/accepted cost, ordinary retry accounting and per-class latency/rejection receipts.
- **Accept:** rejects a fast text-only route when references are required; failure-driven tier promotion uses existing attempt cap; ranks total accepted cost rather than advertised speed; cold/warm/full-job timings distinguished. Tool exists offline; enabling real presets requires T031 evidence. IMP-03, AT-07.

### T015 — deterministic editing/captions

- **Writes:** `editing/` core EDL/audio/caption/export modules and local tests, excluding T016-owned variant/hook modules.
- **Build:** explicit source/timeline cuts, normalization, continuous room/audio mix, Thai-safe font handling, actual-speech alignment/caption spotting and clean/burned exports through argument-safe FFmpeg invocation.
- **Accept:** local original fixture video completes automatically; duration/gaps/audio/cue timing/Thai rendering inspected through technical checks; source-line replacement invalidates associated cues; no fake correction by writing intended words over wrong audio. Avoid broad whole-system CPU workloads on existing shared services.

### T016 — variants/covers/hook experiments

- **Writes:** `editing/variants*`, `editing/hooks*`, `editing/covers*` and local tests.
- **Build:** account-capability aware crop/duration/captions/covers and three distinct 20–40s hook candidate EDLs using accepted assets; include experiment treatment/lineage and ordinary final-review package references.
- **Accept:** no new video-render jobs for hook tests; meaningful parts preserve payoff; changed framing/reading load is logged; three candidates do not force three posts without eligible slots. AT-10, IMP-07.

### T017 — technical/audio/visual QA

- **Writes:** assigned `qa/technical*`, `qa/audio*`, `qa/visual*`, coverage/report helpers and local tests.
- **Build:** actual media decode/streams/black/freeze/silence/peaks/caption bounds; independent ASR critical-term/speaker/identity/prop checks and supported temporal detectors.
- **Accept:** known seeded critical errors are flagged or explicitly unknown, never green solely because a source prompt was correct; evidence time ranges/coverage persist; model/API cost metered. Thai accuracy claims wait for real labeled evidence. AT-05.

### T018 — blind observation and comparison

- **Writes:** `qa/observation*`, `qa/comparison*` and local tests.
- **Build:** separate-call input builder excluding intended answers, immutable actual-media observations/transcript, then comparison with script/canon/anchors and typed findings.
- **Accept:** tests prove excluded fields/content do not reach Pass A; Pass B cannot modify frozen observation; unsampled windows do not count as checked; retry/QA costs reserved. AT-06, IMP-04.

### T019 — repair planner and feedback memory

- **Writes:** `qa/repairs*`, `review/feedback*` or separately agreed feedback submodule and local tests; transfer file ownership explicitly before editing review paths.
- **Build:** root-cause/cost/dependency repair plan from QA or timecoded human feedback, selective stage requeue, scoped local/series preference versions and rollback.
- **Accept:** subtitle defect causes caption repair without whole-video generation; wrong voice repairs the correct line/shot and derivative cues; local feedback cannot become a global season rule by inference; three-attempt/two-round/remaining-fund limits shared with render service; changed final media returns to Gate 2. AT-07, IMP-05.

### T020 — release core and schedule/reconciliation

- **Writes:** `publishing/` common service/protocol/scheduler/reconciler modules, no platform-specific adapter files owned by T021–T024.
- **Build:** required/optional release slots, dependency DAG, IANA scheduling, immutable media/current metadata policy, provider operations and external-ID reconciliation, verification coverage and rollback state.
- **Accept:** no release before approval; CTA dependencies wait for actual target; duplicate slots rejected; crash after provider submit cannot blindly repeat; missing required destination prevents full-release qualification. DST/late-window/permission/readback unknown tests. AT-09.

### T021–T024 — platform adapters (four separately claimable packets)

| Task | Exclusive path | Required operations and evidence |
|---|---|---|
| T021 | `publishing/youtube/`, matching tests | Full vs Shorts routing, resumable upload/status/reconcile, schedule, synthetic declaration, captions/localizations and supported next-video path. |
| T022 | `publishing/tiktok/`, matching tests | Eligible audited provider or approved Direct Post route, actual account max/settings/consent, AI declaration, publish status/error/quotas; no draft/inbox route mislabeled unattended. |
| T023 | `publishing/instagram/`, matching tests | Professional account/login-flow capabilities, container/process/publish/status, required declarations/readback and supported metadata/insights actions. |
| T024 | `publishing/facebook/`, matching tests | Explicit short-Reel vs supported full-video route, Page scope, upload/process/publish/schedule/status and required disclosure/readback; no inferred long-video API support. |

For each: implement the common T020 interface without local alternate approval/budget logic; contract-test accepted/denied/429/timeout/ambiguous/replayed responses using fixtures; source and version capability claims; leave live publishing disabled until T032. A marketing claim or historical duration/quota is not a live account test. Shared files stay integrator-owned.

### T025 — organic agency/community operation

- **Writes:** `community/` and local tests; plugin registration returned to integrator.
- **Build:** grounded titles/captions/descriptions/hashtags/cover selection, metadata version/cooldown, public replies, moderation classification/action, duplicate suppression, policy checks and metered budget consumption.
- **Accept:** ordinary criticism preserved; uncertain destructive actions suppressed; no fabricated episode/price/persona claims; untrusted comments cannot call privileged tools; reply/token/action limits and rate/backpressure implemented; no cold outreach or unapproved sponsorship/refund. Real platform action support tested in T032.

### T026 — membership and permitted DM/catalog flow

- **Writes:** `memberships/`, assigned DM-delivery service beneath `community/dm/` with explicit ownership, and local tests.
- **Build:** one selected verified Patreon/BMC backend plus common interface, truthful finished-episode early access/public transitions, provider entitlements/webhook checks and keyword/inbound DM delivery/eligibility.
- **Accept:** free CTA never resolves to unlabeled paywall; unfinished/unapproved episode cannot be sold as available; messaging windows/recipient restrictions respected; duplicate comments/webhooks do not create repeated unlock messages; revoked/missing entitlement cannot be replaced by an unlisted link. AT-11.

### T027 — analytics, experiments and qualification

- **Writes:** `analytics/`, report templates and local tests.
- **Build:** per-platform normalized-with-provenance snapshots; 24h/72h/7d schedules; hook/source/cohort/denominator ledger; effective successful-episode/minute cost, human time and intervention metrics; qualification state.
- **Accept:** failed/rejected spend retained; incompatible view definitions do not merge; unknown values remain null; organic comparisons not labeled causal; streak resets on failed/manual-fixed episode; management windows pending before day seven; ten episodes required. AT-12, IMP-08.

### T028 — execution queues and shared throttles

- **Writes:** `workers/`, shared rate limiter registration and worker deployment definitions, integrator-owned configuration.
- **Build:** distinct production/publication/community job routing, reserved concurrency/priorities, durable jobs, shared provider/account quota and independently scheduled janitor.
- **Accept:** AT-08 flood/load tests show community cannot starve due releases or spend protected funds; retries do not bypass limiter; outages resume durable jobs without duplicate effects. Initial one-episode GPU ownership enforced. IMP-06.

### T029 — complete mock pipeline and in-app schedule/webhook orchestration

- **Writes:** composition roots, `scheduling/` (declarative W01–W12 registry + webhook routes), integration configuration/tests, pilot runbooks; no unreviewed module rewrites. Schedule firing only enqueues frozen job types; webhook routes only record deduplicated events and enqueue their handling. (n8n dropped 2026-10-23 by operator decision: it duplicated `core.jobs` while adding a stateful service.)
- **Build:** schedules/webhooks/internal-service calls for W01–W12, complete fake original season/episode path, actual local FFmpeg fixture assembly, two review gates, identity lock, hooks, social/membership/analytics and terminal cleanup paths.
- **Accept:** one reproducible offline command/demo from proposal to managed fake post; real media fixture exports playable; no paid network/public actions; no third routine human gate; every module cost/permission/coverage check remains active. Mock/fake statuses clearly visible.

### T030 — independent cross-system review and fault qualification

- **Writes:** assigned integration/security/fault tests, redacted `evidence/` reports and release-readiness checklist. Findings go back to owning implementation tasks.
- **Build:** independently reproduce AT-01 through AT-13; inject concurrency, stale approvals, leaks/reconnects, corrupted media, wrong speaker/amount, comment floods, replayed webhooks, unknown fields, wrong CTA, DST and missing disclosures.
- **Accept:** meaningful failures detected; no fake provider silently falls through to production; budgets/approval provenance/rights/queue isolation verified from behavior, not grep alone; all defects closed or readiness blocked with precise evidence. Do not record AT-14 as passed here.

### T031 — real provider/rights/preset qualification

- **Writes:** assigned `evidence/provider-qualification/` and registry input records; no global policy edits without guardian.
- **Prerequisites:** T045 live-capable adapter/composition; actual rights route and credentials; expressly authorized bounded paid benchmark; prospectively reserved costs and pinned hardware/workflow configuration. External prerequisites remain honest blockers; T045 and other offline work can proceed meanwhile.
- **Execute when authorized:** resolve H3 global output rights or select a separately eligible route; do one bounded manual pod/model canary to learn hardware/graph feasibility; then verify V1's own Runpod/Comfy lease, reservation, submit, poll, durable output and verified shutdown path with generic references. Verify Thai voice/reference controls and compare representative dialogue/emotional/prop/scene-reset shots using matching compatible presets. Record full cold/warm timings, all attempts, critical errors, quality/coverage, actual usage and billed cost. The manual canary alone does not pass T031. Respect the confirmed cap; do not launch an oversized benchmark that assumes an extra budget.
- **Accept:** enabled registry profiles have actual reproducible rights/quality/cost evidence at intended settings; unresolved routes remain disabled. Vendor demos and 5090 speed figures cannot certify a cheaper GPU or a different mode. If no profile meets quality/cap, report feasibility failure rather than mark ready.

### T032 — controlled real publishing/social/member tests

- **Writes:** assigned `evidence/account-qualification/` and capability input records.
- **Prerequisites:** authorized connected accounts, rights-cleared test content, applicable final approval for public media, configured permitted actions and spending. OAuth/app review/unattended disclosure support is actual state, not a test assumption.
- **Execute when authorized:** controlled upload/schedule/reconcile/readback on every required platform route, public metadata/action features, consenting keyword/inbound DM checks, moderation fixture/test policy, selected membership access/payment test mode where supported and free/paid transition. No unsolicited messages to others.
- **Accept:** real IDs/URLs and visible labels/destinations where available, current limits/permissions documented, timeout recovery supported without duplicates, messaging/entitlement restrictions honored. Unsupported destination remains blocked; offline adapter completion alone does not pass this task.

### T033 — first real episode

- **Writes:** first-episode runtime records and redacted `evidence/first-episode/`; media belongs in private storage.
- **Execute when authorized:** actual application Gate 1 for season concept/arc; automated original Thai script→typed scene/wardrobe/prop references→keyframes/shots→FFmpeg/captions/hooks/poster/preview when selected→observation/comparison/repair→Gate 2 package; human final action; automatic supported release and management. Record costs for every attempt, QA coverage and manual interventions. T047 must already show the V2 mock path works without hidden manual operators.
- **Accept:** AT-14 and two-gate workflow work on actual outputs, episode-one identity lock created through Gate 2, pods off during human wait, costs fit configured cap, no hidden manual edit/upload to fake success. If intervention is required, record failed qualification even if the episode is eventually published.

### T034 — sustained qualification

- **Writes:** redacted `evidence/reliability/`, qualification/dashboard records; no speedup of public cadence without approved scope.
- **Execute:** observe ten consecutive qualifying episodes and their initial seven-day management windows under approved schedule. Track resets, failures, action incidents, review/revision time, accepted costs and next-episode progression.
- **Accept:** actual ten-episode and management evidence, no pending-window masquerading as pass, no failures erased. This task can remain pending beyond two weeks. It is not satisfied by running ten mocks or ten cuts from one episode.

### T035 — final handoff and traceability

- **Writes:** operational README/runbooks, requirement/evidence matrix and final task ledger; guardian handles accepted contract changes.
- **Deliver:** reproduce software checks, documented setup/config/restore/rotation/cancel procedures, required capability/rights/preset evidence, fixed/variable/full cost reporting, V2 owner-app and domain operations, owner-review instructions and remaining risks. Independent reviewer assesses the final integrated implementation.
- **Accept:** every MD/IMP/AT row mapped to code, tests and real evidence where required. M4 software-only handoff may be documented early, but overall completion remains pending until M5–M7 evidence is satisfied or explicitly reported as incomplete. No “fully automated and viable” claim from implementation alone.

### T036 — V1 prop/outfit routing correction (V2-F01)

- **Writes:** story compiler and scoped tests; references lane owns any changed binding behavior. Contract changes, if required, go through T038.
- **Build:** map writer `staging.prop_ids` to shot `prop_ids`, leave outfit IDs to wardrobe planning, and reject or identify unknown props before rendering. Preserve V1 manifest readback for audit without misclassifying old corrupt data as a valid outfit.
- **Accept:** a draft with a prop in dialogue produces that exact prop in the manifest and render packet with no false outfit; establishing and dialogue shots both pass. Test a missing prop and a corrected rerun through the ordinary budget/idempotency path. Record the source-level read-only reproduction from the V2 review.

### T037 — live-release scheduling and metadata correction (V2-F04/F05)

- **Writes:** publishing command builder, scheduler discovery and scoped tests.
- **Build:** discover a reconciled-absent slot rearmed as `SUBMITTED` with pending provider operation; construct a current-version command from approved release scope and metadata, not the mock fallback. Retain single-flight per slot and dedupe across periods/restarts.
- **Accept:** an absent result leads to one later submit and verified readback; a crash/restart or concurrent timer does not duplicate it; stale metadata/capability/approval blocks; a live transport never receives mock-labeled title/caption/description. Fixture-only metadata remains explicitly confined to OFFLINE_MOCK.

### T038 — V2 contract and kit crosswalk

- **Writes:** canonical contracts, schema generation, examples, ordered migrations and compatibility notes.
- **Build:** map the production kit's episode/asset/continuity concepts to V2 canonical records without importing incompatible ID, duration and status rules. Define concept intake/candidate, character logic, episode pack, story time, wardrobe bible/assignment, state event, prop/location sheet, style bible, typed shot reference, prompt manifest and progress projection. Use stable IDs, versions, hashes, rights and validity intervals; define legacy V1 read behavior.
- **Accept:** generated schemas/examples/migrations and downgrade/upgrade/readback evidence; a V1 manifest remains readable but is explicitly not V2-ready; role-less assets, contradictory state, stale outfit and retired rights are rejected before paid work. No second source of truth.

### T039 — Script Maker and richer bible

- **Writes:** research/story services, writer/critic prompts and scoped tests; UI input surface is T044.
- **Build:** turn story, genre/tone and episode count into original candidate scopes under a bounded research envelope. Add character wants, strategy, flaw, secrets, relationships and knowledge timing, plus season promise/payoff/escalation ledgers. Generate detailed first-three episode packs and a later-episode map after the existing Gate 1 decision; no additional routine approval gate.
- **Accept:** an owner-entered short idea reaches Gate 1 without hand-written `SeasonScope`; the chosen scope is hash-bound; future secrets do not leak; each episode pack lists visible cast, props, locations, proof objects, story time and required assets; Thai and duration constraints hold.

### T040 — series look, sheets and wardrobe/state library

- **Writes:** references/asset planning and scoped tests; cross-module fields are owned by T038.
- **Build:** generate demand-driven character angles, per-character outfit sheets, props and location layouts/empty plates, and a style bible with a short moving sample. Assign outfit by character, scene, story day, setting and explicit change/reuse reason; maintain prop ownership/hand and wardrobe state intervals. Cost, rights and cache keys cover every distinct asset version.
- **Accept:** day-one office and next-day home scenes bind distinct outfits by default; same-outfit reuse requires a reason; silent visible characters and key props receive references; only the current approved outfit is attached to a shot; changed/retired assets invalidate affected dependents, not the whole season. Real dimensions/cost remain T031 evidence.

### T041 — shot state, reference resolver and prompt compiler

- **Writes:** story/directing compiler, reference resolver and GPU workflow binding through serialized module handoffs.
- **Build:** compile the episode pack into scene/beat/shot records with state-in → event → state-out, screen direction, eyeline, action handoff, sound and edit intent. Produce roughly 30-second editorial groups for the UI but render individual at-most-15-second shots. Select typed exact-version identity, outfit, prop, location, style and first/last/handoff assets; fail on conflicts. Vendor-specific workflow adapters map semantic roles to actual controls without index-based guessing.
- **Accept:** AT-15–17 and a composed draft→pack→manifest→reference→prompt→workflow trace pass; no future secret or unrelated asset enters a shot prompt; changed source hashes trigger targeted regeneration and review; required controls unsupported by the selected route block before reservation.

### T042 — keyframe preflight and continuity QA

- **Writes:** rendering/QA services and scoped tests.
- **Build:** where model route supports it, validate still keyframes before motion for identity, assigned outfit, location geometry, prop details, light and frame handoff. Add actual-media checks and coverage accounting for wardrobe, props, space/action, Thai voice/subtitles and phone viewing; calibrate model evaluators on a labeled set and preserve UNKNOWN for unobserved facts.
- **Accept:** seeded identity/outfit/prop/eyeline/proof-text errors route to the earliest correct repair stage; passing keyframes alone do not certify motion; model QA reports measured false positives/negatives and applicable shot classes before any release-gating use.

### T043 — poster, preview and creative lineage

- **Writes:** editing/variants/cover services and scoped tests.
- **Build:** create a static poster with approved character/title/CTA assets and an optional up-to-90-second episode-one preview from accepted source footage, separately from the existing three short hook candidates. Bind reveal boundary, source ranges, rights, mobile safe zones, platform variants and package hashes.
- **Accept:** all new creatives appear in the Gate 2 package; changing a source invalidates only derivatives; no new generation job or publication obligation is silently created; a spoiler, wrong CTA or unreadable poster fails review.

### T044 — owner workbench and progress projection

- **Writes:** review/API routes/templates or a documented frontend module, with owner-scoped tests.
- **Build:** three-step intake, season bible, sheets/look, episode sections, shots, media/review and release views. Project a full timeline from durable events/jobs/asset/review/post state, showing stage and overall percent, accepted/total work, cost, blockers, retries, waits, next action and version. Keep production and release completion separate.
- **Accept:** refresh/restart/retry/revision, a new planned outfit/shot, a failed provider call and both human gates display truthful progress and reasons; percent can decrease with explicit version change; no invented provider-internal progress or owner-scope leak; existing two gates remain authoritative.

### T045 — live V1 provider composition and paid benchmark path

- **Writes:** Runpod adapter, Comfy transport, live composition/worker bootstrap, storage/billing/cleanup integration, scoped tests and operator runbook. No pod launch is part of code completion.
- **Build:** preserve OFFLINE_MOCK refusal, add explicitly configured PAID_BENCHMARK adapters with credential references and real clock/IDs; select compatible pinned workflow/GPU/rights/price; support owned create/find/stop/terminate, submit/poll, durable output, actual usage, restart reconciliation and independent janitor. Separate production/publication/community capacities. The benchmark tool must produce real receipts rather than relabel fake evidence.
- **Accept:** fixture fault injection covers create/submit ambiguity, stop failure, rate/price changes and restart; no external call without reservation and effect authorization; live configuration refuses unqualified rights/presets. T031 alone records actual pod/quality/cost evidence.

### T046 — private staging and domain readiness

- **Writes:** deployment definition, secret references, TLS/auth/private-media configuration, backup/restore and operations runbook.
- **Build:** stage one owner, one series and one episode privately; then prepare `dramabox.aivora.agency` with DNS/TLS only as a separately executed deployment action. Keep public posting independently gated by Gate 2 and account capability.
- **Accept:** authenticated owner scope, no public media leakage, restart/backup/restore and worker/janitor isolation drills pass; staging progress agrees with persisted job state; production hostname is not marked live from a local mock page.

### T047 — independent V2 composed acceptance

- **Writes:** integration/fault tests and redacted V2 evidence; findings return to the responsible module owners.
- **Build:** start from a short story idea, approve one season, automatically create bible/packs/sheets/style/wardrobe assignments, compile and render fake short shots, assemble/QA/repair, show correct timeline, and reach the same episode Gate 2. Inject prop/outfit mismatch, next-day change, stale reference, failed attempt, restart and revision; exercise poster/preview lineage.
- **Accept:** AT-15–17 and AT-20–23 pass from composed behavior, AT-19's rearm path passes against fixture transports, prior AT-01–13 remain green, and `make check`/`make pilot` are rerun. State clearly that AT-18 live pod evidence, AT-19 real-account extension and AT-14 still require T031–T033.

### T048 — time-independent pilot and integration fixture (V2-F12)

- **Writes:** mock-world/test fixture clock setup, integration tests and pilot runbook. The production approval migration and authorization policy stay strict.
- **Build:** keep the fake media/production timeline deterministic while creating a genuinely live test owner session relative to the database server clock, or provide an equivalent isolated test-time mechanism. Audit fixture provider timestamps and scheduled windows so a different calendar day does not invalidate the mock route. Do not backdate approval events or extend production session TTL to conceal the issue.
- **Accept:** `make check`, `make pilot`, the scheduler-driven integration test and the independent AT-02/AT-03 approval tests pass on a fresh date and when the old fixed 2026-10-27 fixture time is more than eight hours in the past. A genuinely expired/forged session is still denied by the DB. Record the 28 October failure and corrected test receipts.

## 6. Requirement-to-task coverage

| Requirement group | Owning tasks | Verification |
|---|---|---|
| MD-001/002/004 original Thai season/format/research | T009, T010, T011, T031, T033 | Script/canon fixtures; actual Thai/media evidence |
| MD-003/005/006 two gates and automatic production | T004, T008, T019, T029, T033 | AT-02/07/14 |
| MD-007/008 budget and failed costs | T005, T012, T014, T025–T028 | AT-01/04/08/12 |
| MD-009/014 platform publication/reconciliation | T020–T024, T029, T032 | AT-09/14 |
| MD-010 actual-media review | T017–T019, T030, T031 | AT-05/06/07 |
| MD-011 + IMP-01 identity lock | T008, T011, T014, T033 | AT-03 |
| MD-012/018 organic agency scope | T025, T026, T028, T032 | AT-08/11/13 |
| MD-013 + IMP-06 isolation/janitor | T005, T012, T028, T030 | AT-01/04/08 |
| MD-015 rights/disclosures | T006, T020–T024, T030–T032 | AT-09/13 |
| MD-016 memberships/free-paid truth | T026, T020, T032 | AT-11 |
| MD-017 + IMP-08 qualification | T027, T034, T035 | AT-12/14 + actual windows |
| IMP-02 directing playbook | T010, T015 | Structured shot/coverage tests |
| IMP-03 quality routing | T014, T019, T031 | AT-07 + accepted-shot benchmarks |
| IMP-04 observation-first | T018, T030 | AT-06 |
| IMP-05 feedback memory | T008, T019 | AT-07 |
| IMP-07 three hooks | T016, T027 | AT-10 |
| V2-01/02 intake, bible, episode packs | T038, T039, T044, T047 | AT-20 |
| V2-03/04/05 story time, sheet and wardrobe state | T036, T038, T040, T041, T047 | AT-15/16/17 |
| V2-06/07 look, typed references and prompt compiler | T038, T040, T041, T042, T047 | AT-17 |
| V2-08 keyframe/actual-media continuity | T042, T031, T047 | AT-05/17/18 |
| V2-09 poster and optional preview | T043, T047 | AT-22 |
| V2-10 owner timeline and domain | T044, T046, T047 | AT-21 |
| V2-11 current defects and release recovery | T036, T037, T041, T047, T048 | AT-15/17/19/23 |
| V2-12 staged live rollout | T045, T031–T035, T046 | AT-14/18/19 |

## 7. Completion ledger and handoff format

Orchestrator alone maintains [task_status.csv](task_status.csv). Permitted statuses: `TODO`, `CLAIMED`, `IN_PROGRESS`, `REVIEW`, `ACCEPTED` (historical V1 usage), `DONE` (equivalent accepted result for new tasks), `BLOCKED_EXTERNAL`, `FAILED`, `CANCELLED`. `DONE` or `ACCEPTED` requires scoped evidence; a planned contract version, mock pass or external blocker cannot be hidden behind completion. A split software-versus-live result must state its milestone precisely. Do not reset T001–T030 because V2 was added.

For each task return:

```text
TASK: Txxx
CONTRACT VERSION: ...
CHANGED PATHS: ...
ACCEPTANCE RESULTS: exact commands, observed outcomes, evidence references
EXTERNAL EFFECTS: none / explicitly authorized action and actual cost/IDs
OPEN ITEMS: missing provider evidence, limitations, blockers
INTEGRATION NOTES: exported factories, required config, migrations, dependencies
SUGGESTED NEXT TASKS: dependency-ready IDs only
```

Do not paste tokens, private contacts, raw payment data, full media blobs or unverifiable success claims into the ledger.

## 8. Ready-to-use orchestrator brief

> Implement [SPEC.md](SPEC.md) v2.0 using this breakdown and the [current-build review](build-review-v2-2026-10-28.md). Inspect the checkout and ledger first; preserve accepted T001–T030 and the closed 26 October remediation. Repair the V2-F12 fixed-date integration fixture first and close V2-F01/F02/F04/F05 before their affected paid/public paths. Freeze T038 contracts before dependent V2 modules. Follow dependency-ready tasks T036–T048, then the still-pending T031–T035 live/reliability gates; do not call a manual Runpod sample an integrated V1 pass. Keep paid/cloud/public effects disabled until their own prerequisites and authorization. Preserve two runtime human gates, original Thai fiction, the US$10 episode cap and IMP-01–08. Test composed prop/outfit/reference binding, W09 rearm, progress truth, budget/approval/QA/recovery and private-owner access. Report software-ready, provider-qualified, first-episode, staged-domain and ten-episode qualification separately. Do not claim the live system works from mocks or silently add manual operators to make it pass.
