H2-BUILD: ALL PACKAGES DONE

# T031 H-2 build report (spec v3)

Builder: GLM-5.3 build session, 10 Nov 2026. Branch `feat/t031-fix3`, base `82135d4`.
Spec: `T031-H2-recovery-spec.md` (v3). Every package commits on top with its ATs green.

## Status

| Pkg | Sections | ATs | State | Commit |
|-----|----------|-----|-------|--------|
| P1 | §3, §8 | AT-4, AT-20, AT-23, AT-24 | **DONE** | `0bad31b` |
| P2 | §4 | AT-0, AT-5, AT-10, AT-11, AT-13, AT-14 | **DONE** | `67500b6` |
| P3 | §5 | AT-1, AT-2, AT-3, AT-15..AT-19, AT-25 | **DONE** (`3a5710d` part 2a + `45e4f2a` part 2b) | `45e4f2a` |
| P4 | §6 | AT-6, AT-7, AT-21, AT-26 | **DONE** | `941ab6d` |
| HBF | Codex P1–P3 review HB-1..HB-14 ([review](codex-review-h2-p1p3.md), [rulings](rulings-canary-night.md)) | **DONE** — HB-1..HB-12, HB-14 (`30d5e30`..`5790a45`), HB-13 (`9c28ac6`) | fixes, tests first | `9c28ac6` |
| LF | GLM Luna review L-1..L-7 ([review](glm-review-luna-REPORT.md)) | **DONE** — L-1+L-2 (`8810068`), L-3+L-4 (`3b63acd`), L-5+L-6+L-7 (`bdf1e2b`) | fixes, tests first | `bdf1e2b` |
| P5 | §7 | AT-8, AT-9, AT-12, AT-22 (+ §9.3: R7 matrix, R6 FAILED/CANCELLED/NOT_FOUND, R8) | **DONE** | `0e34630` |

## P1 — modes, provenance, EXPIRED reads (commit `0bad31b`)

### Red → green (pytest summary lines)

- Red (before implementation): `6 failed in 33.09s` — each for the missing
  implementation, after fixture-shape corrections only:
  - AT-24 `AssertionError: no world may be constructed for an empty experiment` (sweep composed a world with zero acquisitions);
  - AT-23 `KeyError: 'source_bytes'`;
  - AT-20 `ImportError: cannot import name 'expired_recovery_read_allowed'`;
  - AT-4[RECOVERY/CLEANUP] `TypeError: build_experiment_world() got an unexpected keyword argument 'mode'`;
  - AT-4 CLI `AssertionError: reconcile` (offline CLI reconcile exited 2).
- Green: `6 passed in 34.46s`
  (`tests/unit/rendering/test_t031_h2b_p1_modes.py`).
- Regression suites after P1: `31 passed in 70.45s`
  (test_benchmark_experiments + test_benchmark_world_composition +
  test_comfy_recover), `27 passed in 6.61s` (test_benchmark_authorization +
  test_live_world), `15 passed in 60.19s` (P1 suite + integration
  test_migrations). `ruff check`/`format` clean; contracts-check OK (2.16.0).

### What shipped

- 0026 edited in place (additive): `benchmark_authorizations.source_bytes`,
  `benchmark_acquisitions.authorization_sha256` (NOT NULL, 64-hex),
  `recovery_started_at` / `recovery_deadline`, gate indexes (acquisitions by
  experiment, reservation links by experiment, samples by reservation).
- `build_experiment_world(mode=...)` replaces `cleanup_only`; RECOVERY/CLEANUP
  load authorization/quote per acquisition from durable rows
  (`load_recovery_authorization` verifies sha256(bytes)==SHA and
  parse(bytes)==payload), refuse create/upload POST/prompt POST at the
  composition, request and transport layers; every mode requires a non-null
  store; `bind_for_recovery` (BOUND / VERIFIED_SOURCE_GONE / INDETERMINATE),
  never calls `ensure_pod`.
- `expired_recovery_read_allowed` (§3.3/R4) wired into the benchmark request
  guard; input readback (`/view?type=input`) permitted for RECOVERY/CLEANUP,
  upload POST refused outside EXECUTE.
- `execute(..., source_bytes=...)` persists exact bytes + byte SHA + parsed
  payload in one row; acquisitions record their authorization at admission;
  `resume` is recovery-first and returns `admission` blockers; `sweep` composes
  its CLEANUP world lazily; `reconcile` composes one RECOVERY world per
  acquisition; CLI builds the store for `reconcile`/`resolve` too.
- `comfy_jobs._settle_if_needed`: EXPIRED-with-exposure settles through the
  canonical settlement (SETTLED_AFTER_EXPIRY path), never reactivates/releases.

### Judgement calls (P1)

1. **`recovery_started_at`/`recovery_deadline` are not in the set-once
   trigger**: §5.4/R3 allows *shortening* the persisted deadline and SC2-2
   reuses it for later ambiguities, so set-once would forbid required writes.
2. **Stored payload = parse of the accepted bytes** (not the pydantic model
   dump): §3.2 says "the validated file's exact bytes, the byte SHA and the
   parsed payload"; a model dump would add default fields and break the
   recovery check parse(bytes)==payload. The reuse-conflict check compares
   parsed payloads (semantics), so different formatting of equal content is not
   a conflict. When a caller passes no bytes, the canonical serialization of
   the validated payload is stored (its SHA equals the model's
   `authorization_sha256`).
3. **One CLEANUP world per sweep call** (not per acquisition): cleanup performs
   no Comfy-bound call (no client rebinding concern); RECOVERY worlds — where
   the single-bound client matters — are composed per acquisition.
4. **Admission authorization fallback**: the executing run's validated SHA
   wins; an independently restarted admission (offline composed harness) falls
   back to the newest recorded provenance row. NOT NULL makes a row mandatory;
   the `prepare()` test helper records a synthetic-but-consistent provenance
   row for the offline `_advance` harness.
5. **Only `execute` hard-refuses flags in the CLI**; `resume` runs recovery
   first and reports blockers (§4.2 order). The `--cleanup-only` flag still
   means sweep-only.
6. **`ensure_pod` in a non-EXECUTE world still commits `create_requested_at`
   before the create refusal** — pre-existing canonical order (leases.py is not
   among the permitted canonical edits); the refusal is EffectDenied at the
   attestation/create-guard layers before any POST leaves the process, and
   recovery paths use `bind_for_recovery`, never `ensure_pod`. Recorded as a
   known wart, not a spec violation (I5 refuses the *effect*, which is refused).
7. **AT-20 final exposure**: after the canonical settlement of an
   EXPIRED-but-retained lease-covered prompt hold, the unused remainder is
   released (total drops by the former hold); expiry itself never discharges
   liability (asserted before settlement).
8. **Deadline blocker is seal-independent**: `_admission_blockers` reports
   "absolute experiment deadline expired" whenever hard_stop passed, even
   unsealed (an unsealed experiment also gets its own blocker).

## P2 — unresolved items and the admission gate (commit `67500b6`)

### Red → green (pytest summary lines)

Red baseline (committed file restored, tests only): `14 failed, 1 passed in 66.03s`
(`tests/unit/rendering/test_t031_h2b_p2_gate.py`). AT-11 was already green at
baseline — P1 had shipped §4.2's phase derivation; P2 adds the predication and
CLI ordering around it. Representative red causes:
- AT-0/AT-13-style: `ImportError: cannot import name 'unresolved_items'`;
- AT-10 (all kinds): `ImportError: cannot import name 'AdmissionBlocked'`;
- AT-5: `assert None is not None` (resume admitted generation 2 before finalization);
- AT-14-after-expiry: `Conflict: render attempt reservation is not ACTIVE`;
- cleanup fixture: stop-only evidence still counted as verified.
Green: `15 passed in 93.03s`; combined P1+P2+regression run
(test_t031_h2b_p2_gate + test_t031_h2b_p1_modes + test_benchmark_experiments +
test_benchmark_world_composition + test_comfy_recover + test_benchmark_authorization +
test_live_world): `79 passed in 180.78s`. `ruff check`/`format` clean;
`contracts-check` 2.16.0 OK.

### What shipped

- `benchmark_experiments.py`: `unresolved_items(tx, experiment_id, now)` (U1
  label-free; U2 incl. R1 storage debt, live no-create leases, SC2-2 deadline
  clause over derived ambiguity; U3/U3p through the fixed reservation incl.
  null `sample.operation_id`; U3u acquisition-scoped; U4 with
  projection/slot/settlement/output checks; U5 contradiction + pod/ownership
  finality; U6 for acquisitions and samples), `UnresolvedItem`, `blocking()`
  with the §4.1 R2 scope table, and
  `ExperimentBudgetService.settle_expired_unused_hold` (deterministic
  zero-charge settlement for an EXPIRED never-dispatched hold).
- `benchmark_service.py`: `AdmissionBlocked`; locked gates in `execute`
  (predicated state write per §4.2 — never from NEEDS_RECONCILIATION),
  `_acquisition` (fresh admission gated on every admission-blocking kind;
  U1/U5 also refuse the returned existing acquisition), `_claim_sample`
  (fresh claims gated; the occupied-slot return stays pollable), and dispatch
  gates before the create/upload/prompt sends (a fresh process never holds a
  first-send right — SC2-1). `_advance_owned` refuses AdmissionBlocked into a
  reconciliation status (never a spurious FAILED) and never acquires an
  acquisition awaiting finalization (AT-5). `resume` = reconcile (polls
  in-flight U3p work, reconciles U1 by predicate) → sweep only when U2 owes it
  → item/flag admission blockers → execute with the durable phase.
  `resolve_create` accepts the label-free U1 predicate; its NEEDS_RECONCILIATION
  → running shortcut write is removed (reconcile is the only writer). Sweep
  finalizes NO_CREATE_PROVEN rows (R1): canonical podless lease close, storage
  release or zero-settle. `_close_undispatchable_sample` implements the §F
  expired-claim closure.
- `benchmark.py` (CLI): resume defers new-generation argument validation —
  recovery runs first; unusable authorization/quote files/SHA mismatches
  become admission blockers on the recovered status; execute stays strict.
- Fixture: the two unconditional cleanup assertions restored (§9.1).

### Judgement calls (P2)

1. **U2 includes a live lease on a NO_CREATE_PROVEN acquisition** (not only
   R1 storage debt): the pilot single-live-lease index would otherwise block
   every later lease forever after a crash-before-handler create; the sweep
   closes it canonically (podless shutdown → RELEASED).
2. **reconcile polls in-flight (U3p) slot operations, not only UNKNOWN ones**:
   without the poll, resume deadlocks on its own admission gate (U3p blocks
   fresh admission until the existing work is recovered/finalized — §4.1 R2).
   Production RECOVERY worlds bind via `bind_for_recovery` before polling.
3. **`execute` refuses (raises AdmissionBlocked) when items block; `resume`
   returns the status with blockers.** A fresh process continues through
   resume (its reconcile polls first). The P1 `_drive_execute` harness gained
   a `_drive_resume` companion for continuation flows; the pre-existing
   operator-resolution test was updated to the §4.2 contract (resolve returns
   NEEDS_RECONCILIATION; sweep+reconcile clear it).
4. **Dispatch gates re-check in their own locked transactions before each
   send** (create/upload/prompt); the original invocation passes them because
   its own intents are committed inside the send calls themselves (intent →
   POST in one canonical call), so no explicit first-send token plumbing is
   needed at the benchmark layer (SC2-1's right is realized by the durable
   intent-before-send pattern + reconciliation-only replays).
5. **U6/U2 scope exceptions asserted, not worked around**: AT-10 documents
   that U6 never blocks other work and U2 does not block claims (§4.1), per
   the spec's scope table rather than the AT's "each of U1–U6 refuses" phrasing.
6. **The first-send takeover waits for coordinator-token expiry** (§E): a
   SIGKILLed worker's token persists (its finally never ran); AT-13 advances
   past the one-hour lease instead of preempting a valid coordinator.
7. **`settle_expired_unused_hold` lives on ExperimentBudgetService** (not
   ComfyRenderService): it is benchmark-owned, additive, and avoids touching
   the canonical comfy service; EXPIRED-only, idempotent, deterministic
   receipt id; never a release (I4).
8. **Fixture strictness restored as the two unconditional assertions**
   (`result.compute_stopped`, durable stop/terminate timestamp for pod-bound
   cleanups) after checking the pre-H-2 fixture: the original strictness was
   the asserts, not a terminate-only rule. An intermediate approach that
   swapped the composed fixtures to a runpod-addressed fake was REVERTED: it
   broke the canonical runpod release rule (offline tests cannot do runpod
   invoice finality) and double-counted exposure in AT-20.
9. **AT-13's parent process loads the authorization from the durable
   provenance row the acquisition recorded** (§3.2), uses the child's durable
   clock, and random ids (UuidIds) — the child's deterministic id sequence
   died with it; replays stay idempotent by semantic key.
10. **`_admission_blockers` still reports flag-level blockers separately**;
    item blockers are prefixed with their kind (`U1(...): ...`) so operators
    see which reconciliation is owed.

## P3 (part 1) — §5.1 classification, §5.2 takeover, grace persistence (commit `2ec18f8`, WIP)

### Red → green

Red baseline (tests only, before implementation): `5 failed in 14.50s`
(`tests/unit/rendering/test_t031_h2b_p3_ambiguity.py`). Green:
`5 passed in 23.11s`. Combined P1+P2+P3+regression run
(+ test_comfy_recover): `54 passed in 208.56s`. `ruff check`/`format` clean.

### What shipped

- §5.1 classification split: create ambiguity → acquisition UNKNOWN + sweep
  (no grace); upload ambiguity → intent stays open (U3u), no prompt op
  invented, pod stays for the readback; submit/poll ambiguity → acquisition
  stays ACTIVE, `NEEDS_RECONCILIATION` in the same transaction, pod stays.
- §5.4 persistence: `RECOVERY_GRACE_MAX_S = 600`; `recovery_started_at` set
  once; `recovery_deadline` = earliest of (first ambiguity + 600s,
  hard stop − shutdown margin, funded-work deadline (compute hold expiry −
  margin), aggregate GPU deadline (now + remaining GPU ms)); takeovers reuse
  and may only shorten (SC2-2).
- §5.2 takeover: coordinator token gone/expired → PENDING_SUBMIT (no refusal)
  becomes UNKNOWN under the operation lock
  (`ComfyRenderService.mark_operation_unknown`, additive); a live coordinator
  is never preempted. The deterministic client-id finder (fake + transport)
  now raises Conflict on more than one match — never adopts the first.
- reconcile polls in-flight/pending slot work after a best-effort
  `bind_for_recovery`; NeedsReconciliation/EffectDenied/Conflict leave the
  item blocked (nothing adopted, nothing re-sent).
- `resolve_sample` sets the §7.4 fail-fast outcome on FAILED.

### Judgement calls (P3 part 1)

1. The residual (unclassified) NeedsReconciliation handler keeps the
   conservative create treatment (label + sweep) — new call sites fail safe.
2. Pre-existing tests updated to the spec contract: the operator-resolved
   unfindable prompt now FAILS the experiment (§7.4 through the operator
   path); AT-20 sweeps after the resolution (the pod now survives the
   ambiguity per §5.1, so its compute accrues until cleanup) and asserts the
   exposure structurally (zero open remainder, prompt settled at zero, total
   == accrued+settled compute).
3. Binding before a recovery poll is best-effort: a world whose poll cannot
   authenticate refuses inside the tolerant try and leaves the item blocked
   (offline adapters need no binding; production RECOVERY worlds bind via
   §3.4).

### Still open in P3 (next resume)

- AT-3 (worker SIGKILL mid-poll, pod alive: CLI reconcile → BOUND, output into
  the CLI-built store, zero POSTs).
- AT-17 native upload readback (§5.3 through `stage`/`readback` on a real
  composed world) + §9.3 extensions for AT-16/17/20 (acquisition-scoped
  upload blockers, EXPIRED input readback with no prompt op (R4),
  wrong-owner/wrong-mode/POST refusals, U3p missing-linkage block).

## P3 part 2a — R3 deadline fence, grace mechanics (commit `3a5710d`)

### Red → green

Red baseline (tests only, committed sources restored via `git show HEAD:`):
`test_at18… 1 failed in 8.13s` (no bounded nested request — reconcile set no
deadline context), `test_at18b… 1 failed in 12.98s` (no immediate cleanup at
the reused elapsed deadline), `test_at19… 1 failed in 11.52s` (still-valid
coordinator token never revoked), `test_at02… 1 failed in 8.83s` (pod not
stopped at `recovery_deadline`). Green: `9 passed in 36.36s` (whole P3 file);
P1+P2+P3 `30 passed in 142.87s`; regression `53 passed in 71.42s`
(benchmark_experiments, comfy_recover, world_composition, authorization);
`ruff check`/`format` clean.

### What shipped

- **R3 deadline fence**: `sweep` → `_deadline_fence` commits, under the §6.1
  order (account→categories→E→A→gate rows), the revocation of the
  acquisition coordinator token and the dispatch-slot token when
  `recovery_deadline` has passed with a U1/U3/U3u ambiguity on that
  acquisition; cleanup then runs outside the transaction. The fence bites
  only while an ambiguity is unresolved (SC2-2: a historical deadline never
  fences healthy work).
- **Token-predicated control writes**: the dispatch gates (before each of
  create/upload/prompt), `_claim_sample`, the acquisition-token takeover and
  the `state='ACTIVE'` write, and `_observe` (coordinator callers only) all
  re-check both durable tokens in their own transactions and refuse with
  `AdmissionBlocked` when fenced — a stale coordinator neither projects nor
  dispatches, and the experiment is never spuriously failed.
- **SC2-2 immediate cleanup**: `_mark_submit_ambiguity` sweeps when the
  persisted (reused) deadline is already in the past.
- **Grace mechanics**: reconcile heartbeats the owned lease during grace
  (`heartbeat_at` only — nothing is extended) and wraps every nested recovery
  request (poll, client-id finder scan, upload readback) in
  `set_request_deadline(recovery_deadline)`/`reset`.
- **§5.3 plumbing**: `_SealedNativeInputs.readback` (checksum-verified
  `/view?type=input` per open intent through the real client scope; no POST,
  no invented intent) wired as `world.reconcile_uploads`; `reconcile`
  attempts it per U3u acquisition after best-effort `bind_for_recovery`,
  leaving the item blocked on refusal; `NEEDS_RECONCILIATION` no longer
  clears while an upload intent is open.

### Judgement calls (P3 part 2a)

1. **Fence refusal is `AdmissionBlocked`, not `Conflict`**: the coordinator
   was fenced, nothing was written; returning the status with R3-fence
   blockers matches the existing gate-refusal flow and avoids the
   `except BaseException` path that would spuriously fail the experiment.
   The comfy-level submit-result write is canonical suffix-only (P4 owns its
   ordering); the fence's promise is discharged at the benchmark layer.
2. **No new fence-marker column** (§8 lists none): the fence revokes the two
   tokens; "prevent further execution" is enforced by the token predicates
   (stale coordinators) plus the U2 deadline clause (new coordinators — U2
   blocks dispatch on that acquisition while the ambiguity is unresolved).
3. **Nested-request bounding observed at the production boundary**: the fake
   Comfy client has no transport, so the probe consults the production
   `bound_request_timeout` at the same client methods the real transport
   serves (finder /queue+/history scans, /history polls). The real
   UrllibTransport's honoring of the same context is already covered by the
   CN-6 tests (`test_comfy_transport.py`, `test_diagnostics.py`).
4. **AT-19's stalled coordinator is a thread parked mid-submit** (after
   server acceptance): real SIGKILL-persistence of the token is AT-13/AT-3's
   ground; the thread models the coordinator that returns. The janitor sweep
   fences it while parked; the parked prompt's send was authorised before
   the fence, so its positively-known outcome is later adopted by a FRESH
   takeover (never resubmitted) — revoking a token never proves an
   authorised send did not happen (I2).
5. **Offline cleanup evidence**: the composed world's verified cleanup is a
   verified stop (`stop_verified_at`) — termination is the janitor's separate
   verify step — so AT-18/18b/19/2 assert stop-or-terminate evidence, and
   AT-2 asserts full closure through `resolve_sample` + sweep
   (VERIFIED/BILLED).
6. **AT-2 "no state write" is asserted as full durable-row identity**
   (experiments/acquisitions/samples/operations snapshots equal before and
   after the fresh resume): the sweep's idempotent same-value
   `cleanup_state`/`billing_state` UPDATE stays allowed; zero sends.
7. **Screen sample ids** are `S01-R1`, `S03-R1`, `S07-R1` (`SCREEN_IDS`), not
   sequential — the tests query the right rows.

**Resume here: P3 part 2b — AT-3 (subprocess CLI reconcile death test) and
AT-17 (native upload readback + §9.3 extensions), then P4. Committed through
`3a5710d`; tree clean.**

## P3 part 2b — AT-3 subprocess death test, AT-17 native upload readback (commit `45e4f2a`)

### Red → green

The stopped session left AT-3's test uncommitted (tests only, no sources). Kept
after review against the spec; the red runs below are against committed HEAD
sources throughout.

- AT-3 red: `1 failed in 15.08s` (the inherited child drove a single `execute()`
  — a dispatch step submits and returns without polling, so the mid-poll death
  never fired; marker absent). After driving step 2+ through public `resume()`
  (whose reconcile polls the in-flight U3p operation): `1 failed in 36.24s`
  (`AdmissionBlocked: U3p ... in flight` — the resume-vs-execute gate), then
  `1 failed in 14.47s` (durable op was RUNNING, not SUBMITTED — the death lands
  after the progress observation, before the terminal one), then
  `1 failed in 15.11s` (`bind_for_recovery` = INDETERMINATE — the parent's fresh
  fake provider did not know the child's pod), then `1 failed in 13.72s`
  (CLI refused: `MICRODRAMA_DATABASE_URL is required` — settings lacked the
  DSN). Green: `1 passed in 16.19s`; whole P3 file `15 passed in 58.63s`.
- AT-17 red (first drive of the real composed native-inputs world): fixture
  imports failed first (`ImportError: cannot import name 'document_sha256'`,
  missing V2Record envelope fields, chmod/credential and plan-shot shape
  fixes — fixture only), then two **implementation-level** reds against
  committed sources: `KeyError: 'recorded_at'` in `_rights_resolver` (the
  column does not exist; every real rights row crashed the resolver) and
  `NotFound: current PromptManifest not found` in `submit_v2` (the native
  manifest was never persisted to the v2 ledger). Both fixed (see below);
  the graph then validated against the captured real runtime schema fixture.
  Green: main test `1 passed in 12.19s`; the three extensions
  (`3 passed in 12.39s`); AT-16b `1 passed in 8.69s`.
- Regressions after P3 complete: P1+P2 `21 passed in 115.44s`; benchmark
  suites (experiments, world_composition, comfy_recover, authorization)
  `53 passed in 72.80s`; v2_comfy_submit + pika_h3_flex + live_world
  `30 passed in 14.58s`; whole P3 file `15 passed in 55.89s`.
  `ruff check`/`format` clean; `contracts-check` 2.16.0 OK.

### What shipped

- **AT-3**: the child subprocess runs the real composed execute path; the
  dying client `os._exit(86)`s inside the first `history()` poll of the
  completed prompt (after the progress observation committed RUNNING), having
  first serialized the fake server state (prompts, submissions counter,
  registered outputs, clock) to disk. The parent rebuilds the killed worker's
  pod in its fresh fake provider **from the durable lease row** (pod id,
  client token, create instant; the fake endpoint URL derives from the pod id
  exactly as `create_pod` does), restores the server from the snapshot, and
  asserts: `bind_for_recovery` = BOUND; CLI `reconcile` (with a CLI-built
  store) returns the sample SUCCEEDED with the output object in the store and
  its sha256 durable; ZERO new submissions.
- **AT-17** on a real composed world (`build_experiment_world`, EXECUTE mode,
  real `PikaHttpClient`, scripted Runpod/ComfyUI transports; real canonical
  assets — PNGs + PCM WAV — with WORLDWIDE ELIGIBLE rights rows; a sealed
  4-port port_map; the captured real runtime schema): every input upload POST
  is accepted then times out. Assertions: the ambiguity classifies as upload
  (U3u), no prompt operation is invented; recovery readbacks verify all four
  intents (checksum + durable `verified_readback_sha256`); exactly four
  upload POSTs and one prompt POST ever; dispatch continues to SUBMITTED.
- **§9.3 extensions**: unverifiable readback (corrupt bytes) keeps U3u
  blocking claims/dispatch across fresh resumes (blocker named, no second
  POST, no prompt); EXPIRED-hold input readback succeeds in RECOVERY through
  the upload-intent linkage with no prompt op (R4) and never re-POSTs;
  wrong-owner scope and wrong-mode (RECOVERY upload POST / prompt POST)
  refusals land at the request guard before any transport call; AT-16b:
  in-flight operation with missing sample linkage blocks fresh
  `execute` admission with a U3p blocker.
- **Production fixes the real path exposed** (both in
  `experimental_world.py`): `_rights_resolver` now reads the
  `rights_registry.created_at` column for `RightsRecord.recorded_at` (the
  `recorded_at` column never existed — any real rights row crashed every
  native dispatch); `_SealedNativeInputs.manifest` persists its sealed
  PromptManifest to `v2_contract_documents` idempotently by record id (the
  manifest derives entirely from frozen inputs, so a replay rebuilds the
  identical payload and only the first build writes — I6; `submit_v2` loads
  and verifies exactly that row).

### Judgement calls (P3 part 2b)

1. **AT-3's child drives step 2+ through `resume()`, not repeated
   `execute()`**: a fresh `execute()` is correctly refused by the U3p
   admission gate while the first prompt is in flight (§4.1 R2); the worker's
   own continuation in this harness is resume — whose reconcile polls the
   in-flight operation first. That poll is the mid-poll death window.
2. **AT-3 asserts the durable operation is SUBMITTED *or* RUNNING**: the
   death deterministically lands after the progress observation (RUNNING
   committed) and inside the history call; the spec requires "killed
   mid-poll", not a particular in-flight state. The outcome itself is never
   observed or projected (asserted).
3. **The parent re-seeds the child's pod into its fresh fake provider from
   the durable lease row** (pod id, client token, create instant; endpoint
   derived as `create_pod` derives it): the pod is provider-side state that
   outlives the worker, exactly like the on-disk server snapshot. No pod
   detail is invented that is not durable.
4. **AT-17's transport times out EVERY upload POST after acceptance**: 4
   intents → exactly 4 POSTs ever is the sharpest form of "never a second
   upload for the same intent" (later stage passes find durable rows and are
   read-back-only by construction).
5. **The preset policy is patched to return a REAL disabled, unmeasured
   `PresetRecord`** (pinned to the actual `pika-h3-flex-ref2va-benchmark-v1`
   template): the AT drives the native upload/prompt mechanics, not the
   preset-catalog eligibility layers (preflight suites own those), and a
   None-returning patch would crash `native.request()` which needs the
   record's controls/tier.
6. **The pod-side ComfyUI serves the captured real runtime schema fixture**
   (`pika_h3_flex_object_info_OFFLINE_FIXTURE_ONLY.json`); the seal pins its
   mapped sha. The minimal `schema_fixture()` declares UI-only `value`
   inputs the real graph never sends and cannot pass `validate_api_graph`.
7. **`PromptManifest` persistence lives in `manifest()`** (not in
   `request()`/`submit_v2`): `request`, `bind` and `submit_v2` all derive
   from the same sealed record; persisting at the single construction point
   keeps every caller consistent and the write idempotent by record id.
8. **The manifest insert is guarded by an existence check, not ON CONFLICT**:
   the ledger's unique key spans (contract_type, record_id, version) with a
   `current` flag; the check-then-insert under the dispatch slot's single
   coordinator cannot race itself, and a replay writes nothing (I6).

**Resume here: P4 — §6 (shared lock order with R5, billing-wrapper reorder,
`resolve_create` with SC2-3 replay, storage release only at sweep with R1,
contradiction incident path; AT-6, AT-7, AT-21, AT-26 + the §9.3 extensions).
Committed through `45e4f2a`; tree clean.**

## P4 — lock order, create resolution, storage finalization, incident path (commit `941ab6d`)

### Red → green

- AT-6 red (tests written first, against committed HEAD sources; the fixture
  matured through `BudgetService`→`ExperimentBudgetService`, runpod-addressed
  holds like P2's AT-13, admission-before-labelling ordering, and https pod
  endpoints): the first implementation-level red is
  `AssertionError: assert 'RELEASED' == 'ACTIVE'` — `resolve_create` released
  the STORAGE hold (`1 failed in 8.93s`). The R1 admission block was then
  observed on `execute` (resume auto-sweeps owed U2 cleanup by §4.2, so the
  gate itself is the refusing path). Green: `5 passed in 17.47s` (whole file,
  includes AT-7 + AT-21).
- AT-7 red: `'U5' in ['U3p']` — no U5 after the late adoption: the janitor's
  live-lease stray-attach path never contradicted a resolution, and `gpu_ms`
  excluded NO_CREATE_PROVEN rows entirely.
- AT-21 (races) was written against the implemented order; the
  wrapper-vs-resolve race is deadlock-free BY the new account-first order (the
  pre-P4 wrapper took advisory+L first — the test's blocked-then-proceeds
  assertion is the ordered proof; no counterfactual run was made).
- AT-26: canary + canonical suites after the billing-wrapper change —
  `test_t045_billing_ingestion` + `test_t045_finality_port` +
  `test_canary_gateway` `62 passed in 51.12s`; `test_t045_live_world` +
  `test_live_world` `12 passed in 8.40s`; `test_t045_canary_db` +
  `test_t045_canary_runner` + `test_t045_timing` + `test_t045_quote_attestation`
  `63 passed in 18.80s`.
- Regressions after P4: P1+P2+P3 `36 passed in 156.37s`; lease/claim/shutdown/
  storage-ownership/billing-ingestion `73 passed in 53.84s`; benchmark
  experiments + world composition + canary db/runner + timing + comfy_recover
  `81 passed in 81.57s`. `ruff check`/`format` clean; `contracts-check`
  2.16.0 OK.

### What shipped

- **§6.1/R5**: `BillingRepository.resolve_podless_create` wrapper now takes
  account and categories BEFORE its advisory lock and L (the permitted
  canonical edit), with the core exposed as `resolve_podless_create_in_tx`
  for callers holding locks 1-5. `_observe` locks D before S. The ambiguity
  markers take account→categories→E (E before the A write). `_acquisition`
  locks every prior lease of the experiment (by id) before evaluating U1/U5
  (Q3). Gate decisions (`_lock_gate_rows`) lock the acquisition ownership rows
  FIRST (then D, R, O, uploads), and `_SealedNativeInputs.stage`'s intent
  INSERT/UNKNOWN writes take the acquisition row lock — an intent cannot race
  past a gate decision (R5). The transaction-inventory module docstring lists
  every touched transaction with its locks and writes, distinguishing the
  canonical suffix-only transactions from the full-order benchmark ones.
- **§6.2**: `resolve_create` is ONE transaction in the shared order. SC2-3
  replay first (identical actor/reason/evidence on an uncontradicted podless
  resolution → success with no new audit or settlement, before and after the
  sweep; different attestation / bound pod / contradicted → Conflict).
  Preconditions under lock; `resolve_podless_create_in_tx` inside; the
  NO_CREATE_PROVEN + window-end write; **no storage release**.
- **§6.3**: the sweep's NO_CREATE_PROVEN finalization is one locked
  transaction that re-checks under lock (state, contradiction, verified
  termination + closed ownership for the contradicted case, live lease) and is
  the only place the STORAGE hold is released. The contradicted branch is
  terminal-lease aware: on a terminal lease the discovered pod's
  stop→terminate→verify tail is the janitor's (`terminate_terminal_pod`
  retry); the sweep finalizes only against the durable verified termination.
- **§6.4**: the janitor contradicts the resolution in the same L-locked
  transaction on BOTH discovery paths (stray attach + terminal adoption). A
  live-lease discovery routes through the late-adoption tail so its late cost
  posts as ADJUSTMENT receipts — `record_gpu_interval` states ACCRUAL as
  ADJUSTMENT on a closed reservation and `settle_from_recorded_usage` does the
  same for its SETTLEMENT (amounts unchanged; the ledger's own rule).
  `gpu_ms` includes contradicted acquisitions from the original
  `create_intent_at` through the discovered pod's verified termination
  (never the disproved window end; no new allowance at discovery). U5's detail
  names the contradicted attestation's actor and evidence hash (the §6.4
  status/export incident record).
- **AT-6/AT-7/AT-21 tests**: runpod-addressed U1 fixture with linked
  COMPUTE+STORAGE holds; the janitor boundary matrix with an injected
  mid-adoption janitor death (§9.3-style: a non-Microdrama error escaping
  every handler) to hold the U5 window open; AT-7 proves no partial-index
  collision for the newer generation, U5 blocking dispatch after the late
  adoption, GPU accounting from the original intent, and cleanup+replay
  clearing; AT-21 drives two-connection barrier races with bounded
  `lock_timeout` (wrapper vs resolve_create blocks-then-proceeds; admission/
  sweep/reconcile serialize behind E with no deadlock and no dispatch while
  U1 holds; gate serialization with an initially-absent upload intent through
  the acquisition ownership row).

### Judgement calls (P4)

1. **The R1 admission block is asserted on `execute`, not `resume`**: §4.2's
   resume order sweeps owed U2 cleanup first, so resume CONVERGES by
   finalizing; the gate that must refuse mid-window is execute's admission
   gate (and `_acquisition`). The AT extension's "admission stays blocked
   until STORAGE finalization" is the gate behavior, not a resume freeze.
2. **The janitor contradiction on the stray-attach path**: §6.4 says the late
   adoption "already" binds+contradicts; the live-lease stray path only bound.
   The contradiction write was added in the same L-locked transaction, and a
   stray WITH an existing resolution routes through `_adopt_late_pod`'s tail —
   the ordinary clean would accrue/settle on the already-settled hold
   (restatement), which the ledger forbids.
3. **ACCRUAL/SETTLEMENT → ADJUSTMENT restatement on closed reservations**
   (budget service + `settle_from_recorded_usage`): the ledger's own rule
   ("only ADJUSTMENT may follow a close") applied at the two choke points the
   offline incident path hits; the janitor's own docstring prescribes exactly
   this for late cost. Amounts unchanged; a canonical edit beyond the three
   listed ones, recorded here for the reviewer — without it §6.4's incident
   path cannot bill the discovered pod at all offline.
4. **U5's unfinalized window is created by an injected janitor death**: the
   fake provider escalates any stop failure to a successful terminate, so a
   "discovered but unfinalized" pod cannot be produced by scenario knobs; the
   §9.3-style injected death (TimeoutError escaping `_adopt_late_pod` after
   its bind+contradict transaction committed) produces exactly the durable
   shape the spec describes, and the janitor's real retry tail finishes it.
5. **AT-7 pins `provider_account_ref` on lease+config for the janitor retry**:
   CR-9's own-account filter (`= NULL` never matches) — the mock config leaves
   it NULL; the fixture pins a synthetic ref on both sides rather than
   touching the canonical filter.
6. **The sweep's contradicted branch no longer calls `world.cleanup` on a
   terminal lease**: `LeaseService.shutdown` on a RELEASED lease replays
   without stopping anything, so the offline §9.1 fixture would fail loudly
   (correctly); the pod's tail belongs to the janitor on terminal leases, and
   the sweep finalizes against the durable verified termination (I4: provider
   failure may delay verified termination, never declare it).
7. **AT-21's wrapper race asserts ordered blocking, not a counterfactual
   deadlock**: proving the OLD order deadlocks would require reverting the
   wrapper; the blocked-then-proceeds assertion plus the shared order is the
   spec's requirement (no deadlock under the built order).

**Resume here: P5 — §7 (`finalize_terminal`, mapping, monotonic projection,
R6 atomic fail-fast, operator resolution with R7/R8; AT-8, AT-9, AT-12,
AT-22 + the §9.3 extensions). Committed through `941ab6d`; tree clean.**
(Superseded by the orchestrator's 10 Nov ~17:00Z update: finish HBF
(HB-13 remains), then LF (L-1..L-7), then P5.)

## HBF — Codex P1–P3 review fixes, HB-1..HB-14 (commits `30d5e30`..`5790a45`)

Every fix landed tests-first (red summary lines from the commit messages;
the working tree was green after each commit — whole-file runs cited per
commit). Findings and rulings: [review](codex-review-h2-p1p3.md),
[rulings](rulings-canary-night.md).

| Fix | Commit | What shipped (from the commit) | Red → green |
|-----|--------|-------------------------------|-------------|
| HB-1 | `30d5e30` | EXPIRED reservations settle through the canonical calculation: independently charged execution settles at measured seconds × configured price (SETTLED_AFTER_EXPIRY closes retained exposure); only lease-covered attempts and positively-unused holds settle at zero; `retry_reuses_hold` no longer defers EXPIRED holds. Also defuses the AT-17 fixture time bomb (pika preflight binds at max(world clock, real now) — seal window now 365 days, test-only). | `assert 0 == 151000` (604 GPU-seconds zero-settled) → 16 passed test_comfy_recover, 15 passed p3, 47 passed p1+t045_billing_ingestion |
| HB-2 | `8dbded3` | `_reconcile_slot_sample` binds the owning acquisition's durable pod BEFORE both the UNKNOWN client-id lookup and the known-id poll, handling §3.4 explicitly (only BOUND reconciles; VERIFIED_SOURCE_GONE/INDETERMINATE stay blocked). `bind_for_recovery` returns BOUND only for a RUNNING pod with an endpoint. Fresh-real-client tests (AT-17 machinery refactored so server state outlives each client): AT-1 acceptance-window recovery binds+adopts+persists with zero resubmits; AT-15 (a)/(b) PENDING_SUBMIT takeover through a fresh real client; §3.4 STOPPED ≠ BOUND. | 3 failed at HEAD (at1/at15 shapes) → green |
| HB-3 | `967593b` | RECOVERY/CLEANUP worlds always load the named acquisition's OWN durable authorization and quote (byte-verified `load_recovery_authorization`/`load_recovery_quote`); caller-supplied documents never replace them; latest-by-timestamp fallbacks removed (an experiment WITH acquisitions refuses an acquisition-less recovery world). Slot reconcile derives the acquisition from the recovered sample; `resolve_sample`'s CLEANUP world names the sample's acquisition; the sweep composes ONE CLEANUP world PER acquisition (§3.1). World exposes `.authorization/.quote/.acquisition_id`. | the supplied later authorization (different namespace) was accepted at HEAD → green |
| HB-4 | `ac3179e` | The §5.4 grace heartbeat and nested request bound apply ONLY while an ambiguity is unresolved (UNKNOWN incl. just-taken-over PENDING_SUBMIT); a healthy SUBMITTED/RUNNING poll after an earlier recovered episode is never bounded by the historical deadline. The scripted AT-17 transport honors `bound_request_timeout` exactly like UrllibTransport (what made the stall reproducible offline). | the healthy S03 poll stalled SUBMITTED forever at HEAD → 21 passed (P3), 21 passed (p1+p2) |
| HB-5 | `72c524c` | Takeover-discovered ambiguity enters the durable grace at BOTH discovery points (PENDING_SUBMIT takeover with SC2-2 immediate-cleanup routing; failed recovery observation classifies as §5.1 poll ambiguity — UNKNOWN under the lock, durable prompt id kept). Reconcile routes an owed U2 to the sweep's R3 fence + cleanup. `_mark_unknown` preserves external_id. Scripted AT-17 transports gain the pod lifecycle (pod leaves RUNNING; the pod-side server dies with its pod). at15/hb5 takeovers expire the coordinator token in-window via SQL. | `recovery_started_at` stayed NULL after takeover → 22 passed (P3), 45 passed (p1+p2+p4+comfy_recover) |
| HB-6 | `59da542` | `_effective_recovery_deadline` computes the grace from the EFFECTIVE limits — tighter of plan row and the acquisition's accepted authorization (hard stop, aggregate GPU limit from its own durable provenance) — with the funded window's shutdown allowance excluded and the aggregate GPU deadline RESERVING shutdown GPU time. The R3 fence re-evaluates the bound UNDER its locks and shortens (shorten-only) when liability discovered since persistence exhausted the allowance. `_composed_world` gains `plan_changes`. | both deadlines 600+ s off at HEAD → 24 passed (P3), 30 (P3+P1), 23 (p2+p4) |
| HB-7 | `b2ac4a6` | Exclusive first-send right (SC2-1): `_assert_coordination` requires BOTH durable tokens to MATCH and their ownership leases LIVE; `_observe`'s projection predicate routes through the same check. At the comfy layer `_submit_bound_graph` consumes the right ATOMICALLY with the intent's creation (one append-only `first_send_claimed` event under the operation lock, same transaction as begin) — only the claimer may POST; every later caller raises NeedsReconciliation and never sends (I1). | DID NOT RAISE (the overlap POSTed) and permitted=True (stale projection accepted) → green |
| HB-8 | `c239efb` | The new-coordinator transaction takes account → categories → E → A → D (the fence's own order; was D-first — the exact cycle). Taking coordination asserts the SLOT token inside a live lease; the `state='ACTIVE'` control write predicates on a live ownership lease; the ambiguity/grace handlers apply the matching-token predicate inside their own write transactions when a coordinator drove them (takeovers stay tokenless). | permitted=True at HEAD (stale write accepted) → green |
| HB-9 | `5b8c2b0` (+`b122b44` fmt) | The NEEDS_RECONCILIATION → running transition is predicated on ZERO canonical blocking items (U1–U5, U3p, U3u) through `unresolved_items` UNDER the full §6.1 gate locks — the legacy three conditions missed a surviving U5. | `'SCREEN_RUNNING' == 'NEEDS_RECONCILIATION'` failed at HEAD → green |
| HB-10 | `e4b914e` | CLI resume is fully recovery-first: cleanup-only resume drops `--authorization/--quote` entirely; plain resume softens unreadable (OSError) documents into admission blockers on the recovered status; the service converts eligibility refusals (EffectDenied/PolicyDenied, e.g. an expired quote) into the recovered status plus a blocker instead of an error exit. | the EffectDenied escaped as an error / the broken file refused the sweep → green |
| HB-11 | `97b43a8` | `ExperimentBudgetService.cleanup_grants_only` (set for every non-EXECUTE world `_world` composes): `reserve_in_transaction` refuses any non-cleanup reservation at the service boundary with otherwise valid ownership/scope. The world's `acquire()` refuses a PODLESS lease in RECOVERY/CLEANUP before `ensure_pod` can enter the create flow (no manufactured create-intent state). Mode is a class-level default (EXECUTE) so directly constructed worlds keep the boundary. | the hold opened at HEAD / the provider guard's message from inside the create path → 2 failed → green |
| HB-12 | `9f81ad7` | U2/R1 counts the no-create storage debt while the original hold is EXPIRED-but-unfinalized too (I4). U5 requires complete finality: verified termination AND closed storage ownership AND the lease's compute reservation canonically closed (invoice-level readiness is the janitor's §6.3 gate — offline-unreachable, recorded as the offline boundary). U6 covers a claimed sample with job but NO operation. §5.3's fenced failure path: at verified cleanup the sweep durably FENCES open upload intents (new 0026 state, CHECK widened additively), fails the affected samples under §7.4 with the outcome set once, and releases their positively-unused prompt holds IN the finalization transaction. | 3 failed at HEAD → p3+p4+p2 56 passed, p1+migrations 17 passed |
| HB-13 | `9c28ac6` | The fake ComfyUI server lives only as long as its pod: `couple_server_to_pod_lifetime` + `require_alive`/`reborn` in the testing fake (every guarded call raises once the pod stopped/terminated; a NEW pod boots a fresh server — no prompt/output state survives its pod, the POST ledger and prompt-id counter stay monotonic; the AT-3 §9.3 snapshot round-trips the lifetime). Wired at every composed ComfyWorld+manager pairing. The offline cleanup receipt requires a VERIFIED TERMINATION: stop-only keeps the two unconditional assertions but reports unverified/PENDING with storage honestly open — never a synthesized BILLED; the composed worlds (and the AT-13 restarted process) are runpod-addressed so VERIFIED/BILLED is earned through the real canonical tail (a test's own runpod-addressed provider is kept). AT-4's transport layer is probed with otherwise VALID inputs (real hold/job/sample/lease identity, bound client, verifiable schema): the mode denial and the ownership denial are isolated, with an EXECUTE control proving the same inputs reach the transport boundary. | `AttributeError: no attribute 'alive'` / receipt `verified True` on stop-only → p1 10, p2 16, p3 29 (serial), hb13 1, benchmark_experiments+p3 serial 42, regressions 72. The two AT-4 isolation probes are green at baseline by design — P1's guard code is correct; HB-13's defect there was the test's evidence (the unbound-client probe), not behavior. |
| HB-14 | `5790a45` | Reconcile no longer swallows the finder's multi-match Conflict: a bounded, nonsecret `provider_operation.reconcile_conflict` event is durably recorded (client id and match count only), the operation keeps UNKNOWN with exposure; AT-25 asserts the diagnostic through the public entry point. | no event at HEAD → green, whole P3 file 29 passed |

### Judgement calls (HBF, from the commits)

- **HB-1**: the AT-17 seal window widening is test-only (the preflight's
  max(world clock, real now) binding made the 6-hour window a time bomb).
- **HB-6**: the plan-row GPU route cannot isolate the shutdown reserve in this
  harness (admission only happens while the funded window subsumes the plan
  limit) — noted in the test docstring; the authorization route covers the
  probe.
- **HB-12**: U5's invoice-level readiness is offline-unreachable (the janitor's
  own §6.3 gate) — the offline boundary is documented in the guard test.

### HB-13 detail (commit `9c28ac6`)

**Red → green** (red against committed HEAD, committed fixtures restored via
`git show HEAD:`; the stopped session's uncommitted coupling work was reviewed
against §9.1 and kept before the red runs):

- `test_hb13_fake_comfy_server_dies_with_its_pod` red:
  `1 failed in 8.78s` (`AttributeError: 'FakeComfyServerState' object has no
  attribute 'alive'`).
- `test_cleanup_fixture_requires_verified_termination_evidence` red:
  `1 failed in 9.79s` (`assert True is False` — the stop-only receipt claimed
  verified/BILLED, exactly the HB-13 defect).
- The two AT-4 isolation probes (`test_hb13_at4_recovery_mode_denial_isolated_
  with_valid_inputs`, `test_hb13_at4_execute_control_reaches_the_transport`)
  are **green at baseline by design**: the transport guards are P1's committed
  production code; HB-13's AT-4 defect was the probe's evidence (an unbound
  client with permissive guards proves only the unbound refusal).
- Green after the fix: p1 file `10 passed`; p2 file `16 passed`; p3 file
  `29 passed` (serial); `test_t031_h2b_hb13.py` `1 passed`; serial
  benchmark_experiments + p3 `42 passed in 152.81s`; regressions (comfy_recover,
  world_composition, authorization, v2_comfy_submit, live_world, pika_h3_flex)
  `72 passed in 40.97s`. One combined run showed
  `1 failed, 79 passed` where the single failure was a **basetemp collision**
  (two concurrent background pytest runs sharing `--basetemp` cleaned each
  other's store dirs); it reproduces green serially twice. Lesson recorded:
  never overlap pytest runs on one basetemp.

**Judgement calls (HB-13):**

1. **A new pod boots a fresh server** (`reborn`): pod-side prompt/output state
   never survives its pod; only the POST ledger and prompt-id counter stay
   monotonic (tests count total POSTs; prompt ids never repeat). The coupler
   keys on the returned pod id, so an `acquire_or_reconcile` that merely FINDS
   the same pod keeps its state.
2. **The composed benchmark worlds are runpod-addressed** (provider-id-only
   swap, synthetic finality — the AT-13 pairing), so cleanups run the full
   canonical terminate→verify→settle tail offline and VERIFIED/BILLED is
   earned. P2-8's reverted attempt swapped the finality too (offline invoice
   finality impossible); the provider-id-only swap is offline-legal. A provider
   a test itself made runpod-addressed (the lagging-create fixture) is kept.
3. **Stop-only closes report honest pending, not loud failure**: §9.1/P4 make
   a stopped-not-yet-terminated pod a legal intermediate state (the janitor's
   separate verify tail), so the fixture reports unverified instead of
   crashing — it only crashes when the durable stop evidence itself is missing
   (the two unconditional assertions).
4. **The AT-13 parent world keeps the experiment's runpod addressing**: the
   child created its lease under a runpod-addressed provider; the restarted
   process closing it under a stop-only provider is a cross-process provider
   disagreement the strict receipt exposed (U2 "cleanup pending" blocked the
   convergence). `_adapter_for` now pins the same pairing.
5. **AT-3's parent seeds the rebuilt pod AFTER `_adapter_for`** (which fixes
   the provider pairing) — seeding before it landed in a provider the adapter
   replaced, and the §3.4 binding went INDETERMINATE.


## LF — GLM review of Luna's `82135d4`, L-1..L-7 (commits `8810068`, `3b63acd`, `bdf1e2b`)

Findings and rulings: [review](glm-review-luna-REPORT.md), rulings at the end of
[rulings-canary-night.md](rulings-canary-night.md). L-1/L-2 were raised to
BLOCKING for the paid run.

### Red → green

- **L-1+L-2** (`8810068`) red at HEAD:
  `SchemaInvalid: Pika dynamic destination must be contiguous and role-typed`
  inside `native.bind` (the review's probe, reproduced on the ruling's
  acceptance shape — S01–S07 outfit A, S08 outfit B with the SAME role and
  subject, every shot's port list non-ordinal). Green: the LF costume-change
  test `1 passed` (stages all five assets with exactly 5 upload POSTs, both
  outfit rows VERIFIED, submits, and the per-shot manifests carry the right
  costume); binder/v2/world-composition regressions `28 passed`; at17 subset
  `4 passed`.
- **L-3** (`3b63acd`) red at `628fe5b` — run in the reviewer's detached
  worktree (`/tmp/t031-luna-redcheck`, left in place): `assert True is False`
  (preflight stayed ready with the rejecting policy — it never consulted it).
  Green at HEAD with the fixed test (ready control + policy-refused verdict).
- **L-4** (`3b63acd`) red at HEAD: all three states reported `ready: true`
  (public actions enabled; exposure cap committed; GPU budget exhausted).
  Green: exact reasons asserted.
- **L-6/L-7** (`bdf1e2b`) are coverage restorations — the live-policy
  non-widening cases and the DB-backed evidence path had no test to go red;
  their fixtures refuse loudly at every step that could regress (the exact
  branch messages; the evidence dedup/restatement/foreign-pod behavior).
- Combined LF verification: lf file + authorization + world_composition +
  runpod_transport + pika_h3_flex `117 passed in 42.29s`.

### What shipped

- **L-1**: `bind()` presents the shot's selected ports per media kind in
  destination-ordinal order before the binder (the binder counts per-kind
  ordinals in list order; the validator only guarantees the per-shot SET is
  contiguous). Shared-map seals behave identically (their lists were already
  ordinal; sorting preserves them).
- **L-2**: bind's upload lookup keys the full slot identity stage uses
  (role, subject_id, asset_sha256, media_kind) — a same-subject costume change
  never collapses onto one receipt.
- **L-3**: the composition preflight test stubs the authorization layer and
  builds an otherwise-READY seal (live schema evidence, future hard stop), so
  the monkeypatched POLICY is what decides; `_compose` gained `seal_overrides`.
- **L-4**: preflight appends "public actions must stay disabled for the paid
  benchmark" and the two headroom reasons (exposure cap committed / aggregate
  GPU budget exhausted) — local durable reads, no reservation made.
- **L-5**: runbook section "Re-issuing pre-existing LIVE seals".
- **L-6**: the five parametrized non-widening cases on the LIVE
  `ExperimentalPresetPolicy` against real `preset_registry` rows.
- **L-7**: DB-backed §G evidence test — idempotent replay, preserved
  restatement revisions, foreign pod writes nothing.

### Judgement calls (LF)

1. **L-3's red is at `628fe5b`, not HEAD**: the defect was the test's
   vacuousness (green-at-parent), and H-3's production fix already shipped in
   Luna's commit; the fixed test pins the behavior and fails pre-Luna exactly
   as the ruling requires. The `schema_attestation_source` field (Luna's H-6)
   does not exist at `628fe5b`, so the redcheck copy drops that one override.
2. **L-4's public-actions state is unreachable through validated `Settings`**
   (the Settings model validator refuses the combination first). The preflight
   reason is parity defense with the factory's own guard; the test constructs
   the state via `model_construct` and documents this.
3. **L-6's enabled case carries the full production shape** the registry
   itself demands (measured + evidence + rights route, reference-free control
   set) — the mutation-isolating ideal (enabled alone) is not a legal registry
   row, so the case pins the branch with a legal record instead.
4. **L-6 has no full-pass control**: reaching the policy's return requires the
   full composed shape (model rights, sources, schema) that AT-17's
   real-composed tests already cover; the exact branch messages pin which
   refusal fired.

**Resume here (superseded): P5 — completed below on 11 Nov.**

## P5 — terminal finalization, mapping, monotonic projection, R6, R7 (commit `0e34630`)

### Where this session started

The previous session stopped mid-P5: the parked patch
(`.scratch/t031-h2b-p5-wip/p5-wip.patch`) had been re-applied to the tree
adapted to post-HBF/LF line numbers (5 `.rej` leftovers from the apply,
moved to `.scratch/t031-h2b-p5-wip/session-1011/rej-leftovers/`), plus a
new test file and one production extension of its own (the U4
`operation_id` in `unresolved_items`). The tree's test file already
superseded the parked copy (fixture corrections — see judgement call 1).
All of it was reviewed against spec §7 before being kept; the red runs
below are against committed HEAD sources throughout (restored via
`git show HEAD:`), then the saved diff re-applied.

### Red → green (pytest summary lines)

- P5 file red (tests only, committed sources restored):
  `10 failed, 5 passed in 30.31s`. The 10 red cover AT-8 (replayed
  resolve), AT-8b (R7 matrix both halves), AT-9 `resolve_sample_after_commit`
  and `ambiguity_handler_after_label`, AT-12 (R8), AT-22 (terminal commit
  before settlement) and AT-9b (R6 × FAILED/CANCELLED/NOT_FOUND) — e.g.
  `AssertionError: assert 'CLAIMED' == 'FAILED'` (no finalize_terminal, no
  R6 projection). The 5 pre-green are AT-9 boundaries that converge through
  **committed** P2–P4 code (submit ambiguity, resolve_create replay ×2,
  sweep finalization replay, AT-22b) — kept as the parametrized inventory,
  noted rather than weakened.
- The three adapted ATs red (their `force_unrecoverable` update applied to
  committed sources): `3 failed in 13.42s` — `TypeError` on the kwarg
  (AT-20 in p1, AT-15 and AT-2 in p3).
- Green: P5 file `15 passed in 32.90s`; whole H-2B suite P1–P5
  `81 passed in 269.32s`; regressions (benchmark_experiments,
  world_composition, comfy_recover, authorization, live_world,
  v2_comfy_submit, pika_h3_flex) `1 failed, 87 passed in 79.22s` — the one
  failure was the pre-existing
  `test_operator_resolves_an_unfindable_prompt_and_frees_the_slot`, whose
  scenario is exactly R7's reachable-but-unrecoverable case; updated to
  `force_unrecoverable=True` (judgement call 6), then
  benchmark_experiments + t045_billing_ingestion `40 passed in 64.64s`;
  canary + HB-13 + LF files `65 passed in 50.09s`. `ruff check`/`format`
  clean; `contracts-check` 2.16.0 OK.

### What shipped

- **§7.1 `finalize_terminal(operation)`**: network-free and idempotent —
  canonical settlement/release first through the new
  `ComfyRenderService.settle_terminal` (→ `_settle_if_needed`; the
  deterministic receipt keys make replays no-ops), then sample projection
  + dispatch-slot clear + the R6 outcome write in ONE transaction under
  account → categories → E → D → S. `reconcile` runs it for every U4 item;
  U4 now names its terminal `operation_id`.
- **§7.2**: FAILED/CANCELLED/NOT_FOUND all project FAILED with the original
  reason kept (`error_code` from the recorded result); NOT_FOUND never
  enables resubmission (it maps to FAILED); `_observe` clears the slot on
  every terminal projection (CANCELLED/NOT_FOUND included); projection is
  monotonic under D/S locks — a stale nonterminal observation never
  overwrites a terminal sample (`_observe` and `finalize_terminal`).
- **R6 atomic fail-fast**: projecting an eligible failed fixed sample,
  `execution_outcome=FAILED` if unset, generation stop and the slot clear
  commit in one transaction — in `_observe` (normal polling now fails fast
  like reconcile/operator resolution, §7.4) and in `finalize_terminal`.
  Replay repairs the same outcome idempotently.
- **§7.3**: `resolve_unknown_operation` replays an IDENTICAL attestation
  (same actor/reason/evidence SHA on the terminal operation) before
  anything else; a different attestation and a terminal-without-audit are
  terminal-provenance `Conflict`s; the audit event (now recording
  `forced_unrecoverable`) and the terminal FAILED transition commit
  together under the operation lock, financial finalization after (R5).
  `resolve_sample` runs the R7 live-source matrix: VERIFIED_SOURCE_GONE
  resolves ordinarily; BOUND with positively recoverable work refuses even
  with force (Conflict — reconciliation owns it); reachable-but-unrecoverable
  and INDETERMINATE require `force_unrecoverable` (CLI
  `--force-unrecoverable`), recorded in the audit.
- **AT-12 (R8)**: exposure identity asserted across ACTIVE → EXPIRED →
  settled → late-ADJUSTMENT replay (the stopped session's corrected
  expectations: expiry keeps the total exactly; the audited settlement
  releases only the positively-unused remainder; the identical late
  adjustment never double counts).

### Judgement calls (P5)

1. **The stopped session's tree supersedes the parked patch** and was kept
   after review: its test file had already fixed real fixture defects —
   one composed `_at14_context` world per test (the parked two-world mix
   collided on deterministic account ids), the R8 settlement expectation
   corrected to release only the expired hold's positively-unused
   remainder, the offline ADJUSTMENT receipt's basis/provenance corrected
   to the offline world's canonical pair, and asset/operation assertions
   scoped to S01's own attempt (the screen may legitimately continue past
   a recovered sample; the fake server's deterministic bytes make other
   samples' shas coincide).
2. **Two production fixes from this session's review** (the parked WIP
   passed tests only because every test passed `world=adapter`):
   `reconcile`'s U4 loop and `finalize_terminal`'s world fallback composed
   `mode="RECOVERY"` WITHOUT `acquisition_id` — a hard `Conflict` under
   HB-3 whenever the experiment has acquisitions. Both now name the
   acquisition (one RECOVERY world per acquisition, reused across its U4
   items), and AT-22 drives the `world=None` path through a naming factory
   that fails loudly if a RECOVERY world is composed unnamed.
3. **`_observe` locks E before D/S for the R6 write**: the parked code
   appended the E-row outcome UPDATE after the D and S locks — an
   earlier-order lock taken after later-order ones (§6.1), a deadlock risk
   against the admission gate (E → … → D). The transaction now takes E
   first.
4. **The R6 outcome write is set-once** (`COALESCE` outcome +
   state-change only when the outcome was previously unset) rather than
   the old `repo.outcome` unconditional `execution_state` overwrite: §7.4
   sets the outcome ONCE (I7), and a replay must not clobber whatever
   durable state followed the first write.
5. **Normal polling now fails fast**: at HEAD only `resolve_sample` wrote
   the FAILED outcome; §7.4 requires it "equally when the failure arrives
   through normal polling, reconcile or operator resolution", so `_observe`
   carries the same R6 write (this is why AT-22b's second resume and the
   poll-driven paths now stop generation).
6. **The pre-existing unfindable-prompt test updated to
   `force_unrecoverable=True`**: its BOUND pod's history never shows the
   prompt — R7's reachable-but-unrecoverable case, the same treatment the
   WIP already gave AT-15/AT-2/AT-20. The behavior change is the spec's,
   not a fixture weakened to pass (the refusal is asserted positively in
   AT-8b).
7. **AT-9's five pre-green boundaries kept**: they pin convergence through
   committed P2–P4 code and complete the parametrization over the
   transaction inventory (submit ambiguity, resolve_create replay before
   and after sweep, resolve_sample-after-commit, ambiguity-handler label,
   sweep finalization replay); their green-at-red is recorded here.
8. **`resolve_sample`'s terminal-replay path defers to the comfy layer's
   replay check**: an operation terminal WITHOUT an operator audit raises
   the terminal-provenance `Conflict` (§7.3) — `reconcile` owns the
   ordinary terminal replay through U4/finalize_terminal; resolve never
   adopts a non-operator terminal outcome.
9. **R7's BOUND probe polls once and treats ANY positively-known outcome
   as recoverable work** (even a provider-FAILED one — reconciliation owns
   it, Conflict even with force), while an unreachable/empty/conflicting
   history stays reachable-but-unrecoverable (I2: reachability alone is
   not recoverability) — the force path. The probe's poll may itself adopt
   the terminal outcome durably; AT-8b documents that this IS the
   reconciliation owning it.

**Resume here: none — P1–P5, HBF and LF are all DONE
(`H2-BUILD: ALL PACKAGES DONE` at the top). Committed through `0e34630`;
tree clean. The superseded parked WIP stays at
`.scratch/t031-h2b-p5-wip/` for reference.**
