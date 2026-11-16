# A0-D FIX3: ALL FINDINGS ADDRESSED

# A0-D fix round 3 — the round-3 findings AD6-1..AD6-10 + AD6-GATE-1

Build: GLM (A0-D fix3 brief, 14 Nov 2026). Base `b84a397`, worktree
`drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`. Requirement list:
`codex-review-a0d-r3.md`. **The brief said "AD6-1..7 (5 BLOCKING + 2
SHOULD-FIX)"; the review itself lists AD6-1..AD6-10 (8 BLOCKING + 2
SHOULD-FIX — AD6-8/9/10 arrive under AD5-10). The review wins per the brief,
so all TEN were fixed**, plus the orchestrator's AD6-GATE-1. All closed with
red→green evidence; nothing stopped at red; nothing merged or pushed.
`make lint` clean before every commit.

Commits (on top of `b84a397`, tip `a4e9913`):
- `0893454` — cluster 1: AD6-1, AD6-5, AD6-6 (step.py)
- `c3182c2` — cluster 2: AD6-3 (both validator twins + corpus)
- `30a2777` — cluster 3: AD6-4, AD6-7 (cancel adoption + reconciler + step helper)
- `a4e9913` — cluster 4: AD6-2, AD6-8, AD6-9, AD6-10 (gateway)

## Per-finding status

| ID | Status | Commit | Red | Green |
|----|--------|--------|-----|-------|
| AD6-1 | **CLOSED** | `0893454` | claim 2 (config moved A→B, op returned to PENDING_SUBMIT) hit `IdempotencyConflict` at begin — the refilled identity moved the request hash; no resubmission (test asserted a second POST) | claim 2 POSTs the frozen request byte-identically (identity A), the frozen row keeps A, the job stays unfailed; the pre-written test was repaired first (see Deviations 1) |
| AD6-2 | **CLOSED** | `a4e9913` | `test_ad6_2_a…never_loaded_settles_from_the_result` + `…_no_result_is_unknown` failed at round 2: the never_created branch recorded ISOLATION_UNAVAILABLE launched=false without calling the result reader (timed-out launch, unit GC'd to not-loaded, valid result present) | both green: the branch consults `read_valid_result` like the exited branch — result → DONE/SUCCEEDED launched=true; no result + timed-out launcher → UNKNOWN; completed systemd-run refusal still ISOLATION_UNAVAILABLE launched=false (round-1 AD-8 tests unchanged and green) |
| AD6-3 | **CLOSED** | `c3182c2` | 3 corpus cases failed on BOTH twins: `additionalProperties:false` with omitted `properties` accepted every property; `const [true]` accepted `[1]`; `enum [{"v":true}]` accepted `{"v":1}` | 34-case corpus green (twins agree verdict-for-verdict): `properties` defaults to `{}` (no declared property → every property is additional) and `_json_equal` compares containers recursively so a nested boolean is never the number 1, in both twins |
| AD6-4 | **CLOSED** | `30a2777` | with frozen identity A and the adoption/reconciler configured for B, a result claiming B settled SUCCEEDED (and omitted configuration accepted foreign identities) — `test_ad6_4_a/b` (adoption) and `test_ad6_4_…changed_configuration` (reconciler) all red via a temporary revert | recovery binds to `frozen_policy_identity(db, invocation_id)` (the persisted frozen call, keyed like `frozen_schema_text`); the configured identity is only the fallback — a foreign claim settles FAILED/INVALID_OUTPUT whatever the configuration says; the CLI flag from `b84a397` remains as the fallback path |
| AD6-5 | **CLOSED** | `0893454` | same-attempt replay with a changed `policy_identity`/`cli_version`/`usage_unavailable` DID NOT RAISE (`test_ad6_5_a` ×3); a replay with its recorded quota readings REMOVED did not raise (`test_ad6_5_b`) | the invocation-level compare covers the complete evidence (identity, CLI version, usage availability, timing join outcome/output/usage/cost), and `_record_quota_observation` treats vanishing readings on a recorded attempt as a Conflict; round-2's AD5-6 tests stay green |
| AD6-6 | **CLOSED** | `0893454` | after refusal 1 + readmission + queued cancellation 2, the mirror settled the invocation REFUSED from the stale status result and attributed attempt 1's quota to attempt 2 (`test_ad6_6_a`: outcome REFUSED ≠ CANCELLED) | a result naming an earlier attempt is bound to ITS attempt: the invocation settles from the latest attempt's own entry (CANCELLED), identity columns are preserved (never taken from a result the attempt never wrote), and the stale readings attribute to attempt 1; the AD-10 three-attempt test stays green with a corrected fixture (Deviations 2) |
| AD6-7 | **CLOSED** | `30a2777` | a 404 status (`get_status → None`) raised AttributeError on `record.get`, aborting the whole sweep — `test_ad6_7_a` red via temporary revert (B never adopted) | a None record is skipped explicitly and the sweep CONTINUES: in the same pass a later operation still settles (the test's invocation B adopts CANCELLED while A 404s) |
| AD6-8 | **CLOSED** | `a4e9913` | an ordinary API request squatting the predictable probe uuid5 was accepted (202) and launched while latched; a doctored marker with a foreign request hash launched too (`test_ad6_8_a/b/c` red at round 2) | the probe id is RESERVED (accept → 409 `PROBE_ID_RESERVED`), and the latched pump launches only the internally created probe: the `requalify_probe` marker AND the exact frozen probe-request hash (`_is_authorized_probe`), re-frozen at re-arm when the probe configuration changed; the authorized probe still launches (`test_ad6_8_d` positive control) |
| AD6-9 | **CLOSED** | `a4e9913` | recovery returned after the FIRST violation: a receipt covering the old latched violation cleared health while a NEWER uncovered violation sat in another ledger (`test_ad6_9_recovery_latches_the_newest_uncovered_violation` red at round 2) | `_restore_isolation_latch` collects EVERY applicable violation (the latch file and every settled ledger) and clears only when the receipt covers them all, latching the newest uncovered one; the covers-all case stays green |
| AD6-10 | **CLOSED** | `a4e9913` | a failed receipt write was swallowed and the quarantine cleared anyway (in memory and the latch file deleted) — `test_ad6_10_a_failed_receipt_write_retains_the_quarantine` red at round 2 | durable persistence is a precondition of clearance: on OSError the violation and the latch file are retained; once a write succeeds the same pass clears; a restart with no receipt relatches (companion test) |
| AD6-GATE-1 | **PRE-EXISTING at `6974d5a` — not caused by fix2; evidence below** | — (no code change) | the orchestrator's gate (`.scratch/a0d-gate3/.scratch/gate/check.log`) failed `test_scheduler_driven_path.py::…two_gates` at clean `b84a397` with `assert []` (600 scheduler fires, no PUBLISHED_VERIFIED post) | see "AD6-GATE-1 analysis" |

## AD6-GATE-1 analysis

1. **Fix2's diff cannot reach this test.** `git diff --stat 6974d5a..b84a397`
   touches only `src/microdrama/llm/*`, `deployment/llm-gateway/*`, their
   fakes/fixtures and their tests. The scheduler-driven path runs the OFFLINE
   pipeline world, which `build_pipeline_world` composes on the LEGACY
   synchronous `LlmProvider` path (`src/microdrama/pipeline/world.py` refuses
   `llm_route=subscription` outright); no module under
   `src/microdrama/{pipeline,scheduling,workers,core}` imports
   `microdrama.llm` (verified by grep). Every file the test executes is
   byte-identical between `6974d5a` and `b84a397`.
2. **Behavioral confirmation.** At the fix3 tip the test passes standalone
   (134 s, no CPUQuota). In a clean worktree at `b84a397`
   (`.scratch/a0d-gate1-ab`, removed after the run) the whole
   `tests/integration/pipeline` directory passes — **53 passed in 575 s**
   (9:35), including `test_scheduler_and_workers_drive_release_with_only_the_two_gates`
   — i.e. the failure does not reproduce at the gated commit in a quiet
   environment, only in the orchestrator's loaded full-`make check` run.
3. **Conclusion.** The failure is environment/load-sensitive (the test drives
   real FFmpeg inside a 600-iteration loop on a shared VPS whose load floor is
   set by the MT5 terminals), pre-existing identically at `6974d5a`; per the
   brief it is reported with evidence instead of "fixed". No code change was
   made for it. Recommendation for the round-4 gate: if `make check` hits it
   again, rerun the single test in isolation before treating it as a
   regression.

## Verification coverage (all green lines, 14 Nov 2026)

- `tests/unit/llm`: **112 passed** (all AD6 tests + the pre-existing suites,
  incl. the 34-case validator corpus cross-check).
- `tests/integration/llm_gateway`: **75 passed** (real systemd, real transient
  `dramabox-llm-test-*` units, fake ai-route shim; includes the mandatory
  AD5-1 producer-vs-admission chain, the AD5-2 launch-evidence matrix and the
  8 new requalify-security tests).
- Regression sweeps: core+budget+workers **736 passed**, review+publishing+
  analytics+references **702 passed**, contract **462 passed**, unit pipeline +
  integration persistence/validation **319 passed + 1 load flake** —
  `test_t044b_gate2_owner_metadata…` errored with `ffmpeg failed` in the edit
  lane while three heavy suites ran concurrently (load 17+); the edit lane has
  zero overlap with this diff and the same test **passes in isolation
  (94 s)** — environmental, not a regression. All sweeps ran on the fix3 tip
  `a4e9913`. Not re-run (no import-path overlap with this diff, unchanged from
  round 2): the remaining `tests/unit/{api,community,editing,qa,registry,
  research,scaffold,story,testing_harness}` and the non-routing remainder of
  `rendering`; the orchestrator's `make check` after round 4 covers them.
- `make lint` (`ruff check` + `ruff format --check`): clean immediately before
  every commit.

## Deviations

1. **The pre-existing uncommitted AD6 test drafts were repaired, not
   adopted verbatim.** The worktree contained red-test drafts for AD6-1/3/5/6
   from an interrupted earlier pass (no fix3 report existed). Three defects
   were fixed: an empty stub redefining `test_ad5_6_a…` shadowed the round-2
   test (silently deleting its coverage); the AD6-1 draft never advanced the
   clock between claims (claim 2 found no claimable job — every assertion
   vacuous, the test PASSED at round 2) and updated `provider_operations` with
   the wrong provider string (`llm-gateway` vs `dramabox-llm-gateway` — zero
   rows matched); the AD6-6 draft called `mirror_invocation_result` with no
   invocation row (FK violation). After repair each reproduces its review
   scenario and is red at round 2 / green at the fix.
2. **The AD-10 fixture names its attempts** (the attempt-2 refusal result now
   carries `"attempt": 2`): the real gateway's envelope check
   (`result_envelope_violation`) rejects a result naming another attempt, so
   the old fixture was scripting a payload the gateway can never produce;
   AD6-6 binds readings to the named attempt.
3. **The round-2 corpus test stays the twin-agreement harness** — the six
   AD6-3 cases extend it rather than adding a parallel harness.
4. **AD6-1's gate binding**: for an EXISTING invocation the admission gate
   binds the frozen PERSISTED identity (the gateway must be qualified as the
   identity the work was frozen under); a FIRST freeze still binds to the
   configured identity, and an explicitly-frozen identity other than the
   binding one is still refused (AD5-1's tests unchanged and green). Without
   this, reloading alone would make the A→B replay die at the in-`_submit`
   gate — the review's scenario demands the replay succeed.
5. **AD6-8 re-freeze scope**: a changed probe configuration
   (`--requalify-model`/`--requalify-scenario`) re-freezes the probe request
   only at RE-ARM of a terminal probe (never mid-flight), preserving the
   attempt history; an in-flight probe keeps the request it launched with.
6. **Brief count correction**: the brief announced AD6-1..7; the review lists
   AD6-1..10. The review wins (stated up front); all ten are closed.

## Anything stopped at red

Nothing. Every finding reached green.

## Resume here

Nothing to resume. All ten review findings and the gate triage are complete
and committed (`a4e9913` tip, 4 commits on `b84a397`, nothing pushed). For the
orchestrator: round-4 verification against `b84a397..a4e9913`, then
`make check` + `make pilot` (AD6-GATE-1 note above applies to the check).
