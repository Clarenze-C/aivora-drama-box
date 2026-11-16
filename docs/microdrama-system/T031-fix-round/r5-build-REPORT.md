# T031 R5 build report (R5a–R5f)

R5: ALL PACKAGES DONE — all six packages committed, `make check` green at the final commit
(`6bcdbfa`: `make check: all offline checks passed`, 275 tests, 35m31s under CPUQuota). The single
remaining item is the environment-blocked RR-T3 local image rebuild (disk; code and tests done,
retried twice, see R5a below).

Builder: GLM (`feat/t031-r5`, base `104b26b`), 13–14 Nov 2026. Spec: `T031-run-readiness-spec.md` v0.3.

Status: ALL PACKAGES COMMITTED — R5a `2757e51` (+ `2e42540` schema regen), R5b `fab3e7e`, R5c `b6d3b48`,
R5d `5ec7a56`, R5e `2876466`, R5f `1eddc83`, plus two red-test-driven repair commits `3b5ea3f` (base
defects) and `6bcdbfa` (lint gate restored — two files shipped unformatted in `b6d3b48`, so `make
lint`/`make check` were failing at the R5c tip before any of this session's work). **One open blocker:
the RR-T3 local image rebuild (disk — retried this session, still refused, see R5a).**
`make check` at the final commit: see the bottom line of this report.

## Per-package status

| Package | Status | Commit | RR tests |
|---|---|---|---|
| R5a — image + gateway + flag through the composed request | code+tests green; RR-T3 rebuild STILL BLOCKED on disk | `2757e51` + `2e42540` | T1–T4 (T3 pending rebuild) |
| R5b — ready gate, boot failures, timings, staging bindings | committed (previous session; suites re-verified green this session) | `fab3e7e` | T5, T6, T13–T16 |
| R5c — prediction + seal evidence (one commit) | committed (previous session; suites re-verified green this session) | `b6d3b48` | T7, T8, T12 |
| Base repairs (pre-R5d, red-driven) | committed | `3b5ea3f` | unblocks T9/T12 |
| R5d — prepare-run tool | committed | `5ec7a56` | T9 (5 tests) |
| R5e — results tool | committed | `2876466` | T10 (3 tests) |
| R5f — per-pod billing verification | committed | `1eddc83` | T17 tool scope (3 tests) |

## R5a (previous session; blocker carried forward)

### Red lines (against base 104b26b)

- `tests/unit/pipeline/test_t031_r5a_flag.py` — collection ImportError (`validate_provision_intent` absent).
- `tests/unit/rendering/test_t031_r5a_start_sh.py` — 5 FAILED (no `start.sh`).
- `tests/unit/rendering/test_canary_gateway.py` (new ready tests) — 6 FAILED (no `/__drama/ready`).

### Green: 48 passed across the four R5a files; neighbors 119 passed; `make lint` green.

### Implementation: see the R5a commit message (`2757e51`) — start.sh entrypoint, both gateway copies
with `GET /__drama/ready`, flag plumbing through the composed create request, create guard
(intent ∧ composed request `True` before POST), Dockerfile/build.sh/test updates.

### BLOCKER — RR-T3 local image rebuild (disk) — STILL OPEN

`build.sh` requires ≥12GiB free; the root FS now has **5.4–5.5G free (98% used)** — worse than the 9.8G
at the first attempt (the concurrent SFW P5 builder's basetemp grew to 29G in /tmp). Not deletable
under this brief's rules. **Retried at the close-out point (14 Nov): refused again by the documented
floor** (`Need at least 12GiB free for code-only build`, 5.5G avail). Commands:

```
flock /tmp/t031-native-heavy.lock systemd-run --scope -p CPUQuota=45% --quiet \
  timeout 1200 bash ./build.sh /tmp/t031r5-buildctx
# -> "Need at least 12GiB free for code-only build"
```

No push (the operator pushes). **Resume: retry the rebuild when /tmp frees ≥7G more; then the RR-T3
receipt comparison against `1a6023e2…`.** Everything else in R5a is done and green.

## Base repairs (`3b5ea3f`) — red-test-driven, before R5d

Two defects in the accepted base made RR-T9 impossible as written; both were fixed with tests first:

1. **`_validate_model_rights` read a `payload` column `rights_registry` does not carry** (from the
   original `048cc05` snapshot; only the missing-pins refusal was ever tested, so the SQL never ran).
   Red: `MicrodramaError: column "payload" does not exist`. Fix: read the decision columns that exist
   and rebuild the exact stored form `RightsRegistry.record` fingerprints, so the sealed
   `model_rights_evidence_sha256` binds to the recorded decision content. Green: new registry-backed
   test + the full authorization suite (26 passed).
2. **Two pre-existing R5b regressions at `b6d3b48` (verified at that commit before any change):**
   `acquire()` gained the boot window + `wait_ready`, which KeyError'd on the minimal acquisition
   dicts the H-1 composition tests and R5a's own RR-T4 test pass, and requires the gateway ready
   surface the old refusing transports forbade (`test_benchmark_world_composition` 2 failed,
   `test_t031_r5a_flag::test_rr_t4_composed_path…` 1 failed at base). Repair: `ReadyServingComfyTransport`
   (GET /__drama/ready PROVISIONED + boot /object_info) and `experiment_id` in the dicts — each test's
   assertion set unchanged. Green: composition 3 passed, R5a flag 7 passed.

## R5d — `tools/t031_prepare_run.py` (`5ec7a56`)

### Red lines (against the WIP left by the previous session, recorded before the rewrite)

- All 5 RR-T9 tests: `MicrodramaError: column e.number does not exist` (the canary-spend query used a
  nonexistent episodes column).
- Focused base test: `column "payload" does not exist` (above).
- Latent, surfaced during the fix: wrong `PikaGraphConfig` import path; `RightsRecord(ELIGIBLE)` with
  `output_release_allowed=False` impossible; evidence sources `OPERATOR_ATTESTED`/`GENERATION_RECORD`
  not in the `EvidenceSource` enum; plan samples carried a forbidden `phase` key; the rights-evidence
  hash shape did not match `_validated_sources`; the runtime profile lacked the `model_rights_*` pins;
  the quote loader round-trip was a no-op stub.

### Green: 5/5 passed, including the end-to-end register → author → prepare → seal → quote → verify with
the REAL `ExperimentalPresetPolicy.validate` (no monkeypatch) — preflight PASS on the authored set.

### What the tool does

- **register** — episode + EPISODE account (cap $10.00; prior canary spend reported via the fixed
  `episode_number` query, never moved), METERED_MANAGEMENT allocation added for parity with the canary
  seed; 8 real assets (ACCEPTED/LIVE_PROVIDER; A2/B2 reused by two semantic bindings each; unpicked
  candidates never registered), 10 sealed bindings, 11 ELIGIBLE rights records, the disabled unmeasured
  preset, FILE credential validation (mode 0600/root; never content). Replay is idempotent and the
  named frozen-field drift gate refuses (asset bytes, state/provenance, rights/preset presence,
  credentials). `registered-bindings.json` carries the bindings + the model-output rights pins.
- **author** — plan/seal/authorization.draft with the frozen S05/S06 text, `<Picture N>/<Audio N>`
  port-map prompts, office-reuse + S08 home port map, PREDICTED seal binding the capture record
  (image digest cross-checked), runtime profile with preset pins + boot budget + provision flag +
  model-rights pins, rights-evidence hash in the exact `_validated_sources` shape. Prints per document
  the canonical sha the authorization binds (plan identity sha / sealed sha) plus the file-byte sha.
- **quote** — `AcquisitionQuote` validation + a real `load_document` round-trip; clean refusals.
- **verify** — `benchmark preflight` through the CLI (injected settings/DB, PAID env like the runbook)
  and prints PASS or the first refusal.

### Judgement calls

1. **Evidence sources for PAID-mode eligibility** (the enum has only FAKE_FIXTURE,
   OFFICIAL_DOCUMENTATION, CONTROLLED_ACCOUNT_TEST, MEASURED_BENCHMARK, LICENSE_DOCUMENT; PAID
   evaluation refuses records without a real one): model-output → LICENSE_DOCUMENT (the MiniMax H3
   Community License, operator-attested 12 Nov); voices → LICENSE_DOCUMENT with ref
   `botnoi-studio-v4:operator-attested-o11` (the O-11 attestation rides the ref — there is no
   OPERATOR_ATTESTATION enum value); reference PNGs → CONTROLLED_ACCOUNT_TEST (the Vertex/Nano Banana
   generation manifests on ARISA's controlled account).
2. **Model-output record `output_release_allowed=True`** — the RightsRecord contract makes True a
   precondition of ELIGIBLE; release here means the private benchmark's own use under the license.
3. **Plan samples drop the CSV `phase` column** — `BenchmarkSample` is extra=forbid; the screen set is
   already fixed by `screen_sample_ids`.
4. **The plan's printed canonical sha is `plan_sha256`** (the experiment-id-free identity the
   authorization binds), not the full-document sha; the seal prints `sealed_sha256`; the
   authorization prints its own canonical sha, while its FILE sha is what the operator signs.

## R5e — `tools/t031_results.py` (`2876466`)

Red: the exact-template test failed on the first run — the real template carries **eight** UNKNOWN
quality columns (thai_meaning..emotion) and a **blank** coverage_evidence, not nine UNKNOWNs.
Green: 3/3 passed, and the tool's all-NOT_RUN output was verified byte-for-byte against the
operator's real `docs/microdrama-system/t031-benchmark/results-template.csv` (25 rows identical;
that file is untracked, so the test ships a synthetic copy of the canonical header/body).
Mapping: ids/state/output sha/timings/cost filled; unknown numerics blank (never 0); the eight
quality dimensions UNKNOWN; coverage_evidence/accepted_retained_ms/failure_reason blank for the
human Pass A/Pass B; the per-sample columns the export does not carry (prompt/reference hashes,
actual_duration_ms, cold_start_ms — a per-acquisition record) stay blank; exports or templates off
the fixed 24-column shape are refused.

## R5f — `tools/t031_billing_verify.py` (`1eddc83`)

Red: first run hit the real verifier's own guard `Conflict: no completed billing query covers the
period after the settle lag` — correct behaviour, fixed on the TEST side by running the runbook's
step 14(a) first (the existing per-pod billing ingest recording one settled bucket).
Green: 3/3 — MATCH on the true sum (period evidence + budget finalizations through the real
BudgetService, only the evidence sha stored/printed), idempotent replay (`replayed: true`, one row),
loud MISMATCH (exit 1, period row only), refusals (no durable authorization / missing evidence /
empty period → exit 2). Thin by construction: `verify_invoice_period` unchanged, no migration, no
network. The admission half of RR-T17 (next acquisition refused while canonical billing/storage
blockers are uncleared) is H-2's own behaviour, covered by the H2B suites.

## `make check` at the final commit

First run at `1eddc83` FAILED at the lint gate — the two files shipped unformatted in `b6d3b48`
(pre-existing at the R5c tip; fixed in `6bcdbfa`). The clean-tree rerun at `6bcdbfa` under the
documented CPUQuota scope: **exit 0, `make check: all offline checks passed`** (contracts-check,
lint, unit, contract, integration — 275 passed in 35m31s, zero failures), including the 11 new
R5d/R5e/R5f tests and the repaired H-1/RR-T4 tests.

## Anything stopped at red

Nothing. The only open item is the environment-blocked RR-T3 image rebuild (disk above) — no code,
test or RR row was weakened to work around it. One stray untracked file `microdrama/preflight.json`
(a test artifact from the R5d verify run before `6bcdbfa` pinned `--output`) is left in the worktree
— this brief forbids deletion commands; discard it when convenient.

## Resume here

1. Retry the R5a local image rebuild when `/tmp` frees ≥7G (needs ≥12GiB; 5.5G free at the close-out
   retry): the flock command above; on success run the RR-T3 CPU attestation receipt comparison
   against `1a6023e24ad38cd4ef41e1d3b1c727550a52cba9cd055be2ede8373e487a4c89`; record digest +
   no-push evidence here. The operator pushes.
2. Codex review of `3b5ea3f..6bcdbfa` (R5d/R5e/R5f + base repairs); then the orchestrator's full gate.
