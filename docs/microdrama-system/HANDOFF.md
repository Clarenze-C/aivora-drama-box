# Drama Box microdrama handoff — updated 2 November 2026 UTC

Read `/root/.claude/CLAUDE.md`, this file, [SPEC.md](SPEC.md),
[task_breakdown.md](task_breakdown.md) and [task_status.csv](task_status.csv)
before work. This handoff records the current checkout; chat history is not a
deployment receipt.

## Checkout and safety

- Repo: `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`, everything
  committed and pushed (remote head `62a39ec`, 2026-11-01). The whole
  T036–T048 stack landed on 2026-11-01 in layered code+docs commits, each
  behind a full green gate. A pre-review snapshot of the formerly dirty tree
  exists at `/root/drama-box-dirty-snapshot-20261101.tar.gz`.
- Current contract package: **2.15.0** (V2 payload schema version 2.0; V1
  payloads remain readable). Migrations 0019–0024 are present. Contract source
  and generated artifacts are guardian-owned.
- No real Runpod Pod, paid model request, platform post, account test or
  public action has been performed. OFFLINE_MOCK remains the only composed
  mode; the staging deployment refuses all others. T031–T035 are not
  qualified by local tests.
- No build worker is running.

## Board state

**M5V2 offline software is COMPLETE.** T001–T030 accepted; T036–T044, T046,
T047 and T048 `DONE` (evidence under `microdrama/evidence/`, receipts in the
ledger). T045 is the one open offline task (`REVIEW` — billing finality,
below). T031–T035 are the live qualification gates and have not started.

The **last full green** receipt (2026-11-01, after T046, under CPUQuota45%):
`make check` **all offline checks passed** — **2,599 unit, 462 contract and
214 integration** tests; Ruff clean; `make pilot` exit 0 — W01–W12, exactly
two human gates, 16 local exports, 303,000 **synthetic** micro-USD.

**Pending independent reviews (Codex weekly quota resets 2026-11-04):**
scoped reviews for T044b2's fix round (at minimum a spot-check of findings 1
selection-revision and 3 dispatch-blockers), T047 and T046. These were built
and reviewed in-session on the operator's direction; the same-model-family
caveat is recorded in each ledger row.

## What 1 November built (all gated, committed, pushed)

- **T044 owner workbench — DONE.** T044a season-owner scope (migration 0024)
  + progress projection; T044b1 Gate 2 owner-metadata form/API invoking
  `ReviewService.prepare_release_approval_manifest`; T044b2 the three-step
  Script Maker intake + workbench. Codex's scoped review found 5 BLOCKING
  issues (selection replay, cross-owner sheet leakage, silent source-lane
  skip, unverified display payloads, unverified scope-as-canon); all fixed
  with pinning tests ([T044b2 evidence](../../microdrama/evidence/T044b2.md),
  [review](T044b2-codex-review.md), [re-review](T044b2-review-fixes.md)).
- **T047 composed acceptance — DONE; T037 CLOSED.** The deferred production
  seams exist with fail-closed semantics and pinned tests
  ([T047 evidence](../../microdrama/evidence/T047.md)):
  `references/v2_dispatch_context.py` (`verify_current_asset` = ACCEPTED row
  + exact version/sha + stored-bytes hash; authoritative registry rights
  resolver; the record loader feeding `V2ReferencePreflightContext`) and
  `qa/continuity_sources.py` (typed expectations reader from current edit
  manifests + hash-verified V2 records). Six composed proofs, including the
  intake-born season reaching the Gate 2 manifest → scheduled posts with no
  transport (T037's closure evidence). The pilot composition is deliberately
  unchanged; live V2 dispatch consumes the gates when T045 lands.
- **T046 private staging — DONE.** `api/serve.py` + `api/worker.py` durable
  entries (SystemClock + UuidIds; refuse non-OFFLINE_MOCK modes), digest-
  pinned Dockerfile + `deployment/compose.staging.yaml` (loopback-only,
  127.0.0.1:8093 — 8091 belongs to arisa-sfw-review). The seven-step drill is
  7/7 PASS ([T046 evidence](../../microdrama/evidence/T046.md)): owner
  login, three-step intake over HTTP, FULL restart including postgres with a
  surviving session and identical rows, worker+janitor drain, backup, and a
  scratch-project restore with login + season readback. The drill caught and
  fixed two real defects: registry seeding was not restart-idempotent
  (pinned by `tests/unit/api/test_serve_entries.py`), and deterministic
  `SequentialIds` made `create-owner` work exactly once per database.
  The staging stack is DOWN (volumes kept); bring it back with the compose
  command in the drill header. `dramabox.aivora.agency` DNS/TLS/exposure is
  operator-only runbook work (`deployment/staging/DOMAIN-RUNBOOK.md`) —
  deliberately not executed.

## T045 — the one open offline task (adapter/billing/bootstrap)

- `rendering/runpod_transport.py` / `comfy_transport.py`: fixture-tested
  transports; Runpod create ambiguity searches owned names and never blindly
  retries; Comfy checks effect/authorization/credentials before every live
  request. No provider endpoint has been called.
- `pipeline/live_world.py` **fails closed before provider construction**
  until billing/lease/janitor accounting is safe
  ([runbook](T045-live-provider-runbook.md)).
- Billing (contracts in `contracts/cost.py`; migrations 0022/0023;
  `budget/billing.py`): mismatch evidence persists without finalizing
  accruals; the eight billing tables carry schema guards; focused suites
  22 + 34 green. Open: full-lease BILLED finality/hold-release proof,
  idempotent invoice-verification replay, and connecting BillingRepository
  to `live_world`/janitor without a boolean override
  ([spec](T045-billing-integration-spec.md)). The official Runpod billing
  endpoint returns time buckets, not per-second lease receipts — never
  relabel estimates as billed cost.
- T047's asset/rights gates are the dispatch-boundary suppliers this task's
  live path consumes.

## What remains, in order

1. **Codex scoped reviews** after the 2026-11-04 quota reset (T044b2
   spot-check, T047, T046) — close or escalate each ledger caveat.
2. **T045 accounting acceptance** (offline work, no provider calls).
3. **T031 real-provider qualification** — needs T045 accepted PLUS explicit
   operator authorization: rights route, credentials, current quote,
   time/storage/spend caps. Do not launch a canary without it.
4. T032 controlled real account tests, T033 first actual episode, T034 ten
   episodes + seven-day management windows, T035 final handoff — separate
   live gates, unchanged.
5. Optional, operator-decided: the domain runbook for
   `dramabox.aivora.agency`.

Do not treat a local mock, schema, adapter fixture, staging drill or manual
Pod sample as real provider, publishing, domain or ten-episode qualification.
