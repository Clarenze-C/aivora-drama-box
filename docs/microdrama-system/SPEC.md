# Automated Thai Micro-Drama System — Implementation SPEC

Version 1.0 · 19 October 2026 · Implementation baseline, not deployed software.

Companion: [task_breakdown.md](task_breakdown.md). Background: [operating design](../../deliverables/thai-microdrama-research-2026-10-19/automation-plan.md), [accepted policy v2](../../deliverables/thai-microdrama-research-2026-10-19/automation-policy.example.json), [research and season proposal](../../deliverables/thai-microdrama-research-2026-10-19/decision-plan.md).

## 1. Purpose, authority and implementation boundary

Build a production system that researches original Thai micro-drama seasons, obtains season approval, automatically generates and finishes episodes, obtains final video approval, then automatically publishes and manages their organic social presence.

The user has confirmed the operating requirements and all eight improvements below. This SPEC translates those decisions into implementation contracts. Creating this document does not establish that media quality, provider access, commercial rights, the US$10 target or unattended platform publishing have been validated. No implementation, benchmark or deployment is complete at this baseline.

Precedence: current user instructions → this SPEC for implementation → task breakdown for execution order → accepted policy/playbook examples → operating/research documents for rationale. Report conflicts; do not silently implement the older labor-heavy/manual-publishing plan. Other AIVORA projects' specifications are not policies for this system. Do not copy their account IDs, credentials, posting restrictions, databases, model mandates or deployment triggers into this project.

Implementation root is proposed as `/root/AIVORA/microdrama/`, an isolated new module. This turn creates documentation only. Reuse existing AIVORA services only through separately documented, authorized interfaces; no direct writes to Arisa, Mission Control, trading services or their databases by default.

## 2. Confirmed product requirements

| ID | Requirement |
|---|---|
| MD-001 | Original fictional Thai-language drama; retain Thai performances. English subtitles and localized metadata broaden accessibility. No copying supplied comparables/personas. |
| MD-002 | Episodes 180–300 seconds; initial season defaults to ten episodes, configurable within approved scope. Generation normally uses shorter shots and may use up to a supported 15-second unit. |
| MD-003 | Exactly two routine human approval types: season concept/arc once, and final episode release package per episode. No script, prompt, reference, audio, edit or upload approval steps between them. |
| MD-004 | Gate 1 authorizes versioned season scope, arc, creative constraints, cost policy, intended destinations and management policy. Research creates proposals before this gate under bounded configured spending. |
| MD-005 | Gate 2 offers Approve & schedule / Revise / Reject on the full episode and its release package. Silence/timeouts never approve. Revisions return to this same gate. |
| MD-006 | All intervening research/writing/reference/voice/render/edit/caption/QA work is automated; all publication and policy-permitted social work after Gate 2 is automated. |
| MD-007 | US$10 maximum directly attributable variable cost per episode up to five minutes, including retries, allocated research, generation, AI QA, exports and metered management. Fixed subscriptions and engineering are reported separately. |
| MD-008 | Failed/rejected attempts and jobs retain their spend. Renaming, retrying or requesting human revisions cannot reset the episode allowance. |
| MD-009 | Publish full episodes/parts/cuts on TikTok, YouTube, Facebook and Instagram through supported eligible account/provider routes. Account-specific limitations can block a route; never claim all four work from generic vendor marketing. |
| MD-010 | AI pre-review checks actual exported audiovisual media and captions; independent observation precedes script comparison. Unresolved configured blockers prevent publication. |
| MD-011 | Recurring character/voice/costume/set identities are versioned and reused. Episode-one final approval locks its reviewed production identity package before later-episode rendering. |
| MD-012 | Automatic social operation covers strategy/calendar, titles/captions/descriptions, relevant keywords/hashtags, covers, scheduling/publication, bounded metadata optimization, public replies, permitted DMs, moderation, links, analytics and reporting. |
| MD-013 | Production, publication and community queues have isolated capacity and protected budget reservations; an independent janitor controls owned GPU leaks. |
| MD-014 | Every public action has an approved media/policy scope, account identity, dedupe key, external ID where available and auditable outcome. Ambiguous external actions are reconciled, not blindly repeated. |
| MD-015 | Global output/model/voice/music rights and required synthetic/sponsor disclosures must be established for each active route. AI review/human episode approval cannot waive a license restriction. |
| MD-016 | Member early access preserves the announced free season schedule; keyword DMs distinguish free continuation from paid early access before checkout. |
| MD-017 | Ten consecutive qualifying episodes are required before increasing unattended production volume; production and initial seven-day management qualification are tracked separately. |
| MD-018 | Initial production paid-ad budget is zero. Organic management cannot accept contracts, invent sponsorships, issue refunds, rotate proxies for country impersonation or increase budgets. |

### 2.1 Eight accepted improvements

| ID | Required implementation |
|---|---|
| IMP-01 | Episode-one identity/style lock via existing Gate 2; block later-episode render dispatch until locked. |
| IMP-02 | Reusable directing patterns for confrontation, revelation, quiet confession, comic reaction, practical action and cliffhanger; distinct plots/performances. |
| IMP-03 | Route shot classes among compatible benchmarked quality presets using cost per accepted shot/retained second plus quality, including downstream repairs. |
| IMP-04 | Freeze media-only observations/independent transcript before comparison with intended script/canon. |
| IMP-05 | Timecoded feedback produces smallest-scope repairs; recurring preferences activate only from explicit recurring user instruction or the existing approval package. |
| IMP-06 | Isolated production/publication/community queues and protected funds, with shared provider/account rate limits. |
| IMP-07 | Three 20–40-second hook candidates per episode from existing accepted footage, included in its final review; no fresh video renders solely for hook experiments. |
| IMP-08 | Rolling ten-episode reliability qualification and effective-cost/review-time/continuation scorecard. |

Initial test settings: two active locations, three featured speaking characters per episode, normally two speakers per shot; maximum three paid generation attempts per shot, two automatic final-QA repair rounds and three transient transport attempts. These settings are configurable inside approved scope, not evidence of measured quality. Unknown or unsupported controls cannot be silently discarded.

## 3. Delivery architecture and code layout

Use Python for deterministic services, provider adapters and media workers, PostgreSQL for the durable business ledger, private S3-compatible storage for assets, Redis-backed worker queues, and FFmpeg/FFprobe for editing/inspection. Use n8n for schedules/webhook orchestration; core invariants live in tested services, not duplicated n8n expressions. Use a minimal authenticated server-rendered review interface initially. Bootstrap selects supported dependency versions and pins them; this SPEC does not mandate unverified package versions.

Queue implementation must support the three named work classes and reserved concurrency; a Redis transport does not itself enforce business idempotency or budgets. APIs enqueue short durable jobs and return IDs. Long model/GPU tasks use submit/poll/reconcile steps; no browser request or workflow worker is held open through a human wait. Media bytes remain in object storage, not Redis or n8n payloads.

```text
microdrama/
  pyproject.toml, Makefile, README.md
  contracts/                  # Versioned schemas, enums, examples; integrator-owned
  migrations/                 # Ordered SQL migrations; integrator-owned
  src/microdrama/
    core/                     # State transitions, authorization, events, idempotency
    persistence/              # DB repositories/transactions and object-store metadata
    budget/                   # Reservations, accruals, settlement, allocation
    research/                 # Sources, provenance, originality, season proposals
    story/                    # Bible, canon, directing playbook, scripts and prompts
    references/               # Image/voice generation, reuse and identity locks
    rendering/                # Routing, Comfy jobs, Runpod leases, independent janitor
    editing/                  # EDL, FFmpeg, mix, captioning, variants, hooks
    qa/                       # Technical/audio/visual/observation/comparison/repairs
    review/                   # Gate APIs/UI and scoped feedback/preference memory
    publishing/               # Release DAG, schedules, upload adapters, reconciliation
    community/                # Metadata/replies/DMs/moderation and action policy
    memberships/              # Early-access catalog, entitlement/provider adapters
    analytics/                # Snapshots, experiment ledger, reports, qualification
    api/                      # Composition root; integrator-owned route registration
    workers/                  # Composition root; integrator-owned queue registration
  workflows/n8n/              # Versioned exports calling internal services
  tests/{unit,contract,integration,fixtures}/
  deployment/                 # Local compose, locked images, configuration, runbooks
  evidence/                   # Redacted reproducible validation receipts, not secrets/media
```

This is a target layout; the orchestrator may approve a documented equivalent before code starts. An agent cannot independently rename shared modules or invent a second queue/state store. Module owners export local route/job factories; the integrator registers them to avoid shared-file collisions.

Build/control planes are distinct: development multi-agent orchestration builds this application; runtime researcher/writer/critic roles are application jobs with their own credentials and spend. Runtime LLM roles never approve releases, directly execute arbitrary shell code, or mutate cost/rights policy.

## 4. Canonical contracts and persistence

All records carry UUID ID, schema version, created/updated UTC timestamps, correlation/episode IDs where applicable and an optimistic revision. Use integer micro-USD or equivalent exact decimal for money; runtime floating-point comparisons are forbidden for budgets. Store timezone-aware schedules with IANA zones and concrete UTC instants. Canonical JSON hashing must be defined once in contracts and used for approval/media/policy/version links.

### 4.1 Required entity groups

| Entities | Required fields/invariants |
|---|---|
| seasons, season_proposals, canon_versions | Source provenance, proposed/approved scope hash, arc, expected episode count, planned vs final-approved vs published facts. A planned reveal is not published canon. |
| approval_events | Human actor/session, gate type, action, expected entity revision, media/package/policy hashes, timestamp. Append-only; runtime model roles cannot insert human events. |
| episodes, scripts, shot_manifests | Approved season link, state/revision, exact Thai lines/speaker IDs, actual/estimated timings, shot purpose/pattern, identity refs and dependency graph. |
| characters, voices, identity_locks, preference_rules | Asset/source/license hashes, approved anchors/wardrobe/set/style versions, explicit user-feedback scope, active/superseded state. |
| assets, edit_manifests | Private object key, checksum, media streams/duration/dimensions, source links/licenses, accepted/failed/provisional state, EDL and derivative lineage. |
| jobs, events, idempotency_records | Job type/version/input hash, unique semantic key, queue/lease/retry count, external ID, outcome. Outbox event insertion and state mutation share a DB transaction. |
| reservations, charges, allocations, pod_leases | Exact currency/source price/time bounds; reserved/accrued/settled amounts; remaining exposure; provider operation/pod ID and owned tags. |
| qa_observations, qa_findings, feedback_events, repair_plans | Actual asset/time ranges, independent transcript, observation input hashes, evidence/coverage/severity, proposed repair and cost, dependencies invalidated. |
| release_packages, platform_posts, metadata_versions | Immutable source-media hashes; approved mutable-metadata policy; target account/capability version; schedule/dependencies; provider IDs/URLs and verification coverage. |
| community_events, management_actions | Provider event/user/post dedupe, messaging-window eligibility, factual catalog version, permitted action, budget reservation, external outcome. |
| membership_catalog, entitlement_links | Actual public/early-access state, truthful price/free date, member-provider asset/post IDs, entitlement verification metadata, no secret playback token in public links. |
| performance_snapshots, hook_experiments, qualification_runs | Source/platform definitions, sample counts/denominators, observation time, treatment and slots, missing metrics as null, all failed costs and manual interventions. |
| capability_registry, rights_registry, preset_registry | Provider/account/model/mode/version, tested supported operations/limits, territory/commercial terms/expiry evidence, benchmark quality/latency/cost and enabled state. |

Migrations define unique constraints for semantic jobs, approval actions, external event dedupe and each publication slot. Do not dedupe source assets purely by script text when voices/settings differ. Large binaries/transcripts with sensitive content live in private storage with appropriate retention rather than unbounded event payloads.

### 4.2 Cross-module payloads

Contracts task publishes schemas and valid/invalid examples for:

- `SeasonScope`, `ApprovalCommand`, `EpisodePlan`, `Script`, `ShotManifest`, `IdentityLock`.
- `BudgetReservationRequest`, `UsageReceipt`, `PodLease`, `RenderRequest`, `ProviderOperation`.
- `AssetDescriptor`, `EditDecisionList`, `CaptionTrack`, `HookExperiment`.
- `ObservationRequest`, `ObservationReport`, `ComparisonRequest`, `QAFinding`, `RepairPlan`.
- `ReleasePackage`, `PublicationCommand`, `CapabilityRecord`, `ManagementAction`.
- `MembershipCatalogEntry`, `MetricSnapshot`, `QualificationResult`, `DomainEvent`.

`DomainEvent` includes `event_id`, `event_type`, `schema_version`, `aggregate_id`, monotonic per-aggregate sequence, correlation/causation IDs, UTC time and bounded payload. Delivery is at least once; consumers are idempotent. A hash/checksum verifies identity/integrity, not truth or rights clearance.

### 4.3 Public/internal service API

| Route shape | Required behavior |
|---|---|
| `GET /seasons/proposals`, `GET /seasons/{id}` | Versioned proposals, evidence, scope, cost and status; no provider secrets. |
| `POST /seasons/{id}/approval` | Authenticated Gate 1 approve/reject, expected revision and idempotency key. |
| `GET /episodes/{id}/review` | Full video/variants/covers, cast package when relevant, QA coverage, planned release/management policy, actual/remaining cost. |
| `POST /episodes/{id}/review` | Authenticated Gate 2 approve/revise/reject; timecoded feedback; reject stale packages. |
| `GET /episodes/{id}/events`, `/costs`, `/releases` | Auditable status/receipts with missing/unknown states explicit. |
| `POST /internal/jobs`, `GET /internal/jobs/{id}` | Authenticated deterministic enqueue/status contract; caller cannot bypass transitions/budget/policy. |
| `POST /webhooks/{provider}` | Validate provider signature/challenge as required, dedupe and enqueue; never execute model text as actions. |
| `GET /health`, `/ready` | Health excludes secrets; readiness distinguishes database/queue/config availability. |

Minimum command responses: 202 queued, 200 replay of identical successful command, 409 stale/conflicting revision or reuse of an idempotency key with different content, 422 invalid schema, 403 unauthorized/policy denial. Budget/service failures use typed internal errors surfaced clearly to the UI. Never return success when an asynchronous action is merely submitted.

## 5. State machines and the two approval gates

Season: `PROPOSED → SEASON_APPROVED → ACTIVE → COMPLETE`, with `REJECTED`/`CANCELLED`. Approving the concept/arc creates a scope version; subsequent bible/scripts are machine-produced inside it.

Episode: `PLANNED → SCRIPTING → REFERENCES → RENDERING → ASSEMBLING → AI_REVIEW → AWAITING_FINAL_REVIEW → RELEASE_APPROVED → SCHEDULED → PUBLISHING → PUBLISHED_VERIFIED → MANAGED`.

Failures are typed outcomes alongside last valid stage: `BUDGET_EXHAUSTED`, `FAILED_QA`, `FAILED_INFRA`, `RIGHTS_UNCLEARED`, `CAPABILITY_UNAVAILABLE`, `NEEDS_RECONCILIATION`, `REJECTED` and `CANCELLED`. Do not pretend a blocked platform means the whole episode completed all required destinations.

Rules:

1. Only an authenticated human can produce Gate 1/Gate 2 approval events. Automated QA may accept a shot but cannot set human approval.
2. Gate 2 is enabled only for a current package with configured critical checks passed, rights/capability release conditions satisfied and persistent assets verified. Blocked previews may be viewed without a publish button.
3. Approval binds immutable media hashes, release scope and allowed management-policy hash. Valid platform transcoding is delivery of the approved source; material video/voice/caption/overlay recuts invalidate approval and return to the same Gate 2.
4. Bounded title/description/hashtag/reply changes inside the approved mutable policy do not need additional human approval; factual identity/offer/disclosure rules still apply. Unapproved sponsors/prices/contracts remain outside scope.
5. Explicit timecoded revision triggers automatic targeted repair inside remaining budget. No budget reset or extra routine script gate. A depleted job ends with a visible failure and GPU cleanup.
6. Episode-one package includes reviewed cast contact sheet, short voice anchors, outfits/sets and style. Its Gate 2 approval creates the identity lock atomically. Later-episode render dispatch waits for that lock; later characters not included in it remain provisional until reviewed in their own package.
7. Preserve published canon separately from planned arc and final-approved content. A rewrite invalidates downstream dependencies but cannot rewrite released episodes silently.
8. Do not run GPU resources during human waits. No timers, AI confidence scores or worker credentials can approve on the human's behalf.

Development checks, CI reviews and deployment readiness are engineering controls, not extra recurring creative human gates. Runtime setup includes necessary OAuth/rights/configuration; implementations cannot claim those one-time requirements are automatically satisfied.

## 6. Budget accounting and queue isolation

Before a paid job, one DB transaction checks and reserves:

`settled + accrued/unbilled + outstanding in-flight exposure + new worst-case exposure + mandatory shutdown/billing reserve ≤ 10,000,000 micro-USD`.

Reservations transfer to accrued/settled states without double-counting. Reconcile final charge differences; unknown price, currency/FX or uncertain maximum exposure blocks paid dispatch. Set token/duration/resolution/timeout ceilings. A cap is enforced conservatively before dispatch; delayed external billing can still reveal an overrun. Record it, quarantine the unsafe profile and stop further paid work; never erase/relabel a charge to claim compliance.

Episode budget includes allocated season research/reference setup, failed generations, GPU warmup/download/idle time, AI observation/comparison/ASR, CPU/storage/transfer, hook exports and metered community/provider overages. Fixed subscriptions/engineering remain separately visible. Pre-Gate-1 research needs a prospective bounded reservation; rejected ideas retain their cost. No research loop spends without a configured envelope.

Initial allocation is $1 research/script/prompts/metadata, $1.50 references/dialogue, $2.50 GPU, $1 QA/captions, $0.50 CPU/variable storage/transfer, $1 metered management and $2.50 uncommitted exposure/recovery headroom. This is an allocation, not evidence that current services fit. Transfers inside total preserve committed production and shutdown reserves; community cannot steal those funds.

Use logical queues `production`, `publication`, `community`, with reserved worker capacity and shared provider/account rate limiters. Independent janitor does not depend on a blocked community worker. During the pilot, only one episode owns a GPU lease at a time. Reuse a warm pod sequentially only after transferring lease/accounting ownership transactionally; allocate each paid time interval once, including cold/idle overhead by declared basis. Parallel shared-pod accounting is a later optimization requiring proof.

Community metering stops at its safe allowance; use supported deterministic templates/fixed-quota mechanisms only where those truly avoid new variable exposure, otherwise suppress/defer optional actions. Do not promise unlimited free AI management. Failed jobs count in both episode spend and project effective cost per successful episode.

## 7. Research, story, reference and directing services

Research uses approved public/authorized sources, date/provenance tracking, source-quality labeling, dedupe and bounded originality/resemblance checks. Public comments are qualitative clues, not representative market shares. Incoming text cannot alter instructions, secrets, budget or permissions. Proposal ranking returns original season concepts/arc and uncertainty; no scraping behind authentication or copying scripts.

Claude is the configured story architect. Research/critic/classifier roles may use cheaper selectable models where verified available. Runtime model IDs, prices and credentials are configuration, not hardcoded from conversational model names. Produce validated structured data; semantic critics check canon, Thai relationship terms, names/money/negations, action/intent, runtime, hooks and resemblance. Machine cultural accuracy remains a benchmark risk, not a guarantee.

The directing playbook starts from the [accepted example](../../deliverables/thai-microdrama-research-2026-10-19/directing-playbook.example.json). Per shot require pattern/purpose, dramatic importance, dialogue/temporal risk, identity controls, compatible tier, fallback edit, reference-lock version, exact Thai lines, voice/speaker IDs, timing, framing/eyelines, scene/outfit/prop IDs, required references, sound and acceptance criteria. Automatically simplify unsupported staging while preserving the dramatic event.

Reference/voice services generate/select commercially eligible assets, cache by full input/model/license hash, compare to approved brief/anchors and persist reusable IDs. Use actual audio timing; recalculate cuts/subtitles after line replacement. No recurring human voice session or specialist script-editor dependency. Missing eligible voice/rights route blocks the provider, not a fabricated license record.

## 8. GPU generation, presets and lifecycle

Preset registry records exact base/LoRA/model mode/workflow/node hashes, GPU and host RAM, precision, resolution, frames, steps, attention backend, supported reference/voice/first-frame controls, measured full-job latency, costs and acceptance by shot class. Entries remain disabled until contract/quality benchmarks pass. Four/eight-step naming does not prove quality or Thai support. Never stack already-included speedup factors or substitute text-only speed results for reference-capable workflows.

Routing first filters hard controls/rights/hardware/budget, then ranks critical-quality pass and cost per accepted shot/retained second including failed attempts and downstream repairs. Simple inserts may use fast presets; emotional/dialogue shots use the best qualifying accepted-cost preset. A tier promotion consumes an ordinary attempt and remaining funds. Stop at configured attempt/cost limits; no blind whole-episode retry.

Lifecycle: atomically claim lease/reserve → acquire or reconcile an owned pod → verify pinned container/model/node schema and health → submit ComfyUI API-format graph → persist prompt ID → monitor/poll history → verify complete MP4/audio/checksum → copy durable outputs → review/retry bounded batch → shut down and verify compute stopped. `executed` sampler events alone do not prove completed media output. Provider create timeouts trigger resource reconciliation before retry.

The independently scheduled janitor only manages verified pipeline-owned tagged resources, checks expired leases/heartbeats/exposure, and stops/terminates orphans with evidence. Persistence and shutdown choices distinguish disposable disks from retained caches and continuing storage charges. Cancellation/error branches release reservations and clean resources after accounting for unresolved usage; crashes cannot depend solely on an in-process `finally` block.

## 9. Editing, captions, hooks and two-pass QA

Editing consumes a schema-validated EDL with explicit source/timeline in/out, camera/crop, dialogue bindings, audio and transitions. Normalize timebases/frame rate/dimensions/audio; use continuous ambience/music, intelligible dialogue and correct Thai font shaping. Source script is never rendered directly into shell commands. Generate caption timing from actual audio and compare actual speech meaning with intended lines. Subtitles cannot conceal wrong spoken content.

Create clean master, Thai/English caption tracks, required platform variants/covers and three 20–40s hook candidates using accepted footage before Gate 2. Exports/QA remain in budget. Include all candidates in final review; publish only eligible scheduled variants. No new video generation for hook testing. Hook ledger records changed treatment, shot sources, platform/cohort/slot/duration/subtitle/offer, paid/organic status and counts. Matched organic comparisons are observational.

QA comprises deterministic decode/duration/stream/black/freeze/silence/peak/caption-bound checks, independent ASR/critical-term checks, identity/wardrobe/prop checks, supported temporal/lip detectors and narrative/localization analysis. Known unavailable coverage is `UNKNOWN`, not `PASS`. Brief defects require dense local review; a sparse video summary cannot certify lip-sync precision.

Pass A receives actual media plus neutral observation questions; excludes intended dialogue/plot/writer rationale. Independent transcript and immutable observations are persisted with input hashes before Pass B. Pass B receives those plus script/canon/identity anchors and outputs timecoded mismatches/coverage/repair instructions; it cannot overwrite Pass A to agree with the script. Neutral ASR vocabulary assistance, if used, is logged and must not supply expected line answers. Separate calls are mandatory; different model vendors are optional based on quality/cost.

Finding contract: asset/time interval, check ID, expected/observed state, evidence, severity, confidence, coverage and repair dependencies. Outcomes `PASS`, `REPAIRABLE`, `BLOCKED`, `UNKNOWN`; critical unresolved findings block release. Narrative confidence alone cannot grant approval.

Repair planner targets caption/line/shot/edit depending on root cause, prices the repair, reserves funds, invalidates dependent outputs and rechecks only necessary scope plus final consistency. Three shot attempts/two final repair rounds maximum by default. Persist all failures. Final human feedback uses the same repair path; ambiguous local comments do not become global preferences. Explicit series preferences are versioned and cannot override budget/rights/published canon.

## 10. Publication, memberships and agency operation

Each account/provider capability record defines codecs/durations/account types, full-video vs short route, upload/schedule/status/readback, AI/sponsor disclosures, metadata/cover updates, insight definitions, comment actions and DM window rules. Confirm using current official documentation and controlled authorized account tests. Live implementation may not assume research-date quotas remain valid.

Default target scope includes all four platforms with appropriate full/part/promo assets. Configure required vs optional release slots before approval. Independent valid posts may publish while one destination is held, but the episode does not qualify as a completed four-platform release until every required slot verifies. No browser-bot or recurring manual phone upload fallback. Unavailable Direct Post approval/label field/long-video route is a real blocker for that destination.

Release states: `RELEASE_APPROVED → SCHEDULED → SUBMITTED → PROCESSING → PUBLISHED_VERIFIED`, plus typed retry/uncertainty/failed outcomes. Key `(series, episode, part, locale, platform, account, release_slot)` is unique. Persist external IDs before subsequent steps where available; reconcile ambiguous uploads/schedules rather than resubmit. Check visible playback/privacy/labels/subtitles/link path where readable; report unverified fields.

Represent dependent release order as a DAG: next free part/full episode must actually exist before its promotional CTA promises availability. Store IANA schedules/concrete UTC slots; daylight-saving changes and expired windows cannot silently change the announced free date. Retry transient errors within deadline; unsupported/missing permissions are not transient.

Community workers ground answers and metadata in released catalog, approved offers and schedule. Allow truthful bounded title/caption/description/hashtag/cover optimization under approved policy with version history/rollback, proposed 24h cooldown and maximum two substantive edits per post in its first seven days. Use supported experiments only; no repost spam. Public replies address ordinary questions/praise/criticism; no fake real-actor persona or invented promises.

DMs use configured keywords/permitted inbound interactions and current provider message-window eligibility. A public comment is not blanket permission for unlimited follow-up. Moderate clear policy-defined spam/scams/threats where supported; preserve ordinary criticism, take no destructive action when uncertain, no automatic account bans by default. Dedupe event/reply IDs, cap per-conversation/action/token usage and record policy/grounding versions. Cold outreach, refunds and new sponsor/contract commitments are outside this organic automation scope.

Membership adapter supports an explicitly selected verified Patreon or Buy Me a Coffee route, with truthful recurring price, finished early-access content, eventual free schedule and provider-enforced entitlement. Public routes resolve from verified catalog state; an unlisted link is not entitlement enforcement. Verify provider webhooks/signatures/access; do not handle raw card data. Alternate membership backend can remain optional after one working route, because the original requirement was Patreon and/or BMC. No paid early-access offer for nonexistent/unapproved media.

## 11. Metrics, learning, qualification and human review

Snapshots at 24h/72h/7d retain platform definitions, observation time, country/source when available, paid/organic split, counts and missingness. Do not combine incompatible view definitions or invent country-by-retention cross-tabs. Reports distinguish experiments from uncontrolled comparisons and avoid projected Western ad income as observed revenue.

Qualification metrics: all variable spend including failed jobs divided by successful approved/published episodes and by finished published minutes; human review/revision minutes; attempted-to-unassisted-completed fraction; retries/failure stage; duplicate/wrong releases; actual continuation with denominator. Fixed subscriptions/engineering and any manual intervention remain visible in fully allocated cost.

Ten consecutive episodes must meet cap/QA/Gate-2/required-publication/no-hidden-manual-work conditions before unattended volume increases. Human final feedback is allowed only when repair executes automatically. A failed episode or manual technical fix resets the streak; record exclusions rather than erase attempts. Track initial management window for seven days separately; younger episodes are pending. Full qualification requires ten corresponding management windows without hidden fixes/violations. A two-week pilot is an initial test, not a claim that this is complete.

Final-review UI must show actual playable episode/cuts/covers, first-episode reference package, subtitle preview, QA findings and coverage, costs/remaining funds, scheduled destinations/offers/policy and timecoded revision categories. A proposed steady-state review target is 10–15 minutes per five-minute episode, not a performance guarantee. Interface implementation is minimal; it must not hide uncertain tests behind an aggregate green score.

## 12. Configuration, security, operations and release evidence

Default execution mode is offline/mock: paid requests, cloud resource creation and public actions disabled. Use explicit configuration for authorized paid benchmarks, controlled account tests and production. A future agent implementing code must not infer live deployment authority from this SPEC or fill missing configuration from unrelated projects.

Secrets stay in configured secret storage, never schemas, prompts, committed files, public URLs or evidence logs. Authenticate review/internal APIs, authorize owner scope, verify webhook signatures, protect cookie sessions against CSRF as applicable, rate-limit public endpoints, and scope private asset links to review access. External URLs are fetched through source/host policy and bounded download limits. Comments, model outputs and reference metadata are data, not executable instructions. Invoke FFmpeg through validated argument arrays/job presets.

Persist audit/DB state and versioned assets off ephemeral GPUs. Define backups/restore, asset retention, token rotation, provider outage/cancellation and queue-recovery runbooks. Crash recovery replays idempotent effects from durable IDs/events; no unsupported exactly-once claim for external APIs. Stop compute before human waits; storage charges remain accounted separately.

Required observability: per-stage timing/full generation time, provider usage/reservations/accruals, queue lag, orphan leases, uncaught failures, approval mutations, publish uncertainty, action moderation/reply counts, QA coverage and intervention count. Redact identifying/payment data from routine reports. Alert through a configured owner channel only after that channel is authorized.

## 13. Verification and rollout acceptance

Bootstrap provides reproducible `make contracts`, `make lint`, `make test-unit`, `make test-contract`, `make test-integration` and `make check` commands; these are required future targets, not commands already available or run. Mock mode must have no paid network side effects. Contract tests use recording/fake adapters; containers for DB/queue/storage isolate integration tests from existing AIVORA services.

Minimum meaningful verification:

| ID | Required evidence |
|---|---|
| AT-01 | Concurrent paid reservations near US$10 cannot overspend the available allowance; settlements/credits/retries do not double-count or reset spend. |
| AT-02 | Worker/model credentials cannot approve; replayed/stale final approval fails; material media change requires the same Gate 2 again. |
| AT-03 | Episode two cannot render before episode-one identity lock; approved references are reused; unreviewed assets never inherit a lock. |
| AT-04 | Crash/reconnect at pod-create, Comfy-submit, asset-save and shutdown boundaries recovers without duplicate paid work or orphan compute. |
| AT-05 | Seeded critical defects—wrong amount/speaker, identity swap, missing audio, bad caption/CTA—block or repair; unknown coverage is visible. Known suite results do not prove universal Thai accuracy. |
| AT-06 | Observation request cannot access intended script; immutable first report survives comparison/repair. |
| AT-07 | Timecoded local feedback repairs only affected dependencies; global preference requires explicit scope; tier promotions consume ordinary retries. |
| AT-08 | Comment flood cannot starve due publication or spend protected production reserves; shared provider quota remains enforced. |
| AT-09 | Duplicate webhooks, ambiguous upload timeout, expired token, unsupported disclosure and DST scheduling cases cannot produce duplicate/wrong/unapproved posts. |
| AT-10 | Three hook candidates use accepted source footage with no new video jobs and appear in the existing final review package. |
| AT-11 | Free/paid catalog and DM messages remain truthful through delayed release, cancellation, public transition and insufficient metered-management budget. |
| AT-12 | Qualification includes failed costs/manual fixes, resets correctly, distinguishes pending seven-day windows, and requires ten rather than one successful episode. |
| AT-13 | Rights/capability blockers remain blockers despite a green model score; logs/private links/webhooks do not expose credentials or bypass owner scope. |
| AT-14 | One complete rights-cleared original Thai episode traverses the real configured pipeline with the two gates and actual billed costs, then a controlled supported release/management test records real evidence. No claim based solely on mock success. |

Rollout sequence: local contracts/core/fake providers → isolated service integration → authorized rights/quality/cost benchmarks → controlled account publishing/management tests → one complete episode → ten-episode qualification. Software completion, provider qualification and business/audience validation are separate statuses. Missing credentials/rights/account approval block the corresponding live test, not useful offline implementation work. No new recurring creative human gates are introduced to bridge missing automation.

## 14. Open evidence requirements and source anchors

Before live activation, record: globally eligible model/output rights; exact Thai-capable voice/reference route; optimized compatible preset benchmarks at intended resolution; real GPU/RAM/hourly limits and billed throughput; all required publishing/disclosure/update/insight/community capability tests; selected membership backend and payout/access behavior; QA error coverage; real cost fit and final-review time. Public H3 terms previously researched did not clearly clear the proposed US/EU/UK output release; optimizations do not resolve that issue.

Primary integration anchors to recheck when implementing: [ComfyUI server routes](https://docs.comfy.org/development/comfyui-server/comms_routes), [Runpod pod lifecycle](https://docs.runpod.io/sdks/graphql/manage-pods), [n8n queues](https://docs.n8n.io/deploy/host-n8n/configure-n8n/scaling/enable-queue-mode), [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [video-review API coverage](https://ai.google.dev/gemini-api/docs/video-understanding), [FastH3 modes](https://haoailab.com/FastVideo/cookbook/minimax-h3/), [H3 license](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE). Platform/membership/DM sources and their limitations remain in the linked research plan. These sources establish interfaces or terms, not a successful end-to-end implementation.
