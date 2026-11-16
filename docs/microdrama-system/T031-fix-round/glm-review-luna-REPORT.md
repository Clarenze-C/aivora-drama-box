# GLM review — Luna's H-3..H-9 commit `82135d4`

Reviewer: GLM-5.3 (Luna is Codex gpt-6-luna; Codex may not review Luna code). Date: 2026-11-10.
Scope: `git show 82135d4` only (12 files, +324/−131), parent `628fe5b`. H-2 behaviour out of
scope; conflicts with `/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md`
flagged in a dedicated section. All Luna code was read via `git show 82135d4:<path>`; nothing
was taken from the working tree (which another builder holds at `45e4f2a`).

**Verdict up front: FIX-REQUIRED — 0 BLOCKING, 3 SHOULD-FIX, 4 NIT.** H-3, H-4, H-6, H-7,
H-8, H-9 are CLOSED. **H-5 is PARTIAL**: the 0026 obstacle is gone and staging dedups
correctly, but the binder still rejects shot-scoped maps the validator accepts — the commit's
own costume-change seal fails at bind for every shot (probe-verified below) — and no test
executes shot-scoped stage/bind.

## Red-check setup

`git worktree add --detach /tmp/t031-luna-redcheck 628fe5b` (left in place for the
orchestrator). The three changed test files were written into it **from the commit**
(`git show 82135d4:<path>`). `microdrama` resolves via pytest `pythonpath = ["src"]`
(pyproject.toml:33), so the detached worktree imports its own 628fe5b source, not any
installed package. All runs under `systemd-run --scope -p CPUQuota=45% --quiet`, offline
env flags, `--basetemp=/tmp/t031-lunarev-basetemp`, shared venv python.

## Per-ID results

| ID | Verdict | Red at `628fe5b`? |
|----|---------|-------------------|
| H-3 preflight/factory single source | **CLOSED** | unit test red (`3 failed, 1 passed`); composition test **passes at parent** (vacuous — L-3) |
| H-4 §G raw billing evidence wired | **CLOSED** | red: `1 failed in 0.69s` (`AttributeError: ... no attribute '_record_benchmark_raw_evidence'`) |
| H-5 shot-scoped port maps | **PARTIAL** | the only new H-5 test **passes at parent** (`1 passed` inside the 4-test run) — the seal validator was never the obstacle; stage/bind untested (L-1, L-2) |
| H-6 CPU-hash + label-only denial | **CLOSED** | red: both tests in the `3 failed` set (`ValidationError ... extra_forbidden, input_value='INDEPENDENT_RUNTIME_CAPTURE'`) |
| H-7 cleanup-hold acquisition link | **CLOSED** | no test (code-verified; key format confirmed) |
| H-8 dead duplicate policy removed | **CLOSED** | n/a (removal); coverage regression → L-6 |
| H-9 resume-window documentation | **CLOSED** | doc-only, content accurate |

Exact pytest summaries (parent `628fe5b`):

```
tests/unit/pipeline/test_benchmark_authorization.py (4 new tests)
  FAILED test_published_cpu_no_weights_hash_cannot_be_relabelled_live   (extra_forbidden)
  FAILED test_live_provider_label_without_independent_capture_is_denied (extra_forbidden)
  FAILED test_preflight_is_not_ready_when_factory_policy_refuses        (reason string absent)
  PASSED test_shot_scoped_costume_ports_reuse_the_same_destination_per_shot
  => 3 failed, 1 passed in 0.64s

tests/unit/rendering/test_runpod_transport.py::test_benchmark_raw_billing_writer_receives_original_amount_strings
  => 1 failed in 0.69s   (AttributeError: module ...runpod_billing has no attribute
                          '_record_benchmark_raw_evidence')

tests/unit/pipeline/test_benchmark_world_composition.py::test_preflight_uses_the_same_policy_as_the_default_factory
  => 1 passed in 6.00s   (NOT red — vacuous, see L-3)
```

### H-3 — CLOSED

Preflight (`benchmark_service.py:88-100`) rebuilds `BenchmarkPlan`/`BenchmarkSeal` from the
same durable status documents the factory reads, constructs the same
`ExperimentalPresetPolicy`, and calls the same `policy.validate(db, settings, clock, quote)`
that `build_experiment_world` (`experimental_world.py:818-820`), `create_guard` (:880) and
`request_guard` (:957, :972) call. **One validation source, not a duplicate** — it imports
and invokes the live policy. Rights/preset refusal now propagates to `ready: false` with a
red→green wiring test. Residuals beyond the ruling (factory parity is exact; the ruling did
not ask for more): budget/gpu headroom and `public_actions_enabled` are still absent from
the ready decision → L-4.

### H-4 — CLOSED

`_record_benchmark_raw_evidence` (`runpod_billing.py:94-129`) is called from
`map_billing_history` at :221, **before** bucket construction/ingest — evidence precedes
allocation by ordering. Not one transaction (each `db.transaction()` draws its own pooled
connection — `persistence/db.py:189`), but **replay-safe**: `record_billing_evidence`
(`benchmark_experiments.py:393-433`) inserts with `ON CONFLICT DO NOTHING` against
`PRIMARY KEY(acquisition_id, raw_commit_sha256)` (0026:75), so exact replays are no-ops and
a restated bucket (different amounts, same identity) lands as a second row — revisions are
preserved, matching the H-4 finding's "identity + raw commit hash" design. Payload is
whitelist-only (`set(evidence) != allowed` guard) — **no headers or secrets**; ownership is
re-verified inside the write transaction. Fail-closed `Conflict` when a benchmark-owned
record lacks raw strings (documented conservative choice; janitor backs off, hold stays).
Gap: the write branch has never run against a real DB (fake-Tx test only) → L-7.

### H-5 — PARTIAL (L-1, L-2)

What is right: the 0026 edit removes exactly the authorized
`UNIQUE(acquisition_id,destination_slot)` (ruling-sanctioned; every guard trigger kept —
immutable/no-delete/no-truncate/integer-only; `test_migrations.py` asserts table existence
only, unaffected). `stage()` dedups by the upload PRIMARY KEY via SELECT-then-INSERT, so
repeated shot entries of one asset no longer violate any constraint (they take the
`reconcile_input` branch). `bind()` filters ports by `shot_id` and takes the destination
from the immutable seal. Shared-map seals behave identically to before (no regression to
the executable path).

What is broken: see L-1 and L-2. Both fail **after** pod acquisition with `SchemaInvalid`
→ `except BaseException` → experiment terminally FAILED — the exact H-5 failure shape the
fix was meant to remove, now for a subset of validator-legal seals including the commit's
own test seal.

### H-6 — CLOSED

`DENIED_LIVE_SCHEMA_SHA256` pin **verified by probe**: recomputed
`mapped_schema_sha256(attestation["schemas"], PIKA_TEMPLATE.node_classes)` from
`deployment/pika-h3-flex/schema-attestation.cpu.json` at the commit →
`339021b1e3106ee0648b264f0ef1ddc8e1bb68c0374d8d6c7c1a6b0f375ba9ae` — **MATCH**. The new
`schema_attestation_source` field (default `SELF_ASSERTED`) plus the
`validate_for` checks (`benchmark_authorization.py:410-420`) machine-deny both the pinned
hash and label-only LIVE evidence, per the ruling. Bypass analysis: a *re-hashed* CPU
schema (different Comfy build) is not in the deny-set — residual risk unchanged from the
original finding (bind-time live attest fails closed on a weights-provisioned runtime;
waste bounded by holds). `schema_attestation_source` is itself a self-assertable label, so
the machine guarantee comes from the deny-list + bind-time attest, which is what the ruling
scoped. Operational side effect → L-5.

### H-7 — CLOSED

`_reserve_cleanup_grant` builds `semantic_key = f"pod.stop:{row['id']}"` with the
pod_leases row (`leases.py:1418-1419`, `STOP_OPERATION_KIND = "pod.stop"` in `pods.py:47`),
so `removeprefix("pod.stop:")` (`benchmark_experiments.py:178`) extracts exactly the lease
UUID and the lookup `(experiment_id, lease_id)` resolves the owning acquisition under
multiple acquisitions — each generation claims its own lease and the partial unique index
keeps one open acquisition. Other cleanup ops keep the old fallback (documented). Residual:
if two acquisition rows ever shared one lease, `fetchval` picks arbitrarily — benign
(same experiment, same lease). No dedicated test (Luna acknowledged) — acceptable for a
bookkeeping link; noting under weakened-assertions.

### H-8 — CLOSED

`rendering/experimental_presets.py` is now a docstring-only stub; `git grep` at the commit
finds **zero importers**; its parametrized test removed. Coverage regression → L-6.

### H-9 — CLOSED (doc-only)

`runbooks/t031-benchmark.md` states the 600 s prompt-hold window, reconcile-not-resubmit
resume, and the terminal FAILED consequence of a janitor-expired hold — matches the current
mechanics (H-9 finding) and §E. See conflicts section for the H-2-recovery interaction.

## Findings

### L-1 · SHOULD-FIX — the binder still rejects shot-scoped maps the validator accepts; the commit's own costume seal cannot bind, and nothing tests stage/bind

- **Where:** `microdrama/src/microdrama/pipeline/experimental_world.py:668-670` (bind's
  shot filter preserves seal list order), vs
  `microdrama/src/microdrama/rendering/workflows/pika_h3_flex.py:287-296` (binder requires
  each port's `destination_slot` to equal the running per-kind ordinal in **list order**),
  vs `benchmark_authorization.py:272-277` (validator only requires the per-shot destination
  **set** to be contiguous).
- **Scenario (probe-verified):** the seal built by the commit's own
  `test_shot_scoped_costume_ports_reuse_the_same_destination_per_shot` lists each shot's
  ports as [character@ref_image_0, location@ref_image_2, voice@audio0, outfit@ref_image_1].
  It validates (set {0,1,2} contiguous). At bind, the binder's ordinal counter expects the
  second image port at `ref_images.ref_image_1` but gets `location@ref_image_2` →
  `SchemaInvalid: Pika dynamic destination must be contiguous and role-typed` — reproduced
  for S01 and S08 by an offline probe against the commit's fixture. This raises inside
  `native.bind` after the pod was acquired → `except BaseException` → experiment
  terminally FAILED. The delivered acceptance example for the ruling ("must stage and bind
  (S08 costume change)") therefore cannot run, and **no test in the commit executes
  shot-scoped stage or bind** (Luna reported the same; nothing was added since). The only
  new H-5 test passes at the parent because the seal validator was never the obstacle.
- **Fix:** normalize order in `bind()` (sort the shot's selected ports per media kind by
  destination ordinal) or tighten the seal validator to require per-shot list order; then
  add one DB-backed test that stages AND binds the S08 costume-change seal through
  `_SealedNativeInputs` and asserts the per-shot port sets (S01–S07 outfit A, S08 outfit B).

### L-2 · SHOULD-FIX — bind's upload lookup collapses (role, subject_id), so a same-subject costume change binds the wrong receipt and fails after acquisition

- **Where:** `microdrama/src/microdrama/pipeline/experimental_world.py:665` —
  `by_key = {(r["role"], r["subject_id"]): r for r in rows}` over **all** acquisition
  uploads, unordered.
- **Scenario:** the seal validator permits the same `(role, subject_id)` to bind different
  assets in different shots (references dedup on the 5-key; per-shot semantic uniqueness is
  per group). With outfit A and outfit B both `role=outfit, subject_id=wardrobe`, stage
  correctly creates two upload rows, but bind's dict keeps only whichever row `fetchall`
  returned last. For one shot the receipt's `asset_sha256` mismatches the port's, and the
  binder's strict receipt check (`pika_h3_flex.py:303-317`) raises `SchemaInvalid` →
  experiment FAILED after pod acquisition. Fail-closed (no wrong bytes are ever sent), but
  it is the H-5 failure mode for a validator-legal seal. The delivered test sidesteps it by
  giving outfit B a different `subject_id`.
- **Fix:** key bind's lookup by the same 5-tuple stage uses
  (role, subject_id, asset_id, asset_version, asset_sha256) — the port already carries all
  five — and skip rows whose asset identity differs from the port's.

### L-3 · SHOULD-FIX — the composition preflight test is vacuous: it passes identically at the parent because `_validate_authorization` fails before the monkeypatched policy is ever reached

- **Where:** `microdrama/tests/unit/pipeline/test_benchmark_world_composition.py:253-275`
  (`test_preflight_uses_the_same_policy_as_the_default_factory`).
- **Scenario:** `_compose` builds its seal from the shared `seal_data` fixture, which has no
  `schema_evidence` → default `UNVERIFIED`. Preflight's pre-existing
  `_validate_authorization` then raises `PolicyDenied` (fixture schema cannot authorize)
  **at both revisions**, appending the asserted reason without the monkeypatched
  `ExperimentalPresetPolicy.validate` ever running. Proven: the test was run at parent
  `628fe5b` → `1 passed in 6.00s`. It contributes a misleading green to the orchestrator's
  215-passed run and does not pin the H-3 behaviour its name claims; the ruling's test
  requirement ("a state the factory refuses must make preflight report not-ready") is met
  only by the monkeypatch-based unit test.
- **Fix:** make the composed seal/authorization genuinely LIVE (passing
  `_validate_authorization`) before applying the reject monkeypatch — or stub
  `_validate_authorization` as the unit test does — so the policy path is actually
  exercised, and assert the parent fails it (red baseline).

### L-4 · NIT — preflight still reports ready in two factory-refusing states the ruling did not list

- **Where:** `benchmark_service.py:78-84` vs `experimental_world.py:809-817`.
- **Scenario:** (a) `settings.public_actions_enabled=True` in PAID_BENCHMARK mode: the
  factory raises `EffectDenied`, preflight says ready (it checks execution mode and the two
  effect flags only). (b) exposure already at `cap_micro_usd` or aggregate gpu_ms exhausted:
  refusal comes from `ExperimentBudgetService.reserve_linked` (`BudgetExhausted`), which
  `policy.validate` does not cover — `preflight --execute` can print `ready: true` and the
  first `acquire` refuses. The original H-3 finding suggested headroom in the ready
  decision; the ruling only required factory parity, which is exact.
- **Fix:** add `public_actions_enabled` to the flag reason; optionally fold
  exposure-vs-cap and gpu-ms headroom into preflight reasons (both are local DB reads).

### L-5 · NIT — every pre-existing LIVE seal now fails until re-issued; operators have no note about the new attestation-source field

- **Where:** `benchmark_authorization.py:173-175, 412-413`.
- **Scenario:** `schema_attestation_source` defaults to `SELF_ASSERTED`, and
  `validate_for` refuses LIVE seals without `INDEPENDENT_RUNTIME_CAPTURE`. No in-repo tool
  sets the field (seals are operator-authored JSON via `service.seal`), so a genuine live
  seal captured before this commit — or after it, authored per the old docs — is refused
  with "self-asserted", and fixing the field changes `sealed_sha256`, so the recorded
  authorization must be re-issued too. Fail-closed and consistent with the ruling, but
  undocumented: neither the new runbook nor BUILD_EVIDENCE mentions it.
- **Fix:** one paragraph in the benchmark runbook: live seals must carry
  `schema_attestation_source: "INDEPENDENT_RUNTIME_CAPTURE"` and a re-issued authorization.

### L-6 · NIT — H-8's removal drops the only "experimental preset must not widen production eligibility" regression coverage

- **Where:** removed `test_pika_h3_flex.py::test_experimental_policy_does_not_widen_production_eligibility`
  vs live branch `experimental_world.py:243-251` (enabled/measured/thai → `PolicyDenied`).
- **Scenario:** the removed parametrized test was the only test asserting the disabled/
  unmeasured/thai-null refusals; `git grep` at the commit finds no test asserting the live
  policy's "experiment requires the exact current disabled, unmeasured preset" branch. A
  future edit could re-widen experimental eligibility with no red test.
- **Fix:** re-home the five parametrized cases onto the live policy (seed a preset row,
  call `ExperimentalPresetPolicy.validate`, assert `PolicyDenied`).

### L-7 · NIT — the §G evidence write path has never run against a real database

- **Where:** `runpod_billing.py:94-129`, tested only by the fake-Tx
  `test_benchmark_raw_billing_writer_receives_original_amount_strings`.
- **Scenario:** the owner lookup's join (`benchmark_acquisitions ⋈ pod_leases ON
  p.id=a.lease_id ... p.pod_id=%s`) and the evidence INSERT are unexercised against real
  Postgres; a column-name or type slip would surface only in a paid run's janitor pass.
  The H-2 recovery spec's AT-12 ("§G evidence dedup on replay") will cover this if its
  builder wires a benchmark-owned pod into the ingestion fixture — recommended.
- **Fix:** one DB-backed test: seed an experiment+acquisition+lease with a pod_id, run
  `map_billing_history` with a raw-amount record for that pod twice, assert one evidence
  row and idempotency.

## Weakened assertions / skipped tests

- No skips in the diff. The old shared-map duplicate-destination negative
  (`test_seal_checks_exact_asset_version_and_media_port`'s tail) was re-homed into the new
  shot-scoped test — the validator branch stays covered; no net loss.
- `test_preflight_uses_the_same_policy_as_the_default_factory` is green-at-parent (L-3) —
  the only genuinely vacuous addition.
- H-5 and H-7 ship with no runtime test at all (L-1; H-7 acknowledged by Luna).

## Conflicts with the H-2 recovery spec (`T031-H2-recovery-spec.md`)

No semantic conflicts found; three coordination hazards:

1. **Both edit migration 0026 in place.** Luna changed the `benchmark_uploads` PRIMARY KEY
   line; the recovery spec §8 adds columns to `benchmark_acquisitions` in the same file.
   Textually a merge conflict when the H-2 build lands on top of `82135d4`; both preserve
   every guard, so resolution is mechanical.
2. **Line anchors drift.** The spec cites `experimental_world.py:815/845/443/922/937` and
   `benchmark_service.py:364`/`:507`. Luna's inserts (+33 net in experimental_world above
   those regions, +13 in benchmark_service preflight) shift every anchor; the H-2 build
   must re-resolve them against the new file, not the spec's numbers.
3. **H-9 runbook vs recovery semantics.** The runbook states an expired prompt hold makes
   the resumed submit terminally FAILED. The recovery spec (§3.3 expired-reservation
   recovery-read exception; AT-15 crash-before-POST → UNKNOWN, adopted/audited, no
   resubmit) will soften exactly that terminal story for the dispatch pipeline. The runbook
   will need a refresh when the redesign lands — flag to the H-2 builder, not a defect
   here. AT-12's "§G evidence dedup on replay" also confirms the recovery spec builds on
   Luna's H-4 wiring (compatible: PK `(acquisition_id, raw_commit_sha256)` + DO NOTHING).

## Verdict

**FIX-REQUIRED.**

- BLOCKING: 0
- SHOULD-FIX: 3 (L-1 shot-scoped seals still unbindable + untested; L-2 bind lookup
  collapse; L-3 vacuous composition test)
- NIT: 4 (L-4 preflight residuals; L-5 seal re-issue note; L-6 lost non-widening coverage;
  L-7 evidence path untested on real DB)

H-3, H-4, H-6, H-7, H-8, H-9 are correctly closed with red→green evidence where tests
apply (H-6's deny-hash pin independently re-verified by probe). H-5 remains PARTIAL: the
constraint obstacle is gone and staging is safe, but the ruling's "must stage and bind"
is not demonstrably met — the commit's own S08 costume-change seal fails at bind
(probe-verified), a second validator-legal seal shape fails at bind through the upload
lookup, and neither path has a test. Fix L-1/L-2 with one DB-backed stage/bind test, and
make L-3's composition test actually red-at-parent, before accepting H-5.
