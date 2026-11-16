# T031 canary close-out and review coverage — 6 November 2026

## Scope of this inspection

Read-only inspection of Git history, repository review documents, the saved run-14
JSON, console billing evidence, prior full-check log and T031 narrative. No live
RunPod account or database was queried, no sweep/invoice was replayed, and no paid
effects occurred. Historical observations below are not a fresh fleet check.

## Reconciled status

- Checkout HEAD at inspection: `085137415862a309f30df949224e6ed5431e86e4`, branch
  `feat/microdrama-m0-m4`. HEAD is 24 commits ahead of the **locally recorded**
  upstream ref, zero behind. No fetch or push was performed.
- Pre-existing untracked paths: `.scratch/` and
  `microdrama/evidence/provider-qualification/`. Preserve them. In particular,
  qualification JSONs are present locally but are not tracked by Git; a code push
  alone would not preserve those evidence files.
- Run 14 `T031-canary-20261105-run14`: COMPLETE, two successful submissions,
  `/object_info` MATCH, durable output byte counts/hashes recorded, deadline not
  hit, termination verification recorded. Outputs came from canary stub nodes and
  `fake-quality-8step`; this proves no actual H3 quality or Thai speech.
- The completion JSON was written while billing was pending. Do not rewrite it
  to say BILLED. The later T031 narrative and commit `0851374` record console
  invoice MATCHED and final sweep BILLED at 2026-11-05 15:45 UTC.
- Console evidence for pod `xykul8kobl1e6s`, 05:00–06:00 UTC: total **35,753
  micro-USD**, comprising GPU **35,174** + disk **579** (CPU zero, rounding to the
  integer atom). The recorded lease settlement is **35,174 micro-USD**. Keep disk
  allocation visible; the lease figure is not the full pod expense.
- The ~$0.9 total for all night attempts remains an approximate narrative amount.
  Do not call run 14's invoice the entire night's final cost.
- Latest preserved full-check transcript `.scratch/makecheck-final3.log` ends
  `make check: all offline checks passed`, `EXIT=0`: **2,781 unit / 462 contract /
  270 integration**, lint/format passed. This is an inspected prior receipt, not a
  new test run. The later `9b133f1` invoice-window change has a focused test in its
  diff, but this inspection found no later full-suite receipt; do not claim that
  the earlier full run certifies that later code change.
- Last documented `make pilot` remains the 4 November T045 acceptance receipt:
  two HUMAN gates, 16 exports, 303,000 synthetic micro-USD. No newer real-episode
  acceptance is implied. The reported order-sensitive repair-media-chain test
  remains a follow-up; it was not investigated here.

Raw evidence and hashes are indexed in
[canary-evidence-index.json](t031-benchmark/canary-evidence-index.json). The index
records local file hashes and extracted facts; it does not independently prove
database state or substitute for durable backup of the original evidence/media.

## Independent review coverage

**6 November update:** the subsequent [scoped review](T031-canary-night-review.md)
now covers the canary-night delta and reports FIX REQUIRED (R1/R2), with 150 focused
tests passing. The earlier inventory below records what was known before that
review; it is superseded by the new report, not an ACCEPT for the later code.

The last located independent acceptance is
[T045 round 3](T045-fix-round/rereview-t045fix7.md), scope
`e56c952...1ce71cb`, 4 November. Its ruling is valid for that scope.

The canary-night delta `13da3e2..0851374` is later. Repository review documents and
Git history inspected here contain no independent acceptance receipt for it.
This is a coverage gap, **not** a new vulnerability finding or a rejection of the
prior acceptance. No runtime diff review was performed in this preparation task.

Review the following groups together, retaining the existing test assertions:

| Changes | Main invariant to review |
|---|---|
| `3e16485` CLI pool lifecycle, port declaration, canary image/seed | Actual CLI opens its pool; smoke seam cannot hide production bootstrap defects; stub image never qualifies a real model |
| `092c0f7`, `ecd6b78`, `c703f7b` error diagnostics | Bounded, useful errors without credential/header disclosure; ambiguous submission remains unknown |
| `91d12ac`, `014bca8`, `ce23b83` GPU/price behavior | Stable actual GPU ID; runtime price ≤ reserved quoted ceiling; no under-reservation |
| `9ff7fe9`, `0c79363`, `3866faa`, `27a8bc2` startup/endpoint/transport | Warmup retries bounded by deadline; endpoint belongs to owned pod; retries do not duplicate paid work |
| `989bf12` early pod-ID durability | Persist provider ID before verify/activate can fail; create-to-persistence crash still reconciles; cleanup never targets foreign pods |
| `af09523`, `a1f8456` media kind / example controls | Valid video media fetched from legacy UI key; unsupported controls refuse rather than disappear |
| `c65089a`, `9b133f1` billing atoms / provider window | Rounding conserves components and adjustments; resolved invoice window does not broaden coverage to unrelated accounts/pods/periods |

Relevant paths are the changed files under `microdrama/src/microdrama/{pipeline,
rendering,budget,persistence}`, their matching tests, `microdrama/tools/canary_db.py`
and `microdrama/deployment/canary-image/`. Full list:
`git diff --name-only 13da3e2..0851374`.

Next reviewer should record base/head, scoped findings, tests actually executed
and limitations in a new receipt. Do not reopen the closed T045 review cycle or
claim this coverage inventory is an independent ACCEPT. No self-review is
permitted for any code authored by that reviewer in another session.

## Next action

Prepare the real **Pika H3 Flex native-audio** route using
[T031-benchmark-packet.md](T031-benchmark-packet.md). The remaining work is model
fit/graph integration, rights/reference evidence, review of the later delta and
an accepted budgeted dispatch path for the 24-sample experiment. Re-running the
completed stub canary or billing commands is not the next prerequisite.
