# A0-D FIX2: ALL FINDINGS ADDRESSED

# A0-D fix round 2 — the ten Codex findings AD5-1..AD5-10

Build: GLM (A0-D fix2 brief, 14 Nov 2026). Base `6974d5a`, worktree
`drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`. Requirement list:
`codex-review-a0d-r2.md` (AD-1 REGRESSED + AD5-1..10; 7 BLOCKING, 2 SHOULD-FIX,
AD5-10 BLOCKING). All ten closed with red→green evidence; nothing stopped at
red; nothing merged or pushed. `make lint` clean before every commit.

Commits (on top of `6974d5a`, tip `b84a397`):
- `20f8db6` — cluster 1: AD5-1, AD5-3, AD5-5 (+ AD5-9 pulled forward: the
  AD5-1 identity-binding test rides its pre-gate)
- `9e33051` — cluster 2: AD5-4, AD5-6, AD5-7, AD5-8
- `735a5e0` — cluster 3: AD5-2, AD5-10
- `b84a397` — AD5-4 follow-up: the reconciler CLI's `--expected-policy-identity`

## Per-finding status

| ID | Status | Commit | Red | Green |
|----|--------|--------|-----|-------|
| AD5-1 | **CLOSED** | `20f8db6` | unit: 34 failed (`FrozenLlmCall` had no `policy_identity`; the producer's request carried no identity); integration: the real `FrozenLlmCall.request_text` POST failed admission (3 failed incl. the mandatory producer-vs-admission chain) | unit `tests/unit/llm` 84 passed at that commit; `test_gateway_producer_admission.py` 5 passed — the real producer accepts 202, settles DONE with the identity echoed and bound |
| AD5-2 | **CLOSED** | `735a5e0` | `test_gateway_launch_evidence.py` 3 failed: an exited unit settled `ISOLATION_UNAVAILABLE, launched=false` whether or not a valid result existed; the round-1 timeout test's DONE+execution-count assertions allowed it | 6 passed: valid result → settled from the result through the shared `_settle_from_result`; exited without a result → UNKNOWN (never false absence, never relaunched); completed systemd-run refusal still settles `ISOLATION_UNAVAILABLE launched=false`; an end-to-end wrapper test (real systemd-run runs, result written, launcher times out) settles DONE with launched=true |
| AD5-3 | **CLOSED** | `20f8db6` | corpus: 9 new cases failed (`confidence: 2` vs `maximum: 1` accepted by BOTH twins; enum/minLength/items/additionalProperties/const ignored; `pattern` ignored; a REFUSED result with a mismatched identity diverged: gateway valid, src invalid); accept-side: unsupported schemas accepted 202 | 28-case corpus green (twins agree verdict-for-verdict, identity bound for EVERY outcome); accept refuses unsupported constraint keywords 400 `BAD_REQUEST_TEXT`; a `maxLength` violation settles UNKNOWN end to end |
| AD5-4 | **CLOSED** | `9e33051` + `b84a397` | adoption of `{"outcome": "SUCCEEDED"}` (no envelope/output/hash) settled SUCCEEDED; the reconciler's DONE validation omitted the expected identity (a hijacked-identity result was adopted) | the bare-success probe settles FAILED/INVALID_OUTPUT with nothing adopted; the reconciler (constructed with `expected_policy_identity`) fails a foreign-identity result INVALID_OUTPUT; the CLI takes `--expected-policy-identity` |
| AD5-5 | **CLOSED** | `20f8db6` | the mapper read `five_hour_bp`/`five_hour_reset_at_ms`/`week_reset_at_ms` — A0-R1's `strict_quota_snapshot` (`5h_bp`, `5h_reset_ms`, `week_reset_ms`, verified in the a0r1 worktree) lost both five-hour readings and both resets; the shim spoke the old names | `test_ad5_5_quota_mapping…` green (all six readings mapped); the shim emits the A0-R1 names verbatim (integration asserts the exact key set) |
| AD5-6 | **CLOSED** | `9e33051` | a same-attempt replay with a changed output/hash silently replaced the invocation result; a changed quota was a silent `DO NOTHING` (old quota kept) — `test_ad5_6_a/b` red (no Conflict) | both raise Conflict with the stored evidence untouched; quota rows are compare-before-mutate (identical replay no-op); a distinct later attempt still supersedes (`test_ad5_6_c`, a regression guard that also passed pre-fix) |
| AD5-7 | **CLOSED** | `9e33051` | the reconciler's REFUSED/CANCELLED branches and the CANCELLED adoption (mirror=None) left no attempt row and no quota; the submit path's readmit dropped the refused attempt's quota (the round-1 test blessed three attempts with two quota rows); status exposed only the latest result | every settlement mirrors (reconciler REFUSED/CANCELLED, adoption CANCELLED/REFUSED/DONE, the readmit path from the accept response's own record); the gateway status body exposes EVERY attempt's result (`results`, kept in tombstones); any later settlement harvests historical quota observations; the AD-10 test now expects three quota rows `[1,2,3]` |
| AD5-8 | **CLOSED** | `9e33051` | all three pending-submit races stranded: launched CANCELLED skipped (§5.5(4) guard), DONE and REFUSED skipped for PENDING_SUBMIT | a PENDING_SUBMIT whose lost POST the gateway provably received settles through the legal SUBMITTED transition first: launched CANCELLED → CANCELLED, DONE (validated) → SUCCEEDED/FAILED with metering mirrored and content discarded, REFUSED → REFUSED_PRELAUNCH with evidence; nothing left in flight |
| AD5-9 | **CLOSED** | `20f8db6` | a reachable-red gateway refusal left a PENDING_SUBMIT operation (created before the gate) and the job in NEEDS_RECONCILIATION — `test_ad5_9_red_health_refusal…` red (op row existed) | `ensure()` gates BEFORE begin/rearm when the op is new or NOT_FOUND/REFUSED_PRELAUNCH: red health → `LLM_GATEWAY_UNHEALTHY`, zero provider_operations rows, no POST; the rearm case leaves the settled op untouched; settlement of existing work never passes the pre-gate (round-1 AD-6 tests unchanged and green) |
| AD5-10 | **CLOSED** | `735a5e0` | requalify cleared the latch from the configured identity alone (health advertises it); a restart relatched the historical violation; both tests red (no probe, no receipt, `--requalify-scenario` unknown) | requalify starts a REAL probe invocation through the production launch path (deterministic id, expected identity frozen in the request); only its validated, identity-bound SUCCEEDED writes the durable receipt and clears the latch; the pump launches ONLY the probe while latched; a failing probe keeps the quarantine (fresh attempt per call); a restart honors a receipt covering the violation's epoch — the full latch→restart→probe→receipt→restart chain is green end to end |

## What each fix does

- **AD5-1** (`step.py`): `FrozenLlmCall` gains `policy_identity`, included in
  both `request_text` (the gateway freezes and binds it) and `frozen_call_text`
  (persisted). `LlmStep.ensure` deterministically fills a missing identity from
  its expected (qualified) identity — the request hash never moves between
  claims — refuses a call frozen with a DIFFERENT identity at admission, and
  raises a clear configuration error when neither is known. The mandatory
  integration test runs the real producer (`FrozenLlmCall.request_text`) against
  the real gateway process: accept 202, replay 202, launch, DONE with the
  identity echoed — the shim's echo no longer masks anything because the
  producer's own bytes are what admission validates.
- **AD5-3** (both twins + accept): a single enforced vocabulary — `type`,
  `properties`, `required`, `items`, `enum`, `const`, `minimum`/`maximum`,
  `minLength`/`maxLength`, `minItems`/`maxItems`,
  `additionalProperties: false` — with annotation keywords (title, description,
  default, examples, $schema, $comment) ignored and EVERY other constraint
  keyword rejected (400 at accept; cannot validate at settlement, both sides).
  The gateway twin's identity check moved before the SUCCEEDED early-return:
  identity binds every outcome, identically to the src twin.
- **AD5-5** (`step.py` + shim): the quota mapper reads `5h_bp`/`5h_reset_ms`/
  `week_bp`/`week_reset_ms` — verified against A0-R1's `strict_quota_snapshot`
  in the a0r1 worktree (read-only); the shim emits the same names.
- **AD5-9** (`step.py`): a read-only op lookup by `(provider, client_token)`;
  when no operation exists or it is NOT_FOUND/REFUSED_PRELAUNCH, the §5.7 gate
  runs BEFORE `begin`/`resubmit_allowed`. The in-`_submit` gate stays for
  operations that already existed as PENDING_SUBMIT (round-1 AD-6 semantics).
- **AD5-6** (`mirror_invocation_result`): invocation-level evidence (outcome,
  output sha, model_usage, cost) is compared before mutation — same-attempt
  replay with different evidence → Conflict; later attempt → supersedes; stale
  earlier record → newer evidence kept. Quota observations compare all eight
  reading columns plus the uncertainty set (identical → no-op, else Conflict).
- **AD5-7**: mirrors added to the reconciler's REFUSED/CANCELLED branches, the
  adoption's CANCELLED/REFUSED branches, and the `_submit` readmit path (from
  the accept response's record, whose latest attempt IS the refused one). The
  gateway `status()` exposes `results` (every attempt's envelope-valid result;
  tombstones keep the map), and `mirror_invocation_result` harvests a quota
  observation for every exposed attempt result.
- **AD5-4**: `adopt_confirmed_cancels` validates DONE answers through
  `validate_gateway_result` (envelope + integrity + frozen schema + expected
  identity) before settling or mirroring — invalid → FAILED/INVALID_OUTPUT with
  a sanitized mirror; `LlmReconciler`/`adopt_confirmed_cancels` gained
  `expected_policy_identity` (constructor/function param; CLI flag
  `--expected-policy-identity`), used in the DONE branch.
- **AD5-8**: `adopt_confirmed_cancels` records SUBMITTED first (legal, with the
  gateway's own record as the authority that the POST arrived) then the terminal
  answer, in one transaction — PENDING_SUBMIT never blocks adoption of an
  authoritative terminal answer again.
- **AD5-2** (`gateway.py`): `_reconcile_ambiguous_launch` now distinguishes
  `launched` (live) / `exited` (inactive|failed — indistinguishable from
  created-and-finished on this systemd) / `never_created` (not loaded) /
  `inspection`; the pump's `exited` path consults the durable result first
  (shared `_settle_from_result`, also used by `supervise_once` and `_recover_one`),
  keeps UNKNOWN for a result-less timed-out launcher, and reserves
  ISOLATION_UNAVAILABLE launched=false for a COMPLETED systemd-run refusal.
- **AD5-10** (`gateway.py` + INSTALL.md): verified requalification —
  `POST /v1/requalify` (configured identity only) starts a probe invocation
  (deterministic uuid5 id, minimal line schema, `--requalify-model`, budget
  100_000 microusd, the expected identity frozen in); the pump launches only
  the probe while latched; `_maybe_complete_requalify` writes
  `qualification_receipt.json` on a validated identity-bound SUCCEEDED and
  clears a covered latch; `_restore_isolation_latch` honors a receipt whose
  `verified_at_ms` ≥ the violation's epoch (`ended_at_ms`, fallback
  `latched_at_ms`). INSTALL.md documents the procedure and the one-real-call
  budget note.

## Verification coverage (all green lines, 14 Nov 2026)

- `tests/unit/llm`: **96 passed** (all AD5 tests + the pre-existing suites,
  incl. the 28-case validator corpus cross-check).
- `tests/integration/llm_gateway`: **65 passed** (real systemd, real transient
  `dramabox-llm-test-*` units, fake ai-route shim; combined run with the unit
  suite: 161 passed; no test units left loaded afterwards).
- Regression sweep (jobs/provider-ops/step import paths): core+budget
  **690**, workers **46**, pipeline+review **401**, publishing+analytics+
  references **401**, migration-0027 persistence **9** — all passed. The
  monolithic sweep hit the 10-minute background limit (as in round 1); the
  chunked runs above are the recorded coverage. Not re-run (no import-path
  overlap with this diff, unchanged from round 1): the remaining
  `tests/unit/{api,community,editing,qa,registry,research,scaffold,story,
  testing_harness}` and the non-routing remainder of `rendering`; the
  orchestrator's `make check` after round 3 covers them.
- `make lint` (`ruff check` + `ruff format --check`): clean immediately before
  every commit.

## Deviations (with reasons)

1. **AD5-3 chooses "reject unsupported schemas"** over implementing all of
   JSON Schema: the enforced vocabulary (listed above) is complete for it, and
   anything outside it is refused at accept and cannot validate anywhere —
   the review offered either direction. Annotations are ignored (they carry
   no constraint).
2. **The twins remain twin implementations** (round-1 deviation 1, unchanged:
   §4.1 forbids package imports in the gateway) — now bound by the 28-case
   corpus including the outcome-aware identity cases that caught the
   divergence.
3. **Existing tests updated to corrected contracts** (the findings invalidate
   the old expectations): `llm_world` calls carry `policy_identity`; the AD-10
   quota test expects `[1,2,3]` quota rows (the review itself flagged the old
   `[2,3]` as three-attempts-two-rows); the AD-7 requalify test drives the
   probe (clearance only after a passing one); the shim and fakes speak the
   A0-R1 quota names and expose `results`. The gateway status body's `results`
   map is additive.
4. **AD5-2, systemd reality**: this host's systemd GCs finished transient
   units to `inactive`/`not-found` — byte-identical to never-created (verified
   empirically: a never-loaded unit shows `inactive`, an exited transient unit
   shows `inactive`/`not-found` within seconds, LoadState is not durable).
   Hence the honest classification: durable result first; UNKNOWN for a
   result-less timed-out launcher; ISOLATION_UNAVAILABLE launched=false only
   for a completed systemd-run refusal. The round-1 "authoritative absence"
   case (`unit_active_state → None`) still settles refusal via the
   `never_created` branch and its test is unchanged and green.
5. **AD5-9 scope**: the pre-gate runs only where begin/rearm would CREATE or
   re-arm intent (no op, or NOT_FOUND/REFUSED_PRELAUNCH). Operations already
   PENDING_SUBMIT keep the round-1 in-`_submit` gate (the POST is the
   admission; a refusal there is recovered by the reconciler) — exactly the
   "gate new admissions, retain unrestricted settlement" line.
6. **AD5-10 cost note**: each requalify probe is one real dramabox-llm call
   (§7's at-most-5 envelope applies). `--requalify-model` (default `sonnet`)
   and `--requalify-scenario` (default `ok`; rides the gateway-internal
   scenario field the real CLI never sees) are the new test seams.
7. **AD5-1 hash note**: `request_text` now includes `policy_identity`, so
   request hashes differ from round 1's — no production gateway data exists,
   and both sides of the contract moved in the same commit.

## Anything stopped at red

Nothing. Every finding reached green.

## Resume here

Nothing to resume. All ten findings are closed and committed (`b84a397` tip, 4
commits on `6974d5a`, nothing pushed). For the orchestrator: round-3
verification against `6974d5a..b84a397`, then `make check` + `make pilot`.
