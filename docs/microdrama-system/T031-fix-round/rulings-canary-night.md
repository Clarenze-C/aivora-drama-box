# Rulings — Codex review of `13da3e2...0851374` (canary-night commits)

Review: [codex-review-canary-night.md](codex-review-canary-night.md), 9 Nov 2026, verdict
FIX-REQUIRED. Orchestrator (Opus) re-read every BLOCKING claim at the cited lines before
ruling.

| ID | Codex | Ruling | Verified in code |
|----|-------|--------|------------------|
| CN-1 | BLOCKING | **BLOCKING, accept.** The cost leak is sub-µUSD per bucket, but independent half-up rounding of total and components manufactures DISPUTED buckets that block invoice finalization. That will bite on a 24-sample run. House rule is conservative: never under-record. | `runpod_transport.py:596-605` `_amount_micro` = per-field `ROUND_HALF_UP`; `_billing_record` rounds the four fields independently. |
| CN-2 | BLOCKING | **BLOCKING, accept.** Duplicate paid pod. | `create_pod` calls `_verify_existing_match` (a GET) after a successful POST. A 502 there raises `TransientProviderError` out of `acquire_or_reconcile` before `leases.py:917 _record_pod_id`. The canary retry loop (`canary.py:959`) re-enters `ensure_pod`. `_record_create_request` (`leases.py:940`) returns the old timestamp and does not block a second create, so if `reconcile_by_token` misses on list lag, `pods.py:176` POSTs again. |
| CN-3 | BLOCKING | **BLOCKING, accept.** Unredacted provider bodies and `URLError` text reach exceptions, the persisted run record and stderr. Secrets rule: nothing secret-shaped may be persisted or printed. | `runpod_transport.py:249-254` and `comfy_transport.py:73-90`: `[:500]` slice, no redaction; ComfyUI reads the whole body first. |
| CN-4 | SHOULD-FIX | **Accept, fix in the same round.** Storage ownership must open with the durable pod binding, or a failed startup needs manual accounting recovery. | Not re-verified (SHOULD-FIX). |
| CN-5 | SHOULD-FIX | **Accept, fix in the same round.** The ComfyUI port is public and unauthenticated. This applies to both the canary image and the new `deployment/pika-h3-flex` image. | Not re-verified (SHOULD-FIX). |
| CN-6 | SHOULD-FIX | **Accept, fix in the same round.** Check the deadline immediately before every attempt, and bound request timeouts by the time remaining. | `canary.py:959-970`: deadline checked only after a failure, then sleep and retry. |

Codex's "sound" conclusions (price ceiling, invoice window `9b133f1`, prompt uncertainty)
stand. Fixes go on `feat/t031-pika-flex-native` after fix round 1, as
[fix2-brief.md](fix2-brief.md). Re-review is round 2 of 2, scoped to the fix commits.

## Round 2 — [codex-rereview-fix2.md](codex-rereview-fix2.md), 10 Nov 2026: FIX-REQUIRED

CN-2 and CN-5 CLOSED. CN-1, CN-3, CN-4 and CN-6 PARTIAL, with four new findings. The
orchestrator re-read both BLOCKING claims at the cited lines.

| ID | Codex | Ruling | Verified in code |
|----|-------|--------|------------------|
| CN2-1 | BLOCKING | **BLOCKING, accept.** Small fix: let the residual top-up loop until the total is met, or allocate the whole residual deterministically. | `runpod_transport.py:670` region: total `ROUND_CEILING`, components `ROUND_FLOOR` plus a single-pass top-up. Ceiling-minus-floors can reach 4 within the 1e-12 tolerance, but there are only 3 components, so the `AssertionError` aborts billing ingest. |
| CN2-2 | BLOCKING | **BLOCKING, accept.** Small fix: add every resolved credential in the request, including the Comfy token, to the redaction context. | `runpod_transport.py:381`: `payload["env"] = {"MICRODRAMA_COMFY_TOKEN": token}`. The rejection-body sanitiser knows only the Runpod header credentials. |
| CN2-3 | SHOULD-FIX | Accept: open storage ownership in the POST-accept recorder, and heal it in the janitor's bound-pod path. | Not re-verified. |
| CN2-4 | SHOULD-FIX | Accept: refuse expired dispatch at the transport boundary, and cap the timeout at the positive remainder (no 1 s floor). | `diagnostics.py:110-122`: `max(floor_seconds=1.0, …)` confirmed. |

The two-round cap is reached. A third round needs the operator's approval.

**Operator, 10 Nov 2026: round 3 APPROVED, bundled.** One GLM fix round (fix3) covers
CN2-1..CN2-4 plus the accepted findings from the GLM harness review. Then one full gate,
then a Codex re-review (round 3) of the fix3 commits. Fix3 starts after the harness
review lands.

## Round 3 (final, operator-approved) — [codex-rereview-r3.md](codex-rereview-r3.md), 10 Nov 2026: FIX-REQUIRED

**CLOSED:** CN2-1, CN2-2, CN2-3, CN2-4, H-1. **H-2 PARTIAL**: the reconciler foundations
are right (positive-match adoption, no blind prompt resubmit), but there are three
BLOCKING defects in its recovery paths. The orchestrator re-read each one at the cited
lines.

| ID | Codex | Ruling | Verified in code (`628fe5b`) |
|----|-------|--------|------------------------------|
| CN3-1 | BLOCKING | Accept. | `benchmark_service.py:713`: `world.comfy.reconcile_unknown(...)` runs on a freshly composed, unbound client. Codex reproduced "endpoint is not bound" with the real factory. The ambiguity handler sweeps (terminates the pod) before recovery can read history. |
| CN3-2 | BLOCKING | Accept. | `execute()` (`:186-189`) unconditionally writes SCREEN/FULL_RUNNING before `_advance`, so the `NEEDS_RECONCILIATION` gate at `:291` is unreachable via `resume()` (`:472-490`). |
| CN3-3 | BLOCKING | Accept. **This is worse than having no resolver:** it can release protection for a pod that exists. | `resolve_create`: the pod-attached check (lease `FOR UPDATE`), `resolve_podless_create` and the final acquisition/storage release run in three separate transactions. The last one never re-checks `lease.pod_id`. |
| CN3-4 | SHOULD-FIX | Accept. | Not re-verified. |
| CN3-5 | SHOULD-FIX | Accept. | Not re-verified. |

Codex also flagged H-2 test quality: tests call `_advance()` directly, fake ComfyUI
state survives cleanup, and the cleanup fixture drops two unconditional assertions and
accepts stop where production requires termination. These must be corrected with the
fix.

The operator-approved third round is exhausted. The next step is the operator's
decision.

**Luna WIP `82135d4` (H-3..H-9), orchestrator probe, 10 Nov:** ran the DB-backed probes the Luna
sandbox could not, under CPUQuota=45%, OFFLINE_MOCK: `tests/unit/pipeline/` (including
`test_benchmark_world_composition.py`), `test_pika_h3_flex.py`, `test_runpod_transport.py`,
`test_t045_billing_ingestion.py` and `test_t045_storage_ownership.py`. Result: **215 passed** in
87 s. This is green evidence only. Red baselines are still missing, and a GLM review of the Luna
commit is still required.

**H-2 build, orchestrator verification at `2ec18f8` (P1 + P2 + P3 part 1), 10 Nov 13:15Z.** Run in a
separate detached checkout `.scratch/t031-verify-h2b`, under CPUQuota=45% with OFFLINE_MOCK. Files:
`test_t031_h2b_p1_modes.py`, `test_t031_h2b_p2_gate.py`, `test_t031_h2b_p3_ambiguity.py`,
`test_benchmark_experiments.py`, all of `tests/unit/pipeline/` and `test_comfy_recover.py`.
Result: **151 passed** in 219 s; `ruff check src tests` clean. This confirms the builder's green claims. It is not
acceptance: the remaining packages, the full gate and the Codex build review are still outstanding.

## H-2 build review, P1–P3 (round 1) — [codex-review-h2-p1p3.md](codex-review-h2-p1p3.md), 10 Nov: FIX-REQUIRED

13 BLOCKING (HB-1..HB-13) and 1 SHOULD-FIX (HB-14). **All 14 are accepted.** The orchestrator re-read
HB-1, HB-2, HB-7 and HB-8 at the cited lines:

- **HB-2:** confirmed. `benchmark_service.py:1687` binds only `if operation["state"] != "UNKNOWN"`.
- **HB-8:** confirmed. At `:723` the transaction locks D `FOR UPDATE` and then updates A, while the fence
  locks E → A → D, which is a cycle.
- **HB-1:** confirmed. The EXPIRED branch at `comfy_jobs.py:1143` builds its own receipt before consulting
  `lease_covered`.
- **HB-7:** consistent. `_assert_coordination` compares token values only.

The rest are probe-backed by Codex and consistent with v3.

Codex also graded the builder's judgement calls. The orchestrator adopts those gradings:

- P1-1: `recovery_started_at` must be set once.
- P1-3 and P1-4 are rejected (see HB-3).
- P1-6 is rejected (see HB-11).
- P2-4 is rejected (see HB-7).
- P2-8 is insufficient (see HB-13).
- P3-1: classify by the actual canonical effect, never invent create ambiguity.
- P3a-5 is rejected: termination plus canonical billing finality is required.

**Sequencing:** the builder finishes the in-progress P4 to a clean commit. Then package **HBF** fixes
HB-1..HB-14 tests-first, using shared P4 lock helpers where they apply. Then P5. The done marker requires HBF.
Codex re-reviews the HBF commits as round 2 of 2 for P1–P3.

## GLM review of Luna `82135d4` (H-3..H-9) — [glm-review-luna-REPORT.md](glm-review-luna-REPORT.md), 10 Nov: FIX-REQUIRED

H-3, H-4, H-6, H-7, H-8 and H-9 are **CLOSED**, with red at `628fe5b` confirmed by the reviewer. H-5 is **PARTIAL**.
Orchestrator rulings:

- **L-1 and L-2 are raised to BLOCKING** for the paid run. A shot-scoped costume map (S08 in the benchmark plan)
  passes the validator, then fails bind with SchemaInvalid **after pod acquisition**, which is paid waste.
  - L-1: the binder's ordinal rule must accept the shot-scoped maps that the validator accepts.
  - L-2: the upload lookup must key on the full slot identity, not `(role, subject_id)`.
  - Both need a test that actually stages and binds a costume-change seal.
- **L-3: accept.** The preflight-policy test must fail at `628fe5b`; the composed seal must be valid so that the
  policy check is what decides.
- **L-4 (preflight omits `public_actions_enabled` and budget headroom): accept.**
- **L-5: accept as docs.** Add an operator note that pre-existing LIVE seals need re-issue with the attestation-source field.
- **L-6: accept.** Restore a "preset never widens production eligibility" regression test.
- **L-7: accept.** Exercise the §G evidence write path against real PostgreSQL.

These go to the builder as package **LF**, after HBF and before P5.
