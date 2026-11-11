**Verdict: REWORK.** The architecture is workable, but v0.1 leaves approval compatibility, concurrency, accounting and recovery decisions to the builder. Several literal implementations would change V1 behaviour or fail existing checks.

Reviewed Phase A v0.1, master v0.4.2, A0 v0.2 and the factmap against branch `feat/microdrama-m0-m4`, HEAD `0851374`. This checkout currently ends at migration **0025**; 0026/0027 are prerequisites, not present implementation evidence. No writes or tests were performed.

References below: `A` = `docs/microdrama-system/v3-workflow/phase-A-spec.md`; `S/` = `microdrama/src/microdrama/`; `M/` = `microdrama/migrations/`; `X/` = `microdrama/tests/`.

**Reuse register: all rows assessed**

| Row | “Today” accurate? | Required-change assessment |
|---|---|---|
| R1 | Yes. | Enum addition is straightforward; command/schema/action consumers also change. AC-1/2/23. |
| R2 | Yes. | Incomplete feedback CHECK, version-specific action policy and effective-approval semantics. AC-1/2/16. |
| R3 | Yes. | Global action expansion changes V1; season notes cannot use today’s feedback writer unchanged. AC-1/2. |
| R4 | Yes. | Scope mapping is necessary; “revision checks reused unchanged” is incorrect. AC-3. |
| R5 | Yes. | Protocol lacks transactional binding, authorization and concrete command/route contracts. AC-3/6/22. |
| R6 | Yes. | Refusal until F is safe only if production cannot register test handlers or fall back to V1. AC-4. |
| R7 | Yes. | Handler-specific conditions are appropriate; preserve SQL package/caption/manifest checks. AC-3/23. |
| R8 | Yes. | Pinned legacy states provide compatibility storage, not reader isolation. AC-5/6/7. |
| R9 | Yes. | Inventory omits render polling, publication and analytics selectors. AC-5. |
| R10 | Mostly. | `scope.owner_season_rows` retrieves rows; it does not itself interpret state. GPU safety needs admission/transition integration, not just additional predicates. AC-9. |
| R11 | Yes. | Reuse count primitives selectively: the existing episode projection reads legacy state and its denominator includes wardrobe work. AC-22. |
| R12 | Yes. | Sensible shell approach; routes, selected-episode context and error states remain unspecified. AC-22. |
| R13 | Yes at inspected main. | Coordinate with A0’s runtime changes; `defer()` currently persists RATE_LIMITED regardless of cause. AC-7/23. |
| R14 | Yes. | New scopes require account lookup, receipt routing, allocations, policy and SQL changes beyond the enum. AC-10/11. |
| R15 | Yes. | Parent-first reservation admission alone does not establish hierarchy-wide safety. AC-8/12. |
| R16 | Yes. | Deferred budget waits are appropriate, but lifecycle projection and durable wakeup are incomplete. AC-7/11. |
| R17 | Yes for the named endpoint/module. | Existing analytics aggregation is not reusable unchanged for setup accounts or “cash.” AC-14. |
| R18 | Yes. | Completion-only checking and queued-job cancellation do not implement the required fence. AC-15/16. |
| R19 | Yes. | Reuse is appropriate; transaction boundaries and dispatcher topology are missing. AC-17/18. |
| R20 | Yes. | Advisory-lock ownership, catch-up, calendar scheduling and production selection are unspecified. AC-20/21. |
| R21 | Yes. | A useful skeleton, but not an executable fail-closed composition contract yet. AC-21. |
| R22 | Conditional forecast. | Current tail is 0025. Pin and re-audit the accepted upstream snapshot before assigning 0028+. AC-23. |
| R23 | Broadly. | Keeping V1 green is feasible; the stated global action change already contradicts an exact contract assertion. AC-1/23. |

**Issues and replacement wording**

**AC-1 — BLOCKING — Gate action policy changes V1 and contradicts the master.**  
Facts: `A:37–38` expands `SEASON_CONCEPT` globally. `S/contracts/states.py:122` is unversioned; `X/contract/contracts/test_states_routes_jobs.py:76` asserts exactly APPROVE/REJECT. Master §2.1 permits Approve/Revise/Reject; A independently removes Reject from CAST_LOCK/LAUNCH.  
**Replace:** “Preserve the V1 command/action contract. Introduce version-specific V3 decision validation, selected using the persisted workflow version. Apply master §2.1’s actions unless the master explicitly changes them. V1 concept Revise remains refused at its existing boundary.”

**AC-2 — BLOCKING — `RevisionNotes` has no compatible persistence path.**  
Facts: `M/0002_story_and_approvals.sql:205` requires a nonempty `feedback` array for every Revise. `S/core/approvals.py:119` writes every feedback item to **episode-scoped**, timecoded `feedback_events`. `S/review/forms.py:62` parses only timecoded feedback.  
**Replace:** “Define V3 season-note command fields and durable storage, including target identity/scope validation. Season Revise writes season revision notes, never episode feedback rows. Replace the feedback CHECK with gate-specific requirements; retain Gate 2 timecoded validation.”

**AC-3 — BLOCKING — Gate binding cannot reuse today’s revision check unchanged.**  
Facts: `S/core/approvals.py:64` locks `seasons`/`episodes` and compares **their** revision. `A:66,70` introduces track/input revisions; `A:92–105` gives binding/conditions no transaction argument. Existing decisions also enforce owner scope inside the decision transaction (`S/review/service.py:401,1129`).  
**Replace:** “Resolve ownership, workflow, active gate, content hash and authoritative decision revision under one caller-owned transaction and shared locks. The recorder uses a version-aware binding resolver. Record, handler writes, job enqueue and idempotent response commit atomically; callback failure rolls everything back. Idempotent replay precedes fresh binding validation.”

**AC-4 — BLOCKING — Test handlers can defeat the Gate 2 refusal.**  
Facts: `A:95–99` says Phase A registers test handlers for **every** V3 gate, while `A:41` requires V3 Gate 2 to be unavailable until F.  
**Replace:** “Normal compositions register no unavailable V3 gate handler and return NOT_AVAILABLE before recording or callbacks. Test handlers require explicit test-world injection and cannot enter production. Missing handlers never fall back to V1. Test all three Gate 2 actions through JSON and HTML routes.”

**AC-5 — BLOCKING — The discriminator is sufficient as normalized data, but the specified isolation is incomplete.**  
Facts: episodes have a required season FK (`M/0002_story_and_approvals.sql:61`), so another episode version column is unnecessary. However, `S/story/service.py:752` accepts pinned PLANNED episodes; selectors and direct service entry points do not derive workflow version. `_w05_render_poll` also accepts assets and resolves jobs (`S/scheduling/service.py:798`).  
**Replace:** “Make workflow version non-null, checked and immutable; prevent cross-version reparenting. Every episode/job/post entry point resolves its season and checks workflow before legacy execution. Guard direct services, handlers and replayed jobs as well as selectors. Until their V3 implementation exists, refuse V3 mutations explicitly.”

**AC-6 — BLOCKING — The track command table is not complete or enforceable.**  
Facts: `A:80–86` omits episode creation, production/release transitions, reject/cancel, amendment rewind and extension-scope creation. `set_extending(bool)` cannot represent master §2.2’s independent extension planning scope. Pinned SEASON_APPROVED also requires real approval/scope fields (`M/0002_story_and_approvals.sql:20`; `M/0007_m0_validator_hardening.sql:31`).  
**Replace:** “Specify each Phase A command’s actor, scope, expected revision, exact source/target, current hash-bound prerequisites, writes, jobs, events and replay identity. Add episode/extension creation and cancellation contracts. Later-phase transitions remain unavailable. Define the pre-LOCK legacy pin and the atomic LOCK write satisfying existing season approval constraints.”

**AC-7 — BLOCKING — Side states become a second, inconsistent lifecycle.**  
Facts: `A:65,69` provides one side state per entity, despite independent tracks and multiple jobs. `A:74–76` omits terminal failure as a BLOCKED writer. A0 §5.2 requires LLM_BLOCKED → Failed + BLOCKED. `S/core/jobs.py:575` hardcodes RATE_LIMITED.  
**Replace:** “Derive waits/blockers from scoped job/operation facts, or maintain a transactional projection keyed by contributing job and track. One resumed job cannot clear another’s wait. Include terminal failures, preserve Deferred cause/retry time, and project amendment wakeups only after the authoritative job transition commits.”

**AC-8 — BLOCKING — No complete lock order; extending existing helpers can deadlock.**  
Facts: `A:72,121` orders tracks and budgets but omits jobs and existing callers. `S/core/jobs.py:648` takes a job SHARE lock. `S/budget/billing.py:1296` locks a child account/reservation before calling shared settlement logic.  
A worker taking job → track can deadlock with amendment track → job; settlement child → parent can deadlock with reservation parent → child.  
**Replace:** “Publish one lock-order table covering command/idempotency locks, jobs, tracks, provider/lease/billing records, parent/child accounts, categories and reservations. Audit every caller-owned transaction against it. Acquire ancestor locks before entering shared ledger helpers; add competing-transaction tests for each identified inversion.”

**AC-9 — BLOCKING — Updating GPU predicates does not enforce human-wait safety.**  
Facts: `S/rendering/leases.py:212` is an EpisodeState transition guard; pinned V3 states bypass that invocation path. `heartbeat:1024` and janitor `_sweep_leases:240` read legacy episode state. Lease ownership is episode-only (`M/0003_budget_and_compute.sql:168`).  
**Replace:** “Attach V3 wait checks to TrackService gate/pick activation and lease admission under common scope locks. Verify shutdown before exposing the wait; cover heartbeat, claim/adoption/transfer and janitor candidate selection plus cause calculation. Define season-work ownership for later GPU consumers. Apply waits to affected work scopes, preserving unrelated approved releases.”

**AC-10 — BLOCKING — New budget kinds and lanes are not buildable through current dispatch.**  
Facts: `S/budget/service.py:372–375` routes every non-EPISODE request to the research account. `S/contracts/cost.py:160` validates only existing kinds. `S/budget/policy.py:35` recognizes three queues; jobs/reservations SQL also restricts queues.  
**Replace:** “Define explicit account lookup and receipt routing for every scope; unique season/setup accounts; parent/child season consistency; and aggregate-only SEASON semantics. Update reservation/receipt contracts, account factories, ledger loading, policy ownership, queue SQL and all relevant readers. Reject unsupported kinds explicitly—never route them through the research fallback.”

**AC-11 — BLOCKING — Cap amendments are neither a concrete SQL design nor a complete authorization contract.**  
Facts: `A:135` proposes an effective cap “through a view or trigger.” Existing SQL both caps and freezes `cap_micro_usd` (`M/0003_budget_and_compute.sql:13,33`); ledger loading reads that column. An EPISODE ≤$10 rule conflicts with an effective episode raise unless base/effective caps are distinguished.  
**Replace:** “Specify exact guarded DDL and mutation functions: immutable base caps, append-only approved amendments with account revision, old/new amounts, actor/session, reason and idempotency key; one deterministic effective cap shared by SQL and Python. Serialize amendment against admission, validate ancestor limits, define category top-ups and durable job wakeup, and refuse unapproved direct mutation. Keep V1 cap rules unchanged.”

**AC-12 — BLOCKING — Parent admission alone does not prove ‘no partial overrun.’**  
Facts: `S/budget/service.py:864,649` posts usage/billing to child accounts; release, expiry, GPU accrual and settlement also change commitments. `S/budget/ledger.py:443` deliberately preserves observed overruns. These paths need the same hierarchy serialization, especially when settlement releases room.  
**Replace:** “Define season commitment from canonical child reserved+accrued+settled counters, excluding attribution duplication and retaining expired/unknown exposure. Serialize every commitment-changing path with parent admission. State that admission cannot exceed caps; preserve unexpected actual billing and block further paid work truthfully. Cleanup reservation refusal must never prevent stop/terminate or accounting.”

**AC-13 — SHOULD-FIX — Step caps and initial setup authority are missing.**  
Facts: R-12.7 and V3-AT-21 require step caps; `A:121–125` checks categories, which span multiple steps and permit recovery spill. `A:114` invents an operator-editable $30 setup default where master §12.3 requires an operator-approved setup sub-budget.  
**Replace:** “Define persisted step-budget identity and atomic admission alongside unit/child/season checks, with explicit spill policy. Treat $30 as a proposed default; paid setup requires recorded approval. Define the episode-count/cap basis before LOCK and amendment rules for count changes/extensions. Specify forecast checkpoints before CAST LOCK and rendering.”

**AC-14 — SHOULD-FIX — Costs and A-T11 conflate different accounting quantities.**  
Facts: `A:49` says cash = charges + allocations. `S/analytics/cost.py:129` recognizes SEASON_RESEARCH, not SEASON_SETUP. Its episode spend includes commitments; charges can include both accrual and final settlement. `A:252` demands one charge per paid call, although GPU lifecycle accounting legitimately has several receipts.  
**Replace:** “Reconcile cash, accrued/unsettled usage and reserved exposure separately using ledger semantics. Count setup once; allocations are attribution, not new cash or episode-cap consumption. Persist step/provider attribution. Test exactly-once posting per canonical receipt, including multi-receipt operations. Show subscription allocation, estimates and quota separately.”

**AC-15 — BLOCKING — A completion re-read does not fence concurrent or intermediate writes.**  
Facts: `A:183` bumps season `input_revision`, but §3 defines no such season column. An ordinary re-read can observe revision N, then an amendment commits N+1 before the worker writes. Provider helpers may already persist assets before handler completion (`S/pipeline/handlers.py:186–189`).  
**Replace:** “Define season and episode content revisions separately from display revisions. Validate expected revisions at enqueue/admission and before every canonical mutation. Hold the same revision locks as amendments through each mutation transaction. Apply the fence inside collectors, acceptance, continuation and reconciliation paths. Preserve provider results/receipts as quarantined evidence when stale; never install them as current content.”

**AC-16 — BLOCKING — Amendment atomicity and cancellation/reconciliation are underspecified.**  
Facts: `A:184` introduces SUPERSEDED approval status without a storage/read model; approval rows are append-only. `JobService.cancel` opens its own transaction (`S/core/jobs.py:875`), revokes running leases and leaves external work intact. `finish` then refuses the old holder; unresolved operations also prevent the promised stale Succeeded outcome (`:678,696`).  
**Replace:** “Use append-only approval-supersession records and effective-authority readers. Provide transaction-owned cancellation/invalidation helpers. Atomically fence affected work and unpublished submission authority, including queued continuations. Reconcile cancelled jobs’ external operations through an authorized reconciliation path, retaining exposure and receipts; stale workers do not finish cancelled jobs. Bind Confirm to a revalidated impact hash/revision and regeneration authority.”

**AC-17 — BLOCKING — `consume_once` does not make sending transactional; dispatcher fan-out is undefined.**  
Facts: `S/core/events.py:237` deduplicates effects committed in its transaction. Telegram cannot join it. `event_dispatches` has **one row per event**, not per consumer (`M/0001_foundation.sql:133`), so a second dispatcher can miss already-dispatched events.  
**Replace:** “Atomically consume the source event and enqueue one durable notification intent, uniquely keyed by event/channel. Send later. Specify either shared dispatcher fan-out or an independent domain-event consumer that does not use global dispatch marks as its consumer cursor. Define historical-event bootstrap and irrelevant-event handling.”

**AC-18 — BLOCKING — Bot attempt outcomes omit the crucial crash window.**  
Facts: `A:206–213` has only post-send outcomes. Crash after Telegram accepts but before DELIVERED persists can cause repeated unflagged sends. An HTTP 5xx or malformed success response may also be ambiguous; not every HTTP error proves non-delivery.  
**Replace:** “Persist and claim a uniquely numbered attempt before sending; persist its outcome afterward. Recover unfinished attempts conservatively as ambiguous. Allow one durable, globally counted possible-duplicate retry after ambiguity, then stop visibly. Define retryable/permanent errors, backoff timestamps, exhausted-state handling and Telegram response validation. Never sleep inside the outbox transaction.”

**AC-19 — SHOULD-FIX — Two proposed event names are invalid.**  
Facts: `A:204` names `budget.80` and `budget.100`; both violate `S/contracts/events.py:21` and `M/0001_foundation.sql:118`, whose dotted segments must start with a letter.  
**Replace:** “Use `budget.threshold_reached` with integer threshold/scope/revision fields; deduplicate each threshold crossing. Register valid names and payload schemas for every new event.”

**AC-20 — BLOCKING — Scheduler singleton and calendar semantics need a concrete implementation.**  
Facts: `S/scheduling/service.py:116–136` reads firing state separately from handler transactions. `ScheduleCatalog.due` uses elapsed intervals (`S/scheduling/registry.py:48`), so a 24-hour interval does not mean 09:00 Bangkok. A singleton also does not prevent crash replay of direct actions.  
**Replace:** “Hold a namespaced advisory lock on a dedicated connection throughout the tick, including all handler transactions; concurrent callers skip, and crash releases ownership. Give each direct action a durable period identity. Define first-run/downtime catch-up, Bangkok calendar scheduling, summary dedupe, SLO measurement windows, buffer calculation and health freshness/error thresholds.”

**AC-21 — BLOCKING — Production scheduler selection and startup dependencies are missing.**  
Facts: `A:232` adds composition selection only to serve/worker. `S/scheduling/__main__.py:40` always constructs the offline world. Requiring scheduler health when constructing the scheduler itself can also prevent first startup.  
**Replace:** “Add explicit production composition selection to scheduler and notification entry points. Define role-specific dependencies, bootstrap readiness and freshness checks. Bind qualification records to provider/configuration/evidence versions and expiry; require existing capability/rights/preset gates where applicable. Preserve A0’s dispatch-time checks. Ship production in a separate composition with separate configuration; staging’s guards and defaults stay unchanged.”

**AC-22 — SHOULD-FIX — The UI/progress contract is too abstract for acceptance.**  
Facts: `A:148–166` gives no route/response schemas or precedence rules. “No decision at current revision” does not distinguish an opened gate from a future gate. `S/review/progress.py:562,587` still projects legacy states and recursively projects episodes.  
**Replace:** “Define durable gate activation/binding, selected-episode request context, typed V3 responses, tab denominators, status precedence and one primary action per tab. Specify routes and empty/loading/error/unavailable states. Reuse work-count helpers only; derive V3 statuses from V3 authority. Preserve owner scoping and V1 payloads. Polling must prevent overlapping requests and recover visibly from failures.”

**AC-23 — BLOCKING — Migration/contract ownership and acceptance need an executable boundary.**  
Facts: master §10.0 assigns jobs/provider-operation schema additions to A0, whose §5.2 already specifies Deferred/WaitExternal support. `A:265–267` does not allocate the remaining queue/schema changes, and permits V1 test changes only for filters despite planned command/schema changes. `microdrama/Makefile:33` checks generated-contract drift.  
**Replace:** “Pin accepted T031+A0 commits and allocate every migration, enum, queue, input-model and runtime change once. Preserve applied migration bytes. Ship guarded DDL, generated schemas/examples/catalog updates and explicit upgrade tests. Keep existing V1 expectations; add version-specific tests rather than weakening them. Distinguish Phase A foundation proof from later composed/live qualification.”

**Reader/writer inventory that the register must explicitly carry**

- **Gate consumers:** `contracts/season.ApprovalCommand`, `contracts/states.GATE_ACTIONS`, generated contracts/examples—including the invalid `gate1_revise` example at `contracts/examples.py:2180`; `core.approvals` revision/feedback writers; `core.state_machine._require_gate_approval`; review JSON routes, HTML forms/templates, metadata preparation and package status writers.
- **Approval SQL:** concept/entity/action/feedback CHECKs and uniqueness in 0002; `md_approval_requires_human_session`, `md_season_approval_binding`, `md_release_package_binding`, `md_episode_release_requires_approval` in 0007; Gate 2 package/caption guards in 0008–0010; manifest/current-slot binding in 0021. Preserve or explicitly version each affected rule.
- **Additional approval-authority readers:** `references.identity_lock`, `qa.repairs`, `publishing.metadata.load_approved_metadata`, publishing admission, `memberships.catalog._require_approval`, and qualification. Supersession must affect their authority checks, not merely the UI.
- **Legacy workflow entry points:** research `_open_run/_write_proposal`; intake selection/status/phase/research/workbench; story `compile_season/_claim_episode/_persist_success`; references claim/persist/change; editing claim/persist; QA repair/reopen; packaging; package storage; publishing scheduling/admission/completion/release views. Unsupported V3 paths need explicit refusal.
- **Selectors:** name `_w02_compile_backstop` explicitly; add `_w05_render_poll`, `_w09_publish_submit`, `_w09_publish_poll`, `_w11_analytics`. Shared job/GPU/billing janitors must retain both-version coverage through appropriate adapters, rather than receive blanket V1 filters.
- **State views/safety:** review summaries/page enablement/decidability/metadata, season and episode progress models, owner-scoped row retrieval, `human_wait_guard`, lease claim/adoption/heartbeat/transfer, janitor candidate query **and** `_cause`, qualification production/management predicates. Fixture/mock-runner assumptions remain V1.
- **Budget readers/writers:** account factories/lookups, `AccountRow.cap/committed`, reservation/release/expiry, usage/GPU posting, billing allocation/recovery/finality—including caller-owned settlement locks—transfers, research allocation, reports/API, analytics cost/qualification, `CostPolicy`, Settings and registry policy loading.
- **Budget clients/contracts:** all scope/queue validators and SQL CHECKs, category ownership/shutdown policy, and reserving callers in research/story/references/rendering/editing/QA/community/membership metering. Central hierarchy enforcement should protect these callers without changing their V1 semantics.

**Acceptance gaps**

| Obligation | Additional proof required |
|---|---|
| V3-AT-1; R-11.2–11.5 | Selected episode, all tab denominators/actions, unopened versus open gates, concurrent waits, authorization, unavailable phases and polling failures. |
| V3-AT-2 | Negative command/service/SQL paths; foreign owner; service credential; CSRF; wrong gate/scope/hash/revision; callback rollback; concurrent decisions; production test-handler exclusion. |
| V3-AT-13 | Multiple receipts per operation; accrual→settlement replacement; late adjustments; setup attribution; unknown exposure; effective amended caps; cash/estimate/quota separation. |
| V3-AT-16; R-11.6 | Crashes before/after send and before outcome persistence; concurrent senders; restart during ambiguous retry/backoff; pre-dispatched events; dead letters. |
| V3-AT-20 | Crash at each intent/submit/result/receipt boundary; stable request identity; UNKNOWN without recoverable external ID; cancellation plus late success; no exposure release or blind resubmit. |
| V3-AT-21; R-12.7 | Step caps, direct-SQL amendment rejection, reserve versus amendment/settlement/release/late billing, expired holds, parent overrun blocking and shutdown despite exhausted caps. |
| R-12.6 | Locked revision race tests, intermediate writes, season-scope work, effective approval supersession, queued publication invalidation, confirmation revalidation and cancelled-operation reconciliation. |
| Foundation acceptance | Upgrade populated V1 databases; guard/catalog tests for every new table; pinned upstream regression gate; real runtime/composition tests with fakes. A later F/G test does not substitute for these foundation guarantees. |

**Split the build into ordered packages.** Each should receive scoped independent review and its own acceptance receipt; retain `make check` and V1 `make pilot` before accepting the package.

1. **A1 — Contracts, discriminator, tracks and gate authority:** exact DDL/commands, V1 guards, unavailable-handler policy. Gate: expanded A-T1–6 and migration/contract checks.
2. **A2 — Hierarchical accounting:** all money mutation paths, guarded cap amendments, step budgets and cost reconciliation. Gate: expanded A-T9–11 plus lock/concurrency/shutdown tests.
3. **A3 — Runtime and fencing:** reconcile A0 changes, queue deployment, revision/lease guards, stale-result quarantine and cancellation recovery. Gate: expanded A-T8/12/18.
4. **A4 — Amendment coordinator:** dependency registry, impact confirmation, effective supersession and submission invalidation. Gate: transaction rollback, race and published-immutability tests.
5. **A5 — UI shell:** typed progress, selected episode, waiting/recovery/cost screens and polling. Gate: expanded A-T7 with actual routes/templates.
6. **A6 — Notifications, scheduler and production skeleton:** durable delivery, singleton/calendar schedules, role-specific composition/readiness. Gate: expanded A-T13–17 and the complete offline V3 shell pilot.

The discriminator and reuse strategy can preserve V1. The present register does not yet specify enough enforcement to establish that preservation—or the claimed concurrency guarantees.

