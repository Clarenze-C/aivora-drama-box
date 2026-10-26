# Microdrama build review — 25 October 2026

Reviewed against SPEC.md and task_breakdown.md, contract version 1.6.0. This is a source and behavior review of the current checkout. It does not change task acceptance, deploy services, authorize provider spending, or qualify any real account.

**Verdict: substantial offline implementation, with material integration defects still to fix before live qualification.** The ledger's T001–T030 acceptance is useful module-level history, but the release-readiness statement that only external prerequisites remain is too strong. A scripted mock demonstration and an unattended, recoverable application are different acceptance criteria; the current demonstration supplies orchestration the scheduler and workers do not supply themselves.

## What exists and is useful

- Versioned Pydantic/JSON contracts, generated examples and drift checking; 17 ordered migrations; PostgreSQL repositories with actual transaction/concurrency tests.
- Exact micro-USD reservations, settlement and protected shutdown funds; persisted job identities, claims, outbox primitives, approval records and owner sessions.
- Research, story/canon/directing, reference/identity, rendering, editing, QA, review, publishing, community, membership and analytics modules with extensive offline tests.
- Real local FFmpeg assembly, subtitle exports, variants, covers and hooks. Media observations and script comparison are separate services, with immutable observation records.
- A minimal authenticated review UI, stale-package checks, CSRF controls, private media routes and transactional episode-one identity lock.
- Four platform adapter implementations against fixture transports. Unsupported capabilities remain held, and fake URLs/usage are labeled.
- Strong default refusal of paid, cloud and public effects. The current composed world is deliberately offline-only.

These are valuable foundations. They do not yet demonstrate real Thai performance quality, viable GPU throughput, the all-in US$10 cap, supported unattended four-platform publication, a working paid membership route, or ten actual qualifying productions.

## Findings requiring fixes

Priority P1 means fix before using the affected path for live operation or claiming M4 automation complete. P2 means a material reporting/coverage defect that should be fixed in the same remediation cycle. Findings below distinguish direct boundary reproductions from source-traced integration gaps.

### F01 — P1: the scheduler cannot drive the workflow demonstrated by the runner

Evidence: [scheduler](../../microdrama/src/microdrama/scheduling/service.py), [runner](../../microdrama/src/microdrama/pipeline/runner.py), [handlers](../../microdrama/src/microdrama/pipeline/handlers.py), [release scheduling](../../microdrama/src/microdrama/publishing/slots.py).

The runner creates episode rows itself, explicitly routes/submits every shot, polls and accepts outputs, constructs observation/comparison jobs, prepares review packages, and constructs publication submission commands. Those steps are essential application behavior. The scheduler does not replace them:

- W03 discovers existing PLANNED episodes; it does not create the next approved episode. Gate 1 only queues season compilation.
- W05 polls existing render operations; it never dispatches the initial shots. Its SQL filters provider `comfy`, while the composed fake client persists operations as `fake-comfy`, so even those existing mock operations are missed. The composed runner also never calls `leases.claim` / `leases.ensure_pod`: the successful pilot's zero-live-lease assertion does not prove a real lease was acquired and stopped around rendering.
- W06 selects every RENDERING episode without a main edit; it does not establish that the manifest's accepted shot set is complete before proposing assembly.
- W07 enqueues only `qa.technical`. Its handler does not enqueue Pass A, Pass B, repairs or packaging. Once any QA finding exists, W07's selection excludes the episode, so it does not supply the missing continuation.
- Gate 2 queues `publish.schedule_release`; that service creates SCHEDULED post rows. No recurring scheduler submits those rows. The runner creates the submission commands itself.
- The publication timer only selects SUBMITTED posts. An adapter may return PROCESSING directly at submission; that row needs a poll job too. Ambiguous submissions have no corresponding recurring reconciliation discovery here.

**Effect:** operating the advertised scheduler/worker path can stall or propose premature work even though `MockPipelineRunner.run()` succeeds. Module-local recovery tests do not establish recovery of the whole application.

**Fix:** move progression into durable services/event consumers or explicit scheduled discovery, with semantic keys bound to input versions. Connect render dispatch to owned pod acquisition, health checks, heartbeat, billing and verified stop. Discover due approved slots, PROCESSING posts and uncertain operations. Gate 2 remains a human action; all other progression must occur without invoking runner methods.

**Acceptance:** start from a season request, supply only the two human decisions, and run normal scheduler/worker entrypoints through release and management. Repeat with processes restarted between stages, delayed shots, processing-first publication and uncertain outcomes. Assert that an owned pod actually existed during rendering and was verified off before review.

### F02 — P1: queued repairs fail and human feedback is routed to the wrong planner

Evidence: [repair handler, line 314](../../microdrama/src/microdrama/pipeline/handlers.py#L314), [repair return type and planners](../../microdrama/src/microdrama/qa/repairs.py), [review revision enqueue](../../microdrama/src/microdrama/review/service.py#L812).

`plan_from_findings()` returns `RepairPlanOutcome`, whose ID is `outcome.plan.plan_id`. The handler reads `outcome.plan_id`, raising AttributeError for a valid planned repair. Its supposed no-work branch is unreachable: no repairable input raises `NoRepairableInput`, rather than returning an outcome with a null ID.

The same handler always calls `plan_from_findings`, including jobs created by a Gate 2 REVISE action with trigger `human_feedback`. It never calls `plan_from_feedback(episode_id, approval_event_id)`, even though the review job carries the approval as its causation ID. Human comments can therefore be ignored or the job can fail for lack of machine repair findings.

**Reproduced:** the boundary probe invokes the registered handler with the actual return-model type and observes AttributeError. A feedback-triggered input calls only the findings planner; an empty findings result raises the typed exception.

**Fix:** consume the nested return contract; explicitly distinguish findings from human feedback and pass the originating approval ID. Handle no-work outcomes intentionally. Add composed tests that click Revise, execute the queued repair and return a changed package to the same gate.

### F03 — P1: repair completion does not establish changed, releasable downstream media

Evidence: [repair execution](../../microdrama/src/microdrama/qa/repairs.py#L1100), [caption persistence](../../microdrama/src/microdrama/qa/repairs.py#L1259), [reference replay check](../../microdrama/src/microdrama/references/service.py#L1289), [review media](../../microdrama/src/microdrama/editing/variants_service.py#L1350), [world composition](../../microdrama/src/microdrama/pipeline/world.py).

This remains after fixing F02:

- Caption repairs insert a new CURRENT caption-track body without an exported subtitle asset. They immediately reopen packaging, without rebuilding the existing burned-caption outputs/affected derivatives. Review's caption media links are derived from `caption_tracks.asset_id`, so the new track can lack a playable/downloadable caption artifact while old burned video remains.
- Shot repairs use the default `JobsShotDispatch` whose `dispatch_repair` raises ServiceUnavailable. The composed world does not install a router-backed replacement.
- Line repair supersedes an audio asset and requeues reference preparation, but the reference replay check considers the already-bound manifest sufficient for a replay. It does not check whether the line audio invalidated by the repair needs regenerating.
- Asynchronous repair plans mark their findings RESOLVED after dispatching/requeueing work, before successful replacement and required QA have established that the defect is gone.

**Effect:** unit tests can prove that a cue row changed or a job was queued without proving the exported review/release media was repaired.

**Fix:** make repair dependencies explicit: changed source → regenerate the affected output and caption artifact → rebuild affected exports/hooks → actual-media recheck → resolve finding → seal new package. Wire the real shot-dispatch port. Teach replay checks to honor invalidated inputs. Persist failed/in-progress execution truthfully.

**Acceptance:** seed a caption defect, wrong spoken line and defective shot separately. Drive repairs through registered handlers; verify replacement bytes/hashes, subtitle asset accessibility, correct affected derivatives, ordinary attempt/budget usage and clean re-review. No premature finding resolution.

### F04 — P1: shared provider limits are not enforced by the composed runtime

Evidence: [runtime construction](../../microdrama/src/microdrama/pipeline/world.py#L156), [demo deployment](../../microdrama/src/microdrama/pipeline/runner.py#L107), [throttle](../../microdrama/src/microdrama/workers/runtime.py#L209), [limiter](../../microdrama/src/microdrama/workers/limiter.py).

Both composed deployments pass a limiter but omit its job bindings. `_throttle` returns immediately for every unbound type. A shared instance existing in the world therefore does not establish that publication/community calls acquire quota. In addition, quota buckets are process-local dictionaries; separate worker processes get independent full allowances, and restarting resets them.

**Reproduced:** composed runtime bindings are empty; two limiter instances both acquire the same account's only token.

**Fix:** derive trusted provider/account keys for each provider-bound operation, require bindings for those operations, and enforce atomic shared buckets in Redis or PostgreSQL. Cover provider calls outside worker handlers too. Rate waits must not silently exhaust healthy work's transport-attempt allowance.

**Acceptance:** real composed handlers in separate processes share one account quota across publication/community and after restarts; inspect call counts and timestamps, not just counter handlers.

### F05 — P1: queue slots do not reserve execution capacity

Evidence: [worker cycle](../../microdrama/src/microdrama/workers/runtime.py#L142), [composed queue order](../../microdrama/src/microdrama/pipeline/world.py#L158), [AT-08 test](../../microdrama/tests/integration/validation/test_at08_flood_isolation.py).

`run_cycle` executes handlers synchronously in one process, production before publication before community. Slots bound the number of jobs visited; they do not isolate elapsed execution time. An FFmpeg/model call blocks publication later in that cycle, and a stuck community call prevents the next publication cycle. The flood test uses immediate counting handlers, which cannot reveal this failure mode.

**Fix:** deploy dedicated worker processes/capacity for production, publication and community, and run the janitor independently. Keep slow provider work in bounded submit/poll steps. Separate processes also require F04's shared limiter.

**Acceptance:** deliberately block a community handler and a production handler while a publication deadline arrives; publication and janitor must proceed in their own processes within a declared latency bound.

### F06 — P1: research costs are omitted from episode allowances and effective variable cost

Evidence: [allocation service](../../microdrama/src/microdrama/budget/service.py#L933), [episode account opening](../../microdrama/src/microdrama/story/service.py#L825), [analytics classification](../../microdrama/src/microdrama/analytics/cost.py#L107), [report wording](../../microdrama/src/microdrama/analytics/reports.py#L90).

The budget service explicitly requires the orchestrator to allocate research after opening episode accounts and before paid episode work. There is no application caller of `allocate_research_cost`; only its implementation and tests exist. Analytics instead classifies the season research account as fixed research, outside variable episode cost. SPEC §6 and MD-007 require allocated research in the US$10 ceiling; only subscriptions/engineering are separately fixed.

**Effect:** an episode can appear within cap while its directly attributable research/setup expense is absent. Rejected proposal costs remain recorded but can disappear from the effective variable-cost measure used to judge feasibility.

**Fix:** define and persist the allocation basis, book research shares before dispatch, account for unallocated/rejected/late-billed research at project level, and avoid counting both the source charge and allocated share in total project spend.

**Acceptance:** nonzero research spend, a rejected proposal, two episode accounts and a late bill reconcile exactly to provider spend and episode shares. Near-cap dispatch is refused when its research share would exceed the cap.

### F07 — P1: ten-episode qualification does not enforce the cost cap

Evidence: [episode facts](../../microdrama/src/microdrama/analytics/qualification.py#L66), [production verdict](../../microdrama/src/microdrama/analytics/qualification.py#L122).

The evaluator reads spend but `_production_qualifies` only checks published/managed state, null outcome and absence of manual interventions. A published episode over cap still qualifies, including after late billing. Qualification also relies on the coarse state instead of independently collecting the required approval/QA/release evidence. Seven elapsed days without an intervention are treated as management success without proving the corresponding management work ran without violations.

**Reproduced:** a published EpisodeFacts record carrying US$12 spend returns `True` for production qualification.

**Fix:** make an explicit eligibility decision from configured cap, complete attributed costs/unknown liabilities, actual approval binding, current blocking QA, required verified slots and management-window evidence. Overrun or an unmet invariant breaks the streak; incomplete evidence stays pending. Reevaluate when late costs arrive.

**Acceptance:** charge an otherwise published qualifying episode above cap after publication and verify streak reset. Missing required evidence or missing management execution must prevent qualification even when the clock advances seven days.

### F08 — P2: analytics double-counts overruns and truncates published minutes

Evidence: [spend sum](../../microdrama/src/microdrama/analytics/cost.py#L34), [overrun calculation](../../microdrama/src/microdrama/budget/ledger.py#L443), [effective cost](../../microdrama/src/microdrama/analytics/cost.py#L144).

`overrun_micro_usd` records the portion of committed spend above cap; it is already present in settled/accrued/reserved counters. `_account_spend` adds it again. The per-minute calculation also floors duration to whole minutes before dividing.

**Reproduced:** US$11 settled with a US$1 overrun reports US$12; US$1 / 210 seconds reports 333,333 micro-USD/minute instead of 285,714.

**Fix:** report overrun as a separate subset of committed spend. Compute per-minute cost using `total_micro_usd * 60_000 / published_duration_ms`, with an explicit final integer rounding rule. Add reconciliation tests using real service-created overrun records; the existing analytics test writes the counter independently and encodes the incorrect addition.

### F09 — P2: packaged QA summary drops unknown coverage

Evidence: [package summary](../../microdrama/src/microdrama/pipeline/packaging.py#L39), [review coverage](../../microdrama/src/microdrama/review/service.py#L488), [runner status](../../microdrama/src/microdrama/pipeline/runner.py#L557).

`_qa_summary` hardcodes an empty unknown-coverage list, counts only the latest 200 finding rows, and does not derive coverage from the required check policy. The runner labels QA GREEN whenever blocking findings are absent, even if critical check coverage is unknown. The review UI does separately show database findings/observation coverage, so this is not a claim that all uncertainty is hidden from that UI. However, the sealed package and stage report can disagree with the evidence used to approve it.

**Reproduced:** an UNKNOWN finding produces an empty package unknown list.

**Fix:** derive the complete package summary from current-media QA/coverage, retain missing checks as unknown, and distinguish completed-with-unknowns from fully checked/pass. Required critical coverage should have an explicit release policy; do not globally turn every unknown into a pass or invent a new human gate.

## Further engineering work before real operation

These are remaining deliverables, distinct from the defects above:

| Area | Actual state / work still needed |
|---|---|
| Runtime bootstrap | The integrated world always builds fakes and refuses other modes. Supply a durable application/worker composition with a real clock, production IDs, owned process lifecycle, persistent services and configured providers. |
| Repeated scheduling | `python -m microdrama.scheduling` constructs a new world with default fixed FakeClock T0. After the first persisted firing, repeated invocations do not advance due time. Provider fixture state also does not survive reconstruction. The advertised timer is not a restart-tested application deployment. |
| GPU/provider integration | Runpod's live adapter refuses even when effect flags/credential reference exist. LLM/image/voice/ASR/video-observer/Comfy transport edges need selected real implementations and configuration. Qualified preset evidence must precede enabling paid routes. |
| Platform/membership integrations | YouTube/TikTok/Instagram/Facebook transports and Patreon have live refusal stubs or no live implementation. Credentials alone cannot activate them. Implement transport/OAuth/error/reconcile/readback paths, then conduct T032 tests. |
| Four destinations | The demo requires YouTube only; other destinations are optional. Instagram/Facebook disclosure support is held by current code. This is honest mock behavior, but it does not meet MD-009's completed required four-platform release. Package requirements must come from approved scope rather than demo constants. |
| Release planning | Packaging uses fixed demo account/schedule/territory/disclosure choices and selects a generic variant rather than a destination-specific asset mapping. Bind the approved destination policy, route limits, caption/cover assets and actual release DAG. |
| Storage and transport | Runtime storage is local filesystem; Redis appears in settings/test helpers but is not the worker transport. Either implement the specified private S3-compatible store/Redis integration or document and accept an equivalent architecture with recovery evidence. |
| Analytics/management | Snapshot jobs wait for externally supplied observations; add real insight acquisition, scheduled community ingestion/metadata work and an actual membership catalog-sync path. Instrument review time and management incidents; do not replace unknown metrics with estimates. |
| Operations | Add reproducible worker/API/timer definitions and restore, cancellation, rotation, orphan recovery and outage runbooks. The deployment compose currently supplies local PostgreSQL/Redis only; image digests remain unqualified. |
| Status documents | README still lists n8n despite its removal. T031–T035 are TODO in CSV while readiness describes external blockers; future task rows retain old contract versions. Reconcile these after deciding the remediation scope. |

The current scheduler and publishing limitations above are repository observations, not a fresh determination of what third-party platforms support today. No vendor API or license was independently requalified in this review.

## Recommended next step and exit criteria

**Reopen the integration/readiness scope of T029/T030 and complete an offline remediation cycle before moving to T031.** Preserve accepted module work; repair the cross-module contracts and execution path.

1. Fix F02 and F03 so revisions work through the actual UI → durable job → changed media → QA → new package path.
2. Fix F01 and the clock/bootstrap gaps. Replace runner-supplied progression with durable application progression, including real lease lifecycle in the fake-backed integration flow.
3. Implement independent worker capacity and effective shared quotas (F04/F05).
4. Fix research attribution, eligibility and analytics math (F06–F08), then package coverage truthfully (F09).
5. Extend T030 with normal-entrypoint execution, process restarts, blocking-handler isolation, cross-process quotas, above-cap late billing and human revision cases. Keep the existing tests; test new behavior they currently omit.

The offline exit criterion is one persistent fake-backed season/episode run that needs only Gate 1 and Gate 2 human actions, survives process restarts, actually acquires/stops an owned fake pod, repairs seeded media faults, respects budget/quota rules, and finishes every required supported fixture slot. A successful runner script alone does not meet this criterion.

Then proceed in the original order:

- **T031:** choose a commercially eligible model/voice route; implement the real provider edges and benchmark representative Thai dialogue/emotion/identity/prop shots under explicitly bounded spending. Record full cold/warm usage, failed attempts, accepted quality and cost. No default H3/global-rights assumption.
- **T032:** implement and qualify controlled account transports, required labels/readback, community/DM rules and one real entitlement route. Required destinations that lack an eligible capability remain blocked.
- **T033:** produce one original 180–300-second Thai episode with actual billed costs and only the two agreed runtime gates.
- **T034/T035:** qualify ten consecutive actual productions and their seven-day management windows, then close operational traceability. This evidence cannot be supplied by ten mock runs.

## Verification record

Boundary probes are saved in [build-review-2026-10-25-probes.py](../../microdrama/evidence/build-review-2026-10-25-probes.py). They use small input/result substitutes at module boundaries and actual implementation helpers; they are not real provider tests or full database integration evidence. They deliberately assert the observed defective behavior and should be updated/replaced when fixes land.

Run from `microdrama/`:

```bash
PYTHONPATH=src .venv/bin/python evidence/build-review-2026-10-25-probes.py
```

Observed: exit 0, reproducing the repair contract mismatch, wrong feedback-planner selection, no-input exception, empty unknown list, overrun double-count, above-cap eligibility, minute truncation, missing limiter bindings and process-local bucket independence.

Fresh results:

- Contract generation/drift: **PASS**, version 1.6.0, 70 schemas, 32 valid / 88 invalid examples.
- Standard source/test/tool lint and formatting: **PASS**, 492 files formatted.
- Contract suite: **412 passed**, 101.46 seconds.
- Broad unit run: **793 passed** before deliberately interrupting at 374.44 seconds to focus review verification on the cross-system fault suite. This is a partial run, not a fresh full `make check` pass; no unit test failed before interruption.
- Boundary reproductions: **PASS as defect reproductions**, exit 0; these are additional review evidence, not acceptance of the current behavior.
- Cross-system validation suite: **44 passed**, 147.16 seconds; this includes the composed mock pilot used by the fault-validation fixtures. Existing acceptance tests passing does not close the additional findings above.

The initial sandboxed attempt could not open local sockets; its PostgreSQL setup errors were environmental, not application-test failures. The rerun uses isolated temporary services and keeps the offline guard active. The full unit suite and the integration tests outside `tests/integration/validation` were not completed in this review; historical acceptance receipts are not substituted for fresh results.
