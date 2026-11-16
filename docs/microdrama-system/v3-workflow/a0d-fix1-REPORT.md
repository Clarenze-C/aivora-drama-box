# A0-D FIX1: ALL FINDINGS ADDRESSED

# A0-D fix round 1 — the 13 Codex findings (AD-1..AD-13)

Build: GLM (A0-D fix1 brief, 13 Nov 2026). Base `ea1cc10`, worktree
`drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`. Requirement list:
`codex-review-a0d.md` (10 BLOCKING + 3 SHOULD-FIX). All 13 closed with
red→green evidence; nothing stopped at red; nothing merged or pushed.

Commits (on top of `ea1cc10`, tip `6974d5a`):
- `5e85d3d` — cluster 1: AD-1, AD-2, AD-8 (gateway + shim)
- `97471b3` — cluster 2: AD-3, AD-4, AD-5, AD-12, AD-13 (reconciler + jobs)
- `6974d5a` — cluster 3: AD-6, AD-7, AD-9, AD-10, AD-11 (step + gateway latch + adoption)

## Per-finding status

| ID | Status | Commit | Red line | Green line |
|----|--------|--------|----------|------------|
| AD-1 | **CLOSED** | `5e85d3d` | red run 2026-11-13: `tests/integration/llm_gateway/{test_gateway_ledger_safety,test_gateway_launch_argv,test_gateway_interface}` — **17 failed** (argv missing model/budget/deadline/prompt/schema; incomplete request accepted 202; shim enforced → UNKNOWN) | same files: **51 passed** (full gateway suite) |
| AD-2 | **CLOSED** | `5e85d3d` | (same run) `test_ad2_*`: absolute-path/traversal/non-canonical IDs accepted (202/200) | same suite green; `/etc` asserted green-only (deviation 2) |
| AD-3 | **CLOSED** | `97471b3` | `test_ad3_a_pending_submit_crash…` red: `SKIPPED_NO_EXTERNAL_ID`; `test_ad3_cancellation_forwards…` red: no event, no `cancel_requested_at_ms` | `tests/unit/llm`: **41 passed** (at that commit) |
| AD-4 | **CLOSED** | `97471b3` | `test_ad4_completed_work_at_max_attempts…` red: job left RUNNING for the janitor; `test_ad4_refusal_recovery…` red: deferral timing dropped (no RETRY_WAIT) | same |
| AD-5 | **CLOSED** | `97471b3` | `test_ad5_a_lease_lost_pass…` red: op settled despite the lost lease; `test_ad5_the_reconciler_survives_a_janitor_storm` red: janitor FAILED/LEASE_EXPIRED settled work | same + `test_llm_reconciler_race.py` (two real connections) |
| AD-6 | **CLOSED** | `6974d5a` | `test_ad6_red_health_still_settles…` red: `LLM_GATEWAY_UNHEALTHY` instead of settle+`LLM_BLOCKED`; `test_ad6_a_gateway_outage_defers…` red: job FAILED instead of RETRY_WAIT/GATEWAY_UNAVAILABLE | `tests/unit/llm`: **62 passed** |
| AD-7 | **CLOSED** | `6974d5a` | `test_ad7_the_latch_survives_a_restart…` red: restart cleared the latch + queued work launched; `test_ad7_requalification…` red: no route (404) | `tests/integration/llm_gateway`: **53 passed** |
| AD-8 | **CLOSED** | `5e85d3d` | `test_ad8_*` (6 tests) red: inspection failure treated as absence; timed-out systemd-run settled DONE/launched=false | same suite green (incl. the wrapper-fixture systemd-run timeout + failing-show integration tests) |
| AD-9 | **CLOSED** | `6974d5a` | `test_ad9_*` red: `{}` against required `line` → SUCCEEDED; tampered sha → SUCCEEDED; the shared validator module did not exist (ImportError) | 62 passed incl. the 13-case corpus cross-check (src vs gateway twin agree verdict-for-verdict) |
| AD-10 | **CLOSED** | `6974d5a` | `test_ad10_every_settled_attempt…` red: one attempt row (latest only), zero quota rows; `test_ad10_a_conflicting_attempt_replay…` red: silent DO NOTHING | same suite green: 3 attempt rows + 2 quota rows; Conflict raised |
| AD-11 | **CLOSED** | `6974d5a` | `test_ad11_a_completion_race…` red: adopt==0, op stuck SUBMITTED forever | op settles SUCCEEDED, job stays CANCELLED, content discarded |
| AD-12 | **CLOSED** | `97471b3` | `test_ad12_the_shipped_cli_entry_point_runs` red: `PoolClosed` before connecting | exit 0 on an empty database |
| AD-13 | **CLOSED** | `97471b3` | `test_ad13_pending_submit_with_gateway_unknown…` red: `SUBMITTED_WAIT` (the wrong row) | `UNKNOWN_OPERATOR`, op UNKNOWN, job left for the operator |

## What each fix does

- **AD-1** (`gateway.py`, shim): the launcher passes the complete frozen request
  through the real A0-R1 interface — positional prompt file + `--model`,
  `--max-budget-microusd`, `--deadline-s`, `--invocation-id`, `--attempt`,
  `--result-json`, `--schema-file` (only when the request has a schema);
  `prompt.txt`/`schema.json` are frozen at accept. `accept` refuses an incomplete
  request (400). Settlement binds the result's `policy_identity` to the frozen
  request's (mismatch → invalid result → UNKNOWN). The shim enforces exactly
  the real CLI's `strict_validate` (exit 2, NO result file — verified against
  `/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py`, read-only)
  and echoes `--model`/`request.policy_identity` in its result.
- **AD-2**: `canonical_invocation_id` before EVERY ledger lookup (accept and
  all URL paths, via `LlmGateway.ledger`), plus a realpath containment check in
  `Ledger.__init__` — `/etc`, `../x`, absolute, traversal and non-canonical
  UUID IDs are refused before any write.
- **AD-3**: reconciler candidates LEFT-JOIN `llm_invocations` and recover the
  invocation id through `operation_id`; `JobService.cancel` does the same, so a
  lost-POST-ack crash (op PENDING_SUBMIT, `external_id` NULL — the real
  condition, not a retained external id) is reconciled and cancelled.
- **AD-4**: settled recovery finishes under the reconciler's lease —
  DONE/NOT_FOUND → `WaitExternal` (the handler adopts/rearms on the next claim;
  no attempt burn; nothing for the janitor to LEASE_EXPIRED at max attempts);
  REFUSED → `Deferred(reason, clamp(retry_at − now, 60 s, 6 h))` with
  `defer_reason` kept; CANCELLED → `Failed("CANCELLED")`. RESUME records
  `consumed_attempt=false` so a reconciler deferral never refunds an attempt.
- **AD-5**: `JobService.finish_with_operation` settles the op (and mirrors
  records) and applies the job outcome in ONE transaction — job row locked and
  the lease re-verified BEFORE the operation lock; in-flight rules re-evaluated
  after the settlement. All reconciler mutations go through it; a lost lease
  raises Conflict with nothing written (`LEASE_LOST`, retried next pass).
  Two-connection reconciler/janitor race test on real PostgreSQL
  (`test_llm_reconciler_race.py`), plus the deterministic lease-loss test.
- **AD-6**: the §5.7 gate is an admission check in the submit path
  (`_gate_for_admission`); polling/settlement run regardless of health. A
  health probe that cannot be answered falls through to the POST, so the
  documented connect-level NOT_FOUND+deferral path works during outages; a
  red-but-reachable gateway still refuses new admissions.
- **AD-7**: a real ISOLATION_VIOLATION latches DURABLY
  (`store/isolation_latch.json`, qualification-bound policy identity);
  `recover()` restores it before serving (settled-DONE records are scanned as a
  fallback); `pump()` launches nothing while latched; `POST /v1/requalify`
  clears it only for the configured `--expected-policy-identity`. INSTALL.md
  documents the operator procedure.
- **AD-8**: `unit_active_state` raises `SystemdInspectionError` on any failed
  or timed-out inspection (never absence); supervise/recover skip the pass or
  mark the invocation unresolved (health red); cancel keeps CANCEL_REQUESTED
  when the unit cannot be proven not-active; a failed/timed-out systemd-run is
  reconciled by deterministic unit name (re-attach if live; authoritative
  absence settles ISOLATION_UNAVAILABLE launched=false; uninspectable stays
  LAUNCH_INTENT with the queue slot held). Seams: `--systemd-run-command`,
  `--systemctl-command`, `--systemd-run-timeout-s` (wrapper-fixture tests run
  real transient units through them).
- **AD-9**: `microdrama/llm/result_validation.validate_gateway_result`
  (envelope + integrity sha + identity binding + frozen-schema subset) is used
  by the step's `_done`, the reconciler's DONE branch and the cancellation
  adoption; the gateway's settlement reader (same rules, stdlib twin, landed
  with cluster 1) guards the gateway side — `{}` against a schema requiring
  `line` is INVALID_OUTPUT/UNKNOWN everywhere.
- **AD-10**: `mirror_invocation_result` persists EVERY settled gateway attempt
  (append-only), inserts the settled attempt's `quota_observations` row when
  the result carries readings, and raises Conflict on conflicting evidence
  replays (identical replays are no-ops). The step's REFUSED and CANCELLED rows
  mirror too.
- **AD-11**: `adopt_confirmed_cancels` reconciles every authoritative terminal
  answer: DONE → the op settles SUCCEEDED/FAILED per the validated outcome
  (metering mirrored, content output discarded); REFUSED → REFUSED_PRELAUNCH
  with launched=false; CANCELLED → as before; the job stays CANCELLED and no
  operation is left in flight.
- **AD-12**: the CLI entry point opens its pool through the Database context
  manager.
- **AD-13**: a gateway UNKNOWN answer takes precedence over every
  "existing record" row — PENDING_SUBMIT + UNKNOWN goes straight to operator
  reconciliation.

## Verification coverage (all green lines, 13 Nov 2026)

- `tests/unit/llm`: **62 passed** (all 13 AD tests + the pre-existing suites).
- `tests/integration/llm_gateway`: **53 passed** (real systemd, real transient
  `dramabox-llm-test-*` units, fake ai-route shim; no test units left loaded).
- Regression sweep after the jobs.py/step/reconciler changes:
  core+workers+pipeline+review+publishing+budget: **1406 passed**;
  analytics+references+rendering(jobs importers): **162 passed**.
- `make lint` (`ruff check` + `ruff format --check` over src/tests/tools):
  clean immediately before each commit.
- Not re-run by this build (no import-path overlap with the diff — none of
  these import `microdrama.llm`, the gateway deployment, or `core.jobs`):
  `tests/unit/{api,community,editing,qa,registry,research,scaffold,story,
  testing_harness}` and the non-routing remainder of `rendering`. The
  orchestrator's `make check` after review round 2 covers the rest.
- Two background attempts at the monolithic full-unit sweep hit the background
  time limit and were stopped (no partial output); the chunked + targeted runs
  above are the recorded coverage.

## Deviations (with reasons)

1. **AD-9 "one shared validation" is twin implementations + a corpus
   cross-check**, not one importable module: the gateway runs under the pinned
   system interpreter with no package imports (§4.1), so it cannot import
   `microdrama.*`. One rule set, two implementations bound by
   `test_llm_result_validation.py` (both must agree verdict-for-verdict on a
   13-case corpus).
2. **AD-2's `/etc` case was not run red** — the pre-fix gateway would really
   have written `/etc/request.json` on this host. The absolute-path escape
   class is proven red with a `tmp_path` absolute target; `/etc`, `../x` and
   non-canonical UUIDs are asserted in the committed (green) tests only.
3. **AD-6 re-reading of §5.7** ("checked at every dispatch"): per the review's
   explicit fix direction ("retain admission checks while allowing existing
   operations to be polled and settled"), the gate now runs wherever new
   external work would be created (the submit path, including rearm-resubmit)
   and at startup/composition; polling/settlement is the explicit recovery
   handling. `require_llm_route` itself is unchanged for composition checks.
4. **Existing tests updated to corrected contracts** (the review's findings
   invalidate the old expectations): gateway API tests send complete frozen
   requests (AD-1); three reconciler-suite rows no longer run the
   janitor-requeue dance (AD-4); fake-gateway fixtures REPLACE the readmit's
   attempt entry instead of duplicating it (AD-10's conflict detection
   correctly rejects two entries for one attempt number — the real gateway
   never produces that); the deactivating-stub lambda takes the new
   systemctl kwarg (AD-8 seam).
5. **AD-10 attempt-evidence hash** covers the gateway's attempt entry (the
   persisted columns: outcome, launched, refusal_reason, retry_at_ms,
   ended_at_ms), not the invocation-level result payload: the entry IS the
   per-attempt evidence, and a hash mixing in the latest result would
   false-conflict on a later settlement of another attempt. Conflicting
   replays of the entry raise Conflict (the committed test tampers the entry).
6. **Budget note on §4.2 semantics**: the gateway does not validate the model
   against the {sonnet, opus} allowlist at accept (models.json owns the
   allowlist; the CLI refuses at launch, and the shim enforces the fixture
   copy). Accept validates presence/type/bounds of every interface field.

## Anything stopped at red

Nothing. Every finding reached green.

## Resume here

Nothing to resume. All 13 findings are closed and committed (`6974d5a` tip,
3 commits on `ea1cc10`, nothing pushed). For the orchestrator: review round 2
against `ea1cc10..6974d5a`, then `make check` + `make pilot`.
