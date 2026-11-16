# T031 native implementation handoff — 6 November 2026

**IN_PROGRESS, NEEDS INDEPENDENT REVIEW. No paid run is authorized.**
Operator direction: native Codex for everything, no ai-route. This overrides old
GLM routing/quota instructions for this work. Do not switch providers.

## Current gate result — verified 7 November 2026

Full `make check` has finished with exit2: unit2879passed, contract462passed;
integration258passed,8failed,4setup errors. `make pilot` was NOT_RUN.
Failures include hardcoded migration-tail expectations after adding0026 and actual
missing delete/truncate/non-integer safeguards on new benchmark tables. These are
open failures, not acceptance. Diagnose/fix them narrowly before rerunning affected
checks; do not rent a Pod or treat the image/124-test receipt as live readiness.

## Work preserved

Implementation worktree `/root/AIVORA/drama-box/.scratch/t031-native-worktree`,
branch `feat/t031-pika-flex-native`, base0851374. All81 implementation files are
uncommitted/unmerged. Main checkout keeps earlier docs and canary receipts.
Complete source snapshot including new files:
`.scratch/keep/t031-native-review/full-current/{manifest.json,patch.diff,source/}`.
Patch SHA256: `282f95be45dc8477ee432e19395ef4ab61a4434dac8923a4d8662d28eaae94b8`.
Verify current bytes against manifest before using any receipt.

- Native EGM Goldfish full flow and scoped re-audit completed; independent guardian
  accepted VOICE role/package2.16.0, existing payload versions/hashes unchanged.
- R1/R2 transport/mapper fixes independently ACCEPTED after scoped redaction fix.
- Actual local code-only image built: `drama-pika-h3-flex:t031-native`, image ID
  `sha256:773f4df5effd1f9087bacc4b693c97e633dbbbef9f8cbac784bc3ea3896d142d`.
  Real CPU HTTP schema16 nodes and6 offline provisioning tests passed. No weights.
- Native bindings implemented; implementer receipts489 focused+contract tests,
  then33 final focused tests. Independent binding reviewer verified snapshot hashes
  but hit native usage limit BEFORE a verdict: NOT accepted.
- Durable experiment repo, canonical reservation extraction/adoption, CLI/auth and
  default experimental world are implemented but need integration/fault review.
  Native world/runner workers also stopped on a usage-limit error; parent preserved
  and corrected local integration instead of switching providers.
- Latest combined focused run: **124 passed in82.71s**. Includes actual canonical
  job/reservation/lease/Comfy services with scripted providers for24 samples,
  restarted coordinator objects, same account, distinct repeat output paths,
  24jobs and30 distinct holds:24prompt +2compute +2storage +2cleanup.
  Samples retain quality UNKNOWN. This is connected offline evidence, not H3/Thai
  quality or default real-provider qualification.
- Ruff check/format passed (592files), generated contracts check passed:
  2.16.0,104schemas,74valid/135invalid examples; diff-check clean. CLI help verified
  with PYTHONPATH=src. Earlier direct commands omitted PYTHONPATH and failed import;
  those invocation failures were corrected, not represented as runtime defects.

## Full checks — historical launch, now failed

Durable unit `t031-native-offline-gates.service`, invocation
`c5c5188062154e1595994ab124ff42ab`, CPUQuota45%, two-hour timeout. It runs `make check`
then `make pilot` only if checks pass, OFFLINE_MOCK with paid/cloud/public flags off.
No code edits after the snapshot while this gate run is active.

Receipts under worktree `.scratch/native-gates/`:
`check.log`, `check.exit`, `pilot.log`, `pilot.exit`, `overall.exit`.
A missing/RUNNING receipt is NOT success. At resume read these once; if still
running wait using the execution tool rather than busy polling. Preserve the
first failed receipt and diagnose it before rerunning expensive suites.

## Exact next work

1. Read gate receipts and verify81 frozen source hashes. If checks fail, fix only
   concrete failures, run focused checks, regenerate a source snapshot and rerun
   affected gates. No budget/task reset and no fresh live canary.
2. When native reviewer quota is available, complete an independent code review of
   the frozen binding snapshot and all final world/runner/CLI changes. Reviewer
   cannot be the implementer. Prior interrupted reviewer is NOT a clean pass.
   No ai-route/Codex CLI workaround. At most two scoped rounds per review cycle.
3. Review actual default live factory, not just injected fixture callbacks:
   current model AND reference rights; auth byte hash/current caps; logical plan
   alias/seal identity; per-shot speaker/outfit selection; raw schema attestation;
   acquisition-scoped uploads/UNKNOWN reconciliation; no duplicate create after
   durable intent; no duplicate prompt after uncertainty; slot races; expired
   cleanup; storage+invoice finality and raw billing evidence persistence.
   The124-test composed fixture exercises `_advance` with canonical services but
   is not proof that public execute/default native composition is correct.
4. Require no-effect preflight to read current canonical account/rights/asset state
   honestly. Review remaining readiness semantics carefully: it must not report
   executable-ready merely from labels/hashes while default factory later refuses.
   CPU/no-weight filename enums cannot be relabelled as LIVE executable attestation.
5. After independent acceptance/full gates, update final ledgers and present the
   exact paid screen configuration. $8proposal unsigned; no provider/GPU account,
   image push, model download, production migration, publishing or application
   approval is authorized by this code work. Actual A40 fit and Thai quality remain
   separate paid qualification, not proven by CPU schema or synthetic media.

## Integration changes made after worker interruption

Parent owns auth/CLI modules and their tests. Corrected missing REQUEST price unit,
canonical lowercase sample-specific `bench-s01-r1` IDs (avoids repeat output-key
collision), synthetic cost basis for fake lease-covered zero settlements, retained
failure codes, input-safe diagnostics and explicit current model-output rights
pins. These edits require independent review. Model-rights profile pins are
`model_rights_subject_kind=MODEL_OUTPUT`, `model_rights_subject_ref`,
`model_rights_version`, `model_rights_evidence_sha256`, bound into prepared profile
hash. Reference grants alone never clear model rights.

Use design spec/implementation contract as baseline; contract financial hold unit
is actual canonical `PriceUnit.REQUEST`, not nonexistent CALL. Preserve existing
three-attempt canary and production preset eligibility. Do not restart services,
clear shared data/caches, move paths or stage `.venv` symlink/generated scratch.

Evidence index: [current-receipt.json](t031-benchmark/native-build/current-receipt.json).
