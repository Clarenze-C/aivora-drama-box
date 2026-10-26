# Build-review remediation record — 26 October 2026

Remediation cycle for [build-review-2026-10-25.md](../../docs/microdrama-system/build-review-2026-10-25.md).
Every finding's fix, its durable seam, and the tests that pin it. The review's
boundary probes now assert fixed behavior
([build-review-2026-10-25-probes.py](build-review-2026-10-25-probes.py)).

## What landed

| Finding | Fix | Pinned by |
|---|---|---|
| F02 P1 | `qa.plan_repairs` consumes the nested `RepairPlanOutcome` (`outcome.plan.plan_id`), routes `human_feedback` jobs to `plan_from_feedback(episode_id, approval_event_id)` with the Gate 2 approval as the job's causation id, and turns `NoRepairableInput` into an explicit no-work `Succeeded` | `tests/unit/pipeline/test_repair_handler.py` |
| F03 P1 | Caption repairs regenerate real outputs before anything resolves or reopens: a `CaptionRebuildPort` (editing-backed in the composed world, refusing default unwired) exports each repaired track's SRT asset (`caption_tracks.asset_id`) and re-burns the burned master + burned variant derivatives (stale burns superseded; deterministic content-addressed ids). Shot repairs dispatch through the router-backed `RouterShotDispatch` (real reservation, ordinary `render.shot` attempt). Line repairs no longer replay over invalidated audio (`_line_asset_exists` requires a usable asset state; the filled-script replay gate checks line audio too; identical re-registration promotes a superseded asset back). Asynchronous plans resolve NO findings at dispatch — `resolve_repaired_findings` resolves them only when a fresh QA cycle passes the covered check, called by the `qa.compare` handler. Cue clamping uses the master's timeline, not the newest video asset | `tests/unit/qa/test_repairs_rebuild.py`, `tests/unit/qa/test_repairs_execute.py`, `tests/integration/pipeline/test_repair_media_chain.py` |
| F04 P1 | `PostgresSharedRateLimiter` (migration 0018) keeps buckets in `rate_limit_buckets` under a row lock — one allowance per provider account across processes and restarts; the composed world registers it, and `WorkerDeployment` refuses to build when a limiter is configured without bindings for `PROVIDER_BOUND_TYPES` (callable resolvers compose `provider:account` keys from durable state). Rate deferrals call `JobService.defer`, which restores the claim's attempt — quota waits can never exhaust a healthy job's transport-attempt allowance | `tests/unit/workers/test_workers_shared_quota.py`, `test_workers_rate_gate.py` |
| F05 P1 | `pipeline/deployments.py`: one lane-scoped deployment each for production/publication/community (janitors stay independent scheduler actions); blocked-lane isolation proven within the declared bound | `tests/unit/workers/test_workers_shared_quota.py::TestLaneIsolation` |
| F06 P1 | Story write-claims book unallocated settled season research into the open episode accounts BEFORE the fit check and any paid dispatch (basis persisted in `cost_allocations`); analytics reports attributed research inside variable cost and only the unattributed residue as fixed, so totals reconcile exactly with no double count | `tests/unit/story/test_story_research_attribution.py`, `tests/unit/analytics/test_analytics_cost.py::TestResearchAttribution` |
| F07 P1 | Production qualification decides from independently collected evidence: bound approval, all required slots verified, no open blocking findings, attributed spend inside the cap (recorded overrun or late billing above cap resets the streak on reevaluation). Management windows qualify only with durable in-window evidence the work ran (executed actions, ingested events, completed community jobs — the initial metadata version is publication, not management) | `tests/unit/analytics/test_analytics_qualification.py::TestCostCapInVerdicts` |
| F08 P2 | `_account_spend` no longer adds `overrun_micro_usd` on top of committed spend (it is the above-cap subset, reported separately); per-minute cost uses `total * 60_000 // published_minutes_ms` with floor as the single explicit rounding rule — partial minutes are real minutes | `tests/unit/analytics/test_analytics_cost.py` (service-created overrun reconciliation) |
| F09 P2 | The sealed package's QA summary derives unknown coverage from evidence (UNSAMPLED/UNAVAILABLE/PARTIAL/UNKNOWN checks keep their ids; missing critical checks stay unknown, never assumed passes; superseded findings excluded); the runner labels `GREEN_WITH_UNKNOWNS` when coverage is incomplete | `tests/unit/pipeline/test_packaging_summary.py` |
| F01 P1 | The scheduler alone can drive the workflow: the cadence schedule creates the next approved episode; W05 claims the episode's owned pod lease, dispatches initial routed attempts and accepts verified outputs (operation discovery keyed to `render.shot` jobs, not a provider string); W06 proposes assembly only for a complete accepted shot set; W07 chains technical → observation → comparison → repairs → package from durable state; W09 submits due SCHEDULED slots through the shared `publication_command_for_post` builder (plan resolved by dedupe key, never by slot name — names repeat across platforms in one scope) with one submit proposal per slot in flight, polls SUBMITTED **and** PROCESSING posts (only those with an external id), and proposes `publish.reconcile_slot` for slots whose submit went ambiguous (op UNKNOWN/past deadline, single-flight per slot); a verified readback resolves the submit job its success parked in NEEDS_RECONCILIATION (the publication twin of W05's render reconcile); the deployment timer runs on the wall clock | `tests/integration/pipeline/test_scheduler_driven_path.py` (two human gates only; world rebuilt between stages at boundaries with no in-flight provider operation), `tests/unit/publishing/test_w09_discovery.py` |

## Known limits (unchanged by this cycle, tracked by the review's engineering table)

- The offline fake providers keep in-memory server state; a restart mid-render
  cannot resume an in-flight fake prompt (the scheduler-driven test restarts at
  boundaries with none in flight). Durable fake-state reconstruction is part of
  the runtime-bootstrap deliverable, not a scheduler regression.
- Lane deployments share one process in the offline composition; the isolation
  test stands processes apart via separate runtimes. A multi-process deployment
  definition (compose/units) is the operations deliverable.
- Management-window evidence exists only where the unattended path ran; the
  quiet-week heartbeat instrumentation stays future work.

## Verification (2026-10-26, quota-limited session)

Lane-by-lane fresh runs during remediation (each against isolated PostgreSQL,
offline guard active):

| Suite | Result |
|---|---|
| unit: workers + pipeline + qa-repairs | 45 + 8 + 13 passed |
| unit: scaffold + core | 428 passed |
| unit: budget + analytics | 237 passed |
| unit: review | 216 passed |
| unit: editing + references | 148 passed |
| unit: research + story | 93 passed |
| unit: memberships + registry | 381 passed |
| unit: rendering/publishing/community/api/testing | 1012 passed |
| contract | 412 passed (version 1.6.0 unchanged) |
| integration: composed repair chain (F03) | 2 passed |
| integration: scheduler-driven path (F01) | **1 passed (238.6 s)** — post-mortem prints stripped, settle-resolution and no-fire-error asserts added |
| unit: publishing W09 discovery pins (`test_w09_discovery.py`, added this cycle) | 4 passed; publishing unit lane + pipeline contract lane rerun green (267 passed) |
| `make check` (single full pass) | **passed** — contracts-check + lint + unit 2346 + contract 412 + integration 174 in one run (2026-10-26) |
| `tests/integration/validation` (AT suite) | 174 integration passed inside `make check`, including the full AT lane (44/44 baseline restored; AT-08's flood markers now run on fallback buckets) |
| Probes (`evidence/build-review-2026-10-25-probes.py`) | all FIXED lines, exit 0 |

### The F01 acceptance test's last three defects (found via timeline dumps, all fixed)

1. **Stacked submit proposals** (`scheduling/service.py`): a submit job still
   pending did not stop a later period from proposing a second one under a
   fresh period key; the stale sibling executed against the slot the first
   job had moved and died on Conflict. Discovery now keeps one submit
   proposal per slot in flight (W07's package-stage guard pattern), keyed by
   the slot identity fields serialized in the payload — the payload's slot
   has no `dedupe_key` (it is a computed hash, never serialized).
2. **Name-matched commands submitted other slots' posts**
   (`publishing/commands.py`): `publication_command_for_post` resolved the
   slot plan by `release_slot` name, which repeats across platforms inside
   one release scope; the command's dedupe key then locked a DIFFERENT post
   row (its submits "succeeded" as no-op replays or failed on that post's
   HELD/PROCESSING state while the intended slot never moved). Plans resolve
   by dedupe key now.
3. **Successful submits parked their jobs forever** (`pipeline/handlers.py`):
   a successful submit's provider operation stays in flight until the post
   verifies, so the job layer parks the job in NEEDS_RECONCILIATION at
   finish; nothing resolved it. The poll handler now resolves the linked
   submit job when its readback verifies — mirroring W05's render reconcile.

Also closed this cycle (known-missing from the previous session): W09
reconcile discovery — slots parked by an ambiguous submit (op UNKNOWN or past
deadline, including SUBMITTED slots with no external id) get their
`publish.reconcile_slot` proposal; the poll schedule never proposes a poll
for a slot without an external id.

### Fallout the first full `make check` caught (all fixed same day)

4. **The mock runner fed the builder name-only post rows**
   (`pipeline/runner.py`): `_command_for_post` received dicts selected without
   `dedupe_key` (and keyed its submit jobs by release_slot name, which
   collides across platforms) — the pilot fixture and `test_full_mock_path`
   died on `KeyError`/`IdempotencyConflict` once plans resolved by dedupe
   key. The runner now selects the key and keys submit jobs by post id.
5. **Strict F04 limiter bindings crashed whole lane cycles**
   (`pipeline/deployments.py`): a provider-bound job whose durable row was
   gone (deleted between enqueue and claim, or a synthetic validation marker
   — AT-08's flood tests use random ids by design) raised `LookupError` out
   of `run_cycle`. Bindings now bucket unresolvable entities by their own
   entity id — no account's quota is borrowed, the handler decides the job's
   fate, and a wiring bug (a field binding naming a missing payload field)
   still fails loudly as pinned. Pinned by
   `tests/unit/workers/test_workers_shared_quota.py::test_an_unresolved_entity_buckets_alone_instead_of_crashing_the_cycle`.

## Resume state (next session)

Nothing open on the remediation itself. Remaining work is the review's
"further engineering" table, out of remediation scope: durable fake-provider
state across restarts, real provider edges (T031), platform/membership
transports (T032), multi-process deployment definitions, management heartbeats
for quiet weeks, task_status.csv reconciliation. One design note for whoever
picks up W09 live work: a reconcile that proves the post absent re-arms the
SAME slot (`SUBMITTED`, op `PENDING_SUBMIT`, fresh deadline) — W09 submit
discovery only proposes for `SCHEDULED` rows, so a re-armed slot's resubmit
needs a command carrying its CURRENT metadata version
(`publication_command_for_post` builds the initial version id); unreachable
offline, but live adapters will hit it.
