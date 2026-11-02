# Drama Box microdrama handoff — updated 2 November 2026 UTC

Read `/root/.claude/CLAUDE.md`, this file, [SPEC.md](SPEC.md),
[task_breakdown.md](task_breakdown.md) and [task_status.csv](task_status.csv)
before work. This handoff records the current checkout; chat history is not a
deployment receipt.

## Checkout and safety

- Repo: `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`. Everything
  through 2026-11-01 is committed and pushed (remote head `62a39ec`). The
  2026-11-02 review fix round (DB-1..DB-11) and its re-review-1 follow-up
  round (DBR-1..DBR-3 + DBR-6 drill re-run, code commit `95fef89`) are
  committed locally in layered code+docs commits on top and **not pushed** —
  Opus accepts first. A pre-review snapshot of the formerly dirty tree exists
  at `/root/drama-box-dirty-snapshot-20261101.tar.gz`.
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

The **last full green** receipt (2026-11-02, after the DBR-1..DBR-3 fix round
+ DBR-6 drill re-run, under CPUQuota45%): `make check` **all offline checks
passed** — **2,611 unit, 462 contract and 221 integration** tests; Ruff
(check + format) clean; `make pilot` exit 0 — W01–W12, exactly two human
gates, 16 local exports, 303,000 **synthetic** micro-USD.

**Independent reviews:** the pending Codex spot-checks for T044b2 (findings 1
and 3), T046 and T047 were replaced on 2026-11-02 by a stand-in cross-model
review (Claude Sonnet 5.5 read-only reviewer, Opus rulings —
[review](T044b2-T046-T047-claude-review-2026-11-02.md)). All 11 findings
(DB-1..DB-11) were accepted as BINDING and fixed the same day, tests-first
red→green, in commits `15b6cf5`, `03f3e92`, `64b1784`, `73747df`
(+`01379d7` format); evidence is appended to the T044b2/T046/T047 evidence
files and the ledger rows point there. **Re-review 1** (same file, section at
the end) then ACCEPTED that fix round: DB-1, DB-2, DB-4..DB-10 and the
T044b2 F2/F4/F5/F6 spot-check are CLOSED. Its three follow-ups — DBR-1
(create-owner reserved its password file after the owner row committed),
DBR-2 (the reader's overlap check rejected every contract-valid crossfade
EDL), DBR-3 (unbounded `advisory_lock` wait) — are fixed tests-first
red→green in commit `95fef89`, and the required DBR-6 drill re-run after
DB-10 passed 7/7 (loopback compose on 8093, stack left DOWN). What remains
is ONE scoped re-review of DBR-1..DBR-3 only — the second and last
re-review round; after it, the operator decides whether to push.

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

1. **Review-after-fix**: ONE scoped re-review of DBR-1..DBR-3 only (commit
   `95fef89` + the DBR-6 drill evidence in `microdrama/evidence/T046.md`) —
   the second and last re-review round; after it the operator decides
   whether to push. After the 2026-11-04 Codex quota reset, or another
   cross-model reviewer sooner.
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
