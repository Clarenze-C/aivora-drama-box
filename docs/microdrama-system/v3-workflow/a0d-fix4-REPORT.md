# A0-D FIX4: ALL FINDINGS ADDRESSED

# A0-D fix round 4 — the four round-4 findings AD7-1..AD7-4

Build: GLM (A0-D fix4 brief, 14 Nov 2026). Base `a4e9913`, worktree
`drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`. Requirement list:
`codex-review-a0d-r4.md` (2 BLOCKING + 2 SHOULD-FIX). **All four fixed in the
brief's order (AD7-1 → AD7-2 → AD7-3 → AD7-4), each with a red test recorded
against the pre-fix code before the fix landed.** Nothing stopped at red;
nothing merged or pushed. `make lint` (ruff check + format --check) clean
immediately before every commit.

Commits (on top of `a4e9913`, tip `15ce674`):
- `0f48aaa` — AD7-1 (step.py DONE validation)
- `8a0c5ae` — AD7-2 (per-attempt complete result evidence + fake fidelity)
- `51a7337` — AD7-3 (receipt requires internal authorization)
- `15ce674` — AD7-4 (authorization binds to the frozen request)

## Per-finding status

| ID | Status | Commit | Red | Green |
|----|--------|--------|-----|-------|
| AD7-1 | **ADDRESSED** | `0f48aaa` | `test_ad7_1_an_identity_a_result_completes_under_b_configuration`: after the A-freeze and the A→B recomposition, the honest identity-A SUCCEEDED result settled the operation FAILED — `AssertionError: assert 'FAILED' == 'SUCCEEDED'` on `op_row.state` (INVALID_OUTPUT from the identity check) | `_done` validates against `frozen_policy_identity(self._db, invocation_id) or self._expected_policy_identity` — the same binding the reconciler and the cancellation adoption already use (AD6-4). The A→B test runs through successful completion: op SUCCEEDED, job SUCCEEDED, invocation row `policy_identity` = A with the structured output persisted. `test_ad6_1…` unchanged and green |
| AD7-2 | **ADDRESSED** | `8a0c5ae` | `test_ad7_2_a…[changed-cli-version / changed-identity / flipped-usage-unavailable]` and `…_b…[removes a field]`: after attempts 1 (REFUSED, quota) and 2 (SUCCEEDED, quota) settled, replaying the record with attempt 1's exposed payload doctored — the settling result byte-identical — raised NO Conflict: `Failed: DID NOT RAISE <class 'microdrama.contracts.errors.Conflict'>` (4 failed; the identical-replay control `_c` passed, as it must on both sides) | the append-only `llm_invocation_attempts.result_sha256` now hashes the attempt entry TOGETHER WITH the complete result evidence the record exposes for that attempt (`record["results"][str(N)]` restricted to the evidence vocabulary: outcome, launched, refusal, retry timing, identity, CLI version, usage availability, start/end timing, usage, cost, output text + sha). Absence is evidence: a changed field, a vanished field, a vanished payload and an empty payload each hash differently, so historical replays below `prior_max` conflict while byte-identical replays stay no-ops (`_c` green) |
| AD7-3 | **ADDRESSED** | `51a7337` | both AD7-3 tests red exactly as the review repro'd: an ordinary (pre-reservation) ledger squatting the probe uuid5 — `_is_authorized_probe` false — settled SUCCEEDED claiming the expected identity and the receipt WAS written: direct call `assert not …exists()` failed on `qualification_receipt.json`, and the recovery e2e (RUNNING ledger, dead unit, valid result file, `gateway.recover()`) wrote the receipt through `_settle_from_result` too | `_maybe_complete_requalify` requires `_is_authorized_probe(invocation_id)` before anything is written. Every settlement path (supervision, pump reconciliation, restart recovery) funnels through `_settle_from_result` → `_maybe_complete_requalify`, so the check covers recovery by construction. The squatter still settles DONE from its own result; no receipt, latch retained (memory + file) |
| AD7-4 | **ADDRESSED** | `15ce674` | `test_ad7_4_a…`: latch + genuine probe queued (`_ensure_requalify_probe` → ACCEPTED), gateway rebuilt on the same store with `--requalify-model opus` → `restarted._is_authorized_probe(probe_id)` was **False** (assertion failed) and the pump would return false forever — the probe stranded ACCEPTED | the review's option 1 (preserve authorization for the frozen request): `_ensure_requalify_probe` writes `probe_request_hash` into the STATE at freeze, re-freeze and every re-arm (a key ONLY the internal path writes), and `_is_authorized_probe` requires marker AND the state binding AND the request record hashing its own content. The config-changed gateway still authorizes and LAUNCHES the queued probe (pump → RUNNING); the settled probe re-arms and re-freezes under the new config (`_b`); a rewritten request file with a self-consistent hash fails the state binding (`_c`, AD6-8c stays shut) |

## Verification coverage (14 Nov 2026, all on tip `15ce674` unless noted)

- `tests/unit/llm`: **118 passed** (112 from fix3 + 6 new: AD7-1 ×1, AD7-2 ×5
  incl. the 3-param mutation matrix and the identical-replay control).
- `tests/integration/llm_gateway`: **80 passed** (75 from fix3 + 5 new: AD7-3
  direct + recovery e2e, AD7-4 strand-guard + re-arm + tamper-guard) — real
  transient `dramabox-llm-test-*` systemd units; the AD5-10 e2e requalify
  (a REAL probe through the launch path writing a REAL receipt) stays green
  under the new state-bound authorization.
- Full `tests/unit` sweep: **3222 passed in 51:11** (real PostgreSQL/Redis
  fixtures, CPUQuota 45%) — the whole unit tree green on the tip, pipeline
  dir included, no AD6-GATE-1 flake encountered. A first attempt was killed
  at the harness background limit before pytest flushed any output; the
  rerun above is the recorded result (`/tmp/a0d-fix4-unit-sweep2.log`).
- `make lint` equivalent (`ruff check` + `ruff format --check`) on every file
  touched by each commit: clean before every commit.
- Not run, per the brief: full `make check` / `make pilot` (the orchestrator
  gates them after R5). The AD6-GATE-1 scheduler flake was not chased; this
  diff has no import-path overlap with the pipeline world (unchanged from
  fix3's analysis).

## Deviations

1. **AD7-2's red test targets the exposed-payload route, not the settling
   `result`.** A literal reading of "replaying attempt 1" — the settling
   `result` naming attempt 1 — does conflict at round 3, but for an unrelated
   pre-existing reason: with both attempt rows recorded, `number == prior_max`
   forces the invocation-level comparison, and the stale-result path nulls
   `structured_output_sha256` against the stored attempt-2 sha. The review's
   own "no Conflict" repro ("historical payload processing compares only quota
   evidence") is the EXPOSED route — `record["results"]["1"]` doctored while
   the settling result replays byte-identically — and that is what
   `test_ad7_2_a/b` script. My first draft used the settling-result route and
   passed at round 3 for the wrong reason; it was corrected before being
   recorded as red.
2. **The fake gateway client gained durable-result fidelity.**
   `FakeLlmGatewayClient` now folds a scripted `record.result` into
   `record.results[str(attempt)]` at every exposure (script, accept,
   get_status) — the real gateway builds `results` from the per-attempt result
   FILES, so once a result exists every later status body carries it. Without
   the fold the fake's bodies hide per-attempt evidence the real gateway
   always exposes, and the new pinning would false-conflict on legitimate
   flows (found via `test_ad5_6_c`, next item).
3. **One round-2-era fixture repaired to the faithful status shape.**
   `test_ad5_6_c_a_distinct_later_attempt_supersedes_the_invocation_result`
   superseded the invocation mirror through a hand-built record with NO
   `results` map — i.e. a record that hides attempt 1's settled payload.
   Under absence-as-evidence that replay is now (correctly) a Conflict, so
   the fixture now scripts `results` with both attempts' payloads exactly as
   the real gateway would (same repair pattern as fix3's Deviation 2).
4. **The attempt-evidence hash function changed**, so attempt rows written by
   the round-3 code would not compare equal against round-4 replays. No
   migration is involved (the schema is untouched; `result_sha256` is a
   hash-bearing TEXT column) and the gateway is pre-production (offline/mock
   by default), so this is accepted; noted here for the record.
5. **AD7-4 chose the review's first option** (preserve authorization for the
   frozen request) over cancel-and-rearm: a state key (`probe_request_hash`)
   that only `_ensure_requalify_probe` writes binds the frozen bytes. A probe
   ledger frozen by the round-3 build (no state binding) self-heals at the
   next re-arm (the ACCEPTED update rebinds the hash); a QUEUED pre-fix4
   probe ledger would strand until terminal — dev/test stores only, accepted.
6. **AD7-3 + AD7-4 interact by design**: the receipt check added for AD7-3
   uses the same `_is_authorized_probe` that AD7-4 re-binds, so a genuine
   probe that launched under a configuration the operator later changed still
   earns its receipt (its identity binding is unchanged by a model swap).

## Anything stopped at red

Nothing. Every finding reached green.

## Resume here

Nothing to resume. All four review findings are addressed and committed
(`15ce674` tip, 4 commits on `a4e9913`, nothing pushed), and the verification
is complete: `tests/unit` **3222 passed** (incl. `tests/unit/llm` 118),
`tests/integration/llm_gateway` **80 passed**, `make lint` clean before every
commit. For the orchestrator: round-5 verification against
`a4e9913..15ce674`, then `make check` + `make pilot` (the AD6-GATE-1 note in
the fix3 report applies to the check).
