# Drama Box microdrama handoff — updated 1 November 2026 UTC (post T044b2 review fix round)

Read `/root/.claude/CLAUDE.md`, this file, [SPEC.md](SPEC.md),
[task_breakdown.md](task_breakdown.md) and [task_status.csv](task_status.csv)
before work. This handoff records the current checkout; chat history is not a
deployment receipt.

## Checkout and safety

- Repo: `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`. The previously
  uncommitted T036–T045 stack (including the T044b2 intake and its review fix
  round) was committed on 2026-11-01 in two layers — code
  (`src/tests/contracts/migrations`) then docs/evidence/kit — after a full green
  gate; see the ledger's T044 row for the receipts. A pre-fix snapshot of the
  whole dirty tree exists at `/root/drama-box-dirty-snapshot-20261101.tar.gz`.
- Current contract package: **2.15.0** (V2 payload schema version 2.0; V1
  payloads remain readable). Migrations 0019–0024 are present. Contract source
  and generated artifacts are guardian-owned.
- No real Runpod Pod, paid model request, platform post, account test or public
  action was performed. OFFLINE_MOCK remains the default. T031–T035 are not
  qualified by local tests.
- No build worker is running. The interrupted T044b2 build was inspected,
  independently reviewed (Codex xhigh scoped to the delta:
  `docs/microdrama-system/T044b2-codex-review.md`), and all five BLOCKING plus
  one NON-BLOCKING findings were fixed in-session with pinning tests
  ([T044b2 evidence](../../microdrama/evidence/T044b2.md) fix-round section;
  re-review verdict in [T044b2-review-fixes.md](T044b2-review-fixes.md)).
  Caveat: the re-review shares a model family with the build; findings 1 and 3
  are cheap to spot-check in Codex after its weekly quota resets.

## Accepted software and last broad receipt

- Historical T001–T030 remain accepted. T036, T038, T039, T040, T041, T042, T043 and T048
  are `DONE`; evidence files are under `microdrama/evidence/` and linked in the
  ledger. T037 remains `REVIEW` until T044 invokes its owner-supplied metadata
  preparation before the existing Gate 2; T047 must test the composed release
  path. T044 and T045 remain `REVIEW`/unfinished. T046, T047 and live
  T031–T035 have not started.
- The **last full green** receipt (2026-11-01, after the T044b2 review fix
  round, under CPUQuota45%): `make check` **all offline checks passed** —
  **2,595 unit, 462 contract and 208 integration** tests; Ruff lint and format
  passed; `git diff --check` clean. `make pilot` exit 0: W01–W12, exactly two
  human gates, 16 local exports, 303,000 **synthetic** micro-USD. Focused
  intake receipts re-verified independently in the same session: 19/19
  (12 unit intake UI, 7 composed script_maker integration) and 570 unit +
  462 contract scoped regression. A pre-fix full-check baseline was cut at unit
  31% deliberately (mixed-tree receipts are worthless; the pre-fix tree is in
  the snapshot tarball).

## T041 — offline software gate complete

T041a's `story/directing.py` and DirectingManifest contract are in place;
independent review closed state and wardrobe findings, and the full story unit
suite passed **71** under CPUQuota45% before T041b's latest changes.

T041b implementation is in `references/v2_binding.py`,
`rendering/v2_preflight.py`, `rendering/workflows/v2_binding.py`,
`rendering/routing.py` and `rendering/comfy_jobs.py`, with scoped tests. It
resolves typed identity/outfit/prop/location/style/frame roles, checks current
assets/rights and unsupported controls before reserve, builds named workflow
ports, and adds `submit_v2` without the V1 positional binder. The guardian
added paired `RenderRequest.prompt_manifest_id/hash` and
`semantic_workflow_sha256` in contract 2.15.0. The independent reviewer found
that the semantic mapping hash was not durably pinned; the worker added the pin
and a mapping-change replay test. Current focused tests passed **36** with
isolated PostgreSQL; scoped review found the pin is checked before dispatch and
an existing operation replays without a second submission. The full check and
pilot passed as recorded above. T047 must implement
`verify_current_asset(id, version, sha)` against the current ACCEPTED asset row
and stored bytes, supply authoritative current rights resolution, and pass the
selected pinned template's semantic hash. No V2 paid dispatch is qualified yet.

## T042 — offline keyframe and actual-media QA complete

T042a checks verified, role-labeled still-frame bytes before render reservation.
It records durable evidence keyed by source, shot, evaluator and the selected
workflow's semantic mapping; first-frame entry and last/handoff exit state are
compared separately. Unsupported controls, unknown observation, stale bytes and
known mismatches block before a budget hold. Concurrent replay writes one
evidence event. T042b observes exported media before comparison, emits separate
timecoded continuity findings and per-check coverage, and reports fixture-only
TP/FP/TN/FN and shot-class applicability. Forged media/evaluator results,
foreign-episode expectations and unqualified paid-mode observers fail closed.

The production typed-expectations reader is **not wired**; T047 must compose it
from current V2 records and actual edit windows. The canonical `CoverageWindow`
has only a family, so T042b persists bounded QA-local per-check coverage and
records a contracts-guardian proposal in [T042 evidence](../../microdrama/evidence/T042.md).
Real model calibration and any live release-gating use remain T031 work. The
current pilot reports `GREEN_WITH_UNKNOWNS` at W07; it is not real quality evidence.

## T044 — owner scope and progress built; intake and Gate 2 flow pending

T044a added migration 0024's explicit season-owner relation, owner-scoped
review/media reads, and a read-only persisted-source progress projection. The
current `/ui` timeline and JSON reads separate production and release, show
counts/jobs/blockers/costs, and keep unknown work indeterminate. The scoped
review fixes closed episode-only Comfy output media access, inconsistent
season/episode asset scope, changed outfit-plan fingerprints and an unversioned
generated-contract edit. See [T044a evidence](../../microdrama/evidence/T044a.md)
and the [contract proposal](T044a-contract-proposal.md). Focused review,
contract and migration tests passed; the full make check/pilot receipt for the
whole T044 stack (including b2 and its fix round) is the 2026-11-01 green run
recorded above. T044 is `DONE`.

**Next T044 action:** finish and review the partial three-step owner Script Maker
intake. The Gate 2 metadata preparation form/API already invokes
`ReviewService.prepare_release_approval_manifest` before Approve & schedule.
T037 remains `REVIEW` until the composed release path is checked with the
finished intake/workbench in T047. New intake must call `link_season_creator`
in its creation transaction; unassigned legacy seasons remain hidden. T047
then wires the production continuity expectations reader and tests the full
V2 journey.

**1 November update (final):** T044b1 (Gate 2 metadata form/API) passed focused
review plus a composed fixture. T044b2 (three-step intake + workbench) was
finished, reviewed by Codex, and all findings fixed in-session with pinning
tests; the full `make check`/`make pilot` gate is green post-fix (receipts
above). T044 is `DONE`. T047 remains the independent composed acceptance gate,
and the optional Codex spot-check of fix findings 1 and 3 is recorded in the
ledger caveat.

## T045 — adapter, billing and bootstrap

- `rendering/runpod_transport.py` and `comfy_transport.py` implement fixture-
  tested REST/HTTP transports. Runpod create ambiguity searches only owned
  names and never blindly retries; shutdown checks ownership/readback. Comfy
  now checks effect, scoped reservation/operation authorization and credentials
  before every live HTTP request. Independent re-review closed the original
  pre-effect `/object_info` finding. Earlier adapter fixtures passed 41 tests;
  the later Comfy authorization change passed 6 transport and 11 DB-backed
  submit tests. No provider endpoint was called.
- `pipeline/live_world.py` checks current rights/preset evidence, workflow
  controls, image digest and a bounded operator quote, then **fails closed
  before provider construction** because billing/lease/janitor accounting is
  not yet safe. Its 5 scoped tests and Ruff passed. Missing exact durable
  Comfy node-schema/output-control evidence and stable quote/volume exposure
  are documented in [T045-live-provider-runbook.md](T045-live-provider-runbook.md).
- Billing contracts are in `contracts/cost.py` (package 2.15.0), not `v2.py`.
  Migrations `0022_runpod_billing_reconciliation.sql` and
  `0023_runpod_budget_reconciliation.sql`, `budget/billing.py` and
  `budget/service.py` contain in-progress durable bucket/revision/allocation
  and budget posting work. The billing worker's focused PostgreSQL suite
  passed **22** before this session. `BillingRepository.verify_invoice()` now
  persists MISMATCHED evidence without finalizing budget accruals; a DB-backed
  regression test passes. The eight new billing tables now have the required
  truncate and integer-number guards. The billing/lease focused suite passed
  **34**, and the full check passed. Matched finality still lacks a separate
  BILLED receipt/full-lease hold-release proof; holds
  remain conservatively reserved. Recovery allocations block new Runpod
  reservations until explicitly resolved. See
  [T045-billing-integration-spec.md](T045-billing-integration-spec.md).

**Next T045 action:** complete and independently review full-lease invoice finality/hold
release, make invoice verification replay idempotent, and connect
BillingRepository to `live_world`/janitor without a boolean
override. Until that is accepted, T045 stays `REVIEW` and T031 cannot launch a
qualifying real canary. The current official Runpod billing endpoint returns
time buckets, not per-second lease receipts; do not relabel estimates or empty
responses as billed cost.

## Dispatch order after these fixes

1. T041 is accepted for offline software; keep T047 composed and T031 real
   provider gates separate.
2. T042 keyframe/actual-media continuity QA and T043 poster/preview are
   accepted as offline software, with real quality still T031 evidence.
3. Finish T044 owner workbench and persisted progress; invoke T037's
   `ReviewService.prepare_release_approval_manifest` from the same Gate 2
   flow. Close T037 only after the composed live-like fixture path; no extra
   human approval type.
4. Run independent T047 V2 composed/fault acceptance, then T046 private
   staging/owner-scope/backup drills. DNS/TLS for `dramabox.aivora.agency` is a
   separate deployment action.
5. Finish T045 accounting/bootstrap and obtain explicit rights, credentials,
   current quote, time/storage/spend cap and operator authorization for T031's
   bounded real canary. T032 controlled real account tests, T033 first actual
   episode, T034 ten consecutive episodes plus seven-day management windows,
   and T035 final handoff remain separate live qualification gates.

Do not treat a local mock, schema, adapter fixture or manual Pod sample as
real provider, publishing, domain or ten-episode qualification.
