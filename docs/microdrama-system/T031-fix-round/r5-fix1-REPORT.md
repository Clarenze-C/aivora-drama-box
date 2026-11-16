# T031 R5 fix round 1 — the ten Codex review findings (R5V-1..R5V-10)

Builder: GLM (weekend runbook), 15 Nov 2026. Base `6bcdbfa`, branch `feat/t031-r5`, worktree
`/root/AIVORA/drama-box/.scratch/t031-r5`. Requirement source: `codex-review-r5.md` (the review wins
where this report's plan disagreed with it).

Commits (in order, all on top of `6bcdbfa`):

| Commit | Findings |
|---|---|
| `aa15705` | R5V-1, R5V-2, R5V-3, R5V-5, R5V-8 (world + service + contracts) |
| `e2ee07c` | R5V-4 (RR-T7 discovery test + capture-time check; pilot receipt; RR-T3 note) |
| `bf3b36a` | R5V-6, R5V-7 (tools) |
| `b465d5a` | R5V-9, R5V-10 (prepare_run) |
| `c02e918` | contract schema/example regen for `ProviderOperationResult.sampler_ms` (R5V-8) |

`make check` at the final commit: see "Final gate" below.

## Per-finding status

### R5V-1 — BLOCKING — completed boot timed out during resume — FIXED
`experimental_world.acquire()` now checks the persisted initial-readiness marker
(`cold_start_ms`) FIRST: once durable, the whole acquire path adopts the pod without any boot
deadline (no warmup loop, no request-deadline scope) — `wait_ready` returns on the same marker.
The minute-40 case is covered by a NEW test (`test_r5v1_existing_acquisition_past_boot_deadline_
resumes_without_reclassification`) that boots a GENUINELY EXISTING full-phase acquisition (durable
readiness, in-flight work, 2 h quote window so the lease is alive), advances 40 min past its boot
budget and drives it through real `resume`/`reconcile` to COMPUTE_COMPLETE.

- Red: the full acquisition got `incident {'phase': 'full', 'reason': 'BOOT_TIMEOUT', 'attempt': 2,
  'refused_at': '…00:40:04…'}` and a third create post.
- Green: `SCREEN_REVIEW→PASS→FULL_RUNNING→(40 min)→COMPUTE_COMPLETE`, no incident on any
  acquisition record, exactly one create for the full phase (2 total).
- The old minute-40 test (advance before creating the full pod) is unchanged and still green.

### R5V-2 — BLOCKING — deadline exhaustion made a pre-sample boot failure terminal — FIXED
- The boot request deadline now bounds the COMPLETE initial acquisition path: one
  `set_request_deadline` scope wraps the warmup loop, the post-ensure provider GET (endpoint bind)
  and the ready gate (`wait_ready`'s own equal deadline nests and restores it).
- The deadline is rechecked between requests (`_check_boot_deadline` before the ready poll, before
  `boot_object_info`, and after the warmup loop before the bind GET).
- A transport refusal at the deadline bound inside the window classifies as typed `BOOT_TIMEOUT`
  (`_classify_deadline_exhaustion` — only when the clock positively says the deadline passed;
  unrelated `EffectDenied` propagates unchanged).
- Red: `DeadlineBurningClient` (ready poll OK, first `/object_info` crosses the deadline and the
  transport refuses) → `execution_outcome == 'FAILED'` (the raw EffectDenied reached the generic
  terminal handler). Green: outcome NULL + incident `BOOT_TIMEOUT`.
- Red (post-ensure GET): the provider `get_pod` calls of the INITIAL boot acquire ran with
  `_REQUEST_DEADLINE == None` (outside the bound). Green: every initial-acquire GET runs inside the
  bound; later acquires (durable readiness — R5V-1) and cleanup GETs stay unbounded by design.

### R5V-3 — BLOCKING — persisted boot failure did not guarantee cleanup — FIXED
- `_record_boot_failure` persists the incident coverage AND the acquisition's incident state in ONE
  transaction under the acquisition row lock — an interruption can never leave the incident
  recorded without its cleanup obligation (or vice versa).
- `BOOT_FAILURE_STATES` (now `PROVISION_FAILED | BOOT_TIMEOUT | GATEWAY_REFUSED`, canonical tuple
  moved to `benchmark_experiments`) is recognized as cleanup owed: `unresolved_items()` emits a U2
  ("typed boot failure awaits verified cleanup") and `_needs_finalization()` returns True — the
  acquisition routes exclusively through cleanup until the sweep's verified transition closes it.
- Red (interruption/failed shutdown): with the sweep raising, `unresolved_items() == []` and
  `_needs_finalization() == False` (the review's exact probe), state stuck `PROVISION_FAILED` with a
  live lease. Green: U2 owed; a later PUBLIC `resume` drives the cleanup to verified and then
  admits the fresh attempt (gateway recovered; completes to SCREEN_REVIEW; first acquisition ends
  CLOSED/CLEANUP_PENDING).
- Red (atomicity): a crash injected between the two persistence writes left the coverage incident
  overwritten to BOOT_TIMEOUT while the state stayed PROVISION_FAILED. Green: the incident and the
  state can never disagree.

### R5V-4 — BLOCKING — acceptance evidence incomplete — PARTIALLY FIXED (one environment-blocked item)
- **RR-T7 rewritten**: `test_rr_t7_placeholders_populate_exactly_the_pinned_enums` no longer builds
  enums by appending manifest names (circular). It stages REAL zero-byte placeholders via
  `stage_placeholders` and runs a stand-in pinned-runtime schema smoke as a SUBPROCESS (the same
  folder-listing discovery ComfyUI's loaders perform); the capture record is built from the
  DISCOVERED payload, and the seal built from it passes `validate_for` end-to-end.
- **Capture-time check added**: `t031_schema_predict.capture_record` verifies the smoke's discovered
  enums against `models.json` per folder BEFORE producing a record — divergent discovery (one
  placeholder missing) can never yield seal evidence. Red-verified by neutralizing the check.
  Residual (documented, offline): the stand-in is not the pinned ComfyUI image itself — the real
  in-image placeholder smoke needs the pushed registry image (operator step, §7 step 4).
- **`make pilot` receipt at this HEAD** (RR-T11): `W01..W12 all OK / GREEN_WITH_UNKNOWNS /
  APPROVED (HUMAN)`, 16 media files exported, `out/pilot-demo/run-report.json`, settled 303000
  fake-µUSD, `pilot exit: 0` (log: `/tmp/t031r5-pilot-receipt2.log`; run twice — the first run's
  output was lost to a basetemp collision, the second is the receipt).
- **RR-T3 remains environment-blocked — operator item, per the brief**: the local rebuild needs
  ≥12 GiB free; the root FS now has ~1.2 G (worse than the 5.5 G at the R5 close-out), and the
  12 Nov local image (`abd32e9e…`) is no longer on the host, so the CPU attestation receipt
  comparison against `1a6023e2…` cannot run here. The brief explicitly forbids attempting it.
  Where the brief and the review disagree (the review says "complete … before accepting"), the
  brief wins on this item; acceptance of RR-T3 stays with the orchestrator.

### R5V-5 — SHOULD-FIX — readiness retried permanent HTTP failures — FIXED
`boot_failure_tolerated()` (comfy_transport) splits tolerated boot-read failures (connection layer —
`NeedsReconciliation`/`OSError` — and HTTP 404/502/503/524) from permanent ones (any other
`ProviderError` status, e.g. 401/403). `_read_ready` and the world's `_boot_object_info` wrapper
classify permanent failures IMMEDIATELY as a typed pre-sample `BootFailure("GATEWAY_REFUSED")`
(counted by the 3-attempt cap); the client's `boot_object_info()` re-raises them instead of
returning None. Red: a permanent 401 was retried as a paid wait — 150 ready reads over the full
25-min budget ending in BOOT_TIMEOUT. Green: ≤2 reads, incident `GATEWAY_REFUSED`, outcome NULL.
Tolerated 502s still keep waiting (regression guard, green both sides).

### R5V-6 — SHOULD-FIX — billing wrapper lacked acquisition provenance — FIXED
`t031_billing_verify` resolves experiment → target pod/lease → THE acquisition and ITS admission
`authorization_sha256` (never "latest") before the unchanged verifier. Red: a foreign experiment's
pod was billed through this experiment's account; a newer authorization with a rotated
`provider_account_ref` was picked and the verification refused on the wrong account's buckets.
Green: foreign pod refused ("not an acquisition pod of this experiment"); with a rotated newer
authorization present, the stored evidence row still bills the acquisition's ORIGINAL account
(MATCHED). The existing no-auth/missing-evidence/empty-period refusals kept (the empty-period arm
now reaches the verifier through its own acquisition-linked pod).

### R5V-7 — SHOULD-FIX — results repeated the whole bill per sample — FIXED
`t031_results` fills `billed_micro_usd` per row ONLY from that sample's allocated
`cost_micro_usd`; unallocated sample costs stay blank, and the experiment's aggregate is reported
separately as `billed_micro_usd_aggregate` in the summary. Red: all 24 rows carried the
experiment's 999,999 µUSD (2,962,944 µUSD fabricated). Green: only the allocated row shows its
123,456 µUSD; the aggregate is in the summary.

### R5V-8 — SHOULD-FIX — recovery permanently lost available timings — FIXED
- `_observe` looks the submission time up by the RESULT's verified operation id (recovery can
  observe with the sample's link still NULL — the review's `(None,)` lookup). Red: the recovered
  sample's `t031_timings` stayed `{}` forever. Green: `full_job_ms` written at the recovery
  observation.
- Sampler evidence now persists WITH the terminal completion: `ProviderOperationResult.sampler_ms`
  (additive optional contract field) rides the durable `last_result`; replayed terminal polls
  re-report it; and `finalize_terminal` (the delayed replay that projects the sample) recovers BOTH
  `full_job_ms` (created→terminal-record time, write-if-absent) and `sampler_ms` from the durable
  record. Red: crash between the terminal commit and the projection lost both. Green: the replay
  writes both (sampler 4321 recovered).
- No migration: the field lives in the existing `last_result` jsonb.

### R5V-9 — SHOULD-FIX — replay did not enforce the promised frozen fields — FIXED
The register replay gate now compares the NAMED frozen content per row type via the SAME
`_expected_*` helpers the author path constructs from: the episode account cap (one shared
`EPISODE_CAP_MICRO_USD`), exact asset fields per picked sha (kind/ACCEPTED/LIVE_PROVIDER — a decoy
wrong-kind row under a picked sha is refused), the exact rights identities/version/territories/
terms/evidence per route (a replacement CURRENT v2 with drifted content keeps the ELIGIBLE count
and is still refused), and the preset pins (version/workflow sha/enabled/rights route/record pins —
a replacement CURRENT preset row is refused). Red-verified with the checks neutralized: the
one-µUSD-cap probe, the wrong-kind row, the replacement rights v2 and the replacement preset row
all replayed "successfully"; after the fix each is refused.

### R5V-10 — SHOULD-FIX — real voice rows got fictional media metadata — FIXED
`_wav_media_info()` parses the RIFF/WAVE chunks of the actual bytes and refuses anything that is
not uncompressed PCM; the register path uses it for the voice descriptors. The tests write real
24 kHz mono PCM WAVs and assert the stored media (real per-file durations, `pcm_s16le`,
`has_video=False`); garbage and compressed-fmt inputs are refused. Red-verified: with the parser
bypassed (media=None) the duration/codec assertions fail; the old code's fixture metadata
(4,000 ms, h264/aac, 48 kHz stereo, `has_video=True`) is gone.

## Red/green summary (all red lines recorded against `6bcdbfa` before each fix)

| Test | Red | Green |
|---|---|---|
| r5v1 minute-40 existing acquisition | BOOT_TIMEOUT incident on attempt 2 + 3rd create | COMPUTE_COMPLETE, 2 creates, no incident |
| r5v2 budget exhausted in ready read | `execution_outcome == FAILED` (raw EffectDenied) | outcome NULL, incident BOOT_TIMEOUT |
| r5v2 post-ensure GET bound | initial-acquire GETs had `_REQUEST_DEADLINE=None` | all initial-acquire GETs bounded |
| r5v3 cleanup owed (sweep fails) | `unresolved_items()==[]`, `_needs_finalization()==False` | U2 owed; later resume cleans + admits |
| r5v3 atomic persistence | incident=BOOT_TIMEOUT vs state=PROVISION_FAILED | incident and state can never disagree |
| r5v5 permanent HTTP 401 | 150 paid reads → BOOT_TIMEOUT | ≤2 reads, GATEWAY_REFUSED, outcome NULL |
| r5v5 tolerated 502s | (guard) | keeps waiting, completes |
| r5v8 result-operation timing | `t031_timings == {}` after recovery | full_job_ms written |
| r5v8 sampler survives interruption | replay lost full_job_ms and sampler_ms | both recovered (4321) |
| r5v6 foreign pod | billed through the wrong experiment | refused |
| r5v6 rotated authorization | newest account picked → verifier refused on wrong buckets | original account billed, MATCHED |
| r5v7 per-sample bill | 24 × 999,999 µUSD | allocated-only + separate aggregate |
| r5v7/r5v9/r5v10 (neutralized-check reds) | 3 failed as designed | all green |
| rr_t7 discovery (check neutralized) | divergent discovery still produced a record | refused at capture time |

## Deviations / notes

1. **RR-T3 (R5V-4)** stays environment-blocked (disk ~1.2 G vs ≥12 GiB needed; pinned image absent
   from the host). The brief explicitly forbids attempting the rebuild — operator item; this report
   does not claim RR-T3.
2. **Pre-existing test-isolation quirk (not from this round)**: running
   `test_t031_h2b_p3_ambiguity.py` together with `test_t031_h2b_lf_luna.py` fails the luna L6
   parametrizations. Verified IDENTICAL on a pristine `6bcdbfa` tree extracted to /tmp
   (5 failed there too); each file passes alone, and the full `make check` unit run is green. No
   fix attempted (outside the ten findings).
3. **GATEWAY_REFUSED** is a new typed boot-failure state (counts toward the 3-attempt cap; no
   migration — `benchmark_acquisitions.state` carries no CHECK, as verified in the spec).
4. `ProviderOperationResult.sampler_ms` is an additive optional contract field (default None);
   no migration, no DB change.
5. Tests first per finding: every fix above was driven red against the base (or against the
   neutralized check where the base was structurally unable to express the new refusal), then
   green. No interactive pytest flags; real PostgreSQL everywhere the path touches the DB.

## Final gate

First `make check` run failed at `contracts-check` (the new `sampler_ms` field drifted the generated
contract artifacts) — fixed by `make contracts` + commit `c02e918` (104 schemas, 74 valid and 135
invalid examples; OK). Full `make check` re-run at `c02e918`: see the bottom line.

## Resume here

1. If `make check` is green: this round is done — hand to the orchestrator for the Codex re-review
   (re-review scope: the five commits `6bcdbfa..c02e918`).
2. RR-T3 (operator): retry the image rebuild when ≥12 GiB free (`flock /tmp/t031-native-heavy.lock
   systemd-run --scope -p CPUQuota=45% --quiet timeout 1200 bash ./build.sh /tmp/t031r5-buildctx`),
   then the CPU receipt comparison against `1a6023e2…`; then the REAL in-image placeholder smoke
   (the stand-in is covered; the pinned-image run needs the pushed digest).
3. The stray untracked `microdrama/preflight.json` (pre-existing test artifact) is still in the
   tree — this brief forbids deletion commands; discard when convenient.
