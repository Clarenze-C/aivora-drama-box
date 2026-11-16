# T031 canary-night review — 6 November 2026

**Verdict: FIX REQUIRED before the next paid qualification run.**

Scope: immutable runtime/test delta `13da3e2..0851374`, reviewed at
`085137415862a309f30df949224e6ed5431e86e4`. This review does not reopen the
closed T045 review cycle and does not review the subsequent documentation draft.
The implementation commits identify Claude Code as co-author; this session has
not authored the reviewed application code. No application changes were made.

## R1 — valid billing components can fail conservation after rounding (P1)

`microdrama/src/microdrama/rendering/runpod_transport.py:596–625`, introduced by
`c65089a`, rounds total, GPU, CPU and disk independently. A provider row can obey
the exact decimal accounting identity yet violate it after these four independent
roundings. The downstream billing reconciliation treats a component mismatch as
DISPUTED, so otherwise valid usage cannot reach invoice finality and release its
hold. The new test covers individual fields and the observed run-14 values, not
component conservation across the rounding boundary.

Reproduced with the real `_billing_record`, no provider or database calls:

| Field | Exact provider USD | Parsed micro-USD |
|---|---:|---:|
| GPU | 0.0351746 | 35,175 |
| CPU | 0 | 0 |
| Disk | 0.0005786 | 579 |
| Total | 0.0357532 | 35,753 |

Raw GPU + CPU + disk equals total exactly; parsed components sum to **35,754**.
This is a deterministic counterexample, not a claim that run 14 was misbilled.

Required fix: validate original finite nonnegative Decimal amounts and their raw
conservation first, with an explicitly bounded provider-representation tolerance,
preserve raw evidence, round the authoritative total once,
then allocate its integer atoms deterministically across components (for example
floor + largest remainder with a documented tie order). Do not mask genuinely
inconsistent provider data or rewrite existing stored billing revisions. Test both
rounding directions, ties, zero, malformed/non-finite inputs, a truly inconsistent
raw row and downstream invoice/adjustment replay. Existing run-14 values must
remain unchanged. Integer allocations must sum exactly to the rounded total.
The console's binary-float decimal encodings differ from exact component sums by
tiny fractions of an atom; exact raw equality alone would reject run 14 again.
Choose a reviewed Decimal tolerance far below one micro-USD, retain the raw values
and discrepancy, and test both sides of that tolerance. Do not use a tolerance
large enough to hide a genuine monetary discrepancy.

## R2 — new diagnostic text is persisted without credential redaction (P2)

`runpod_transport.py:244–254` and `comfy_transport.py:68–89` now include provider
body excerpts or exception text in messages. These flow into the canary record
(`pipeline/canary.py:1052–1057,1153–1167`) and CLI refusal output. The assertion in
comments that provider diagnostics are never secrets is not enforced.

A scripted 401 response containing `Authorization: Bearer` followed by a clearly
synthetic marker reproduced that marker in the real `ProviderError.message`.
No real credential was read, supplied or printed. This establishes the missing
redaction path; it does **not** claim RunPod actually echoed a live key.

Required fix: sanitize known credential values and authorization/header-shaped
content before exceptions cross the transport boundary, bound both reads and
retained text, and preserve useful status/non-sensitive detail. Apply the same
policy to uncertain transport causes. Tests should include reflected credentials,
case variants, long bodies and benign GPU/schema errors. Do not write raw secret
bodies to an alternate evidence/log file.

## Reviewed behavior and limits

- Ordered GPU catalog selection, port declaration and price-at-or-below-quote
  checks have direct regression coverage. The declared endpoint retains the pod's
  own proxy host; the existing scoped request guards remain in place.
- The new early pod-ID write precedes `PodManager.verify`, covering the observed
  warmup/interrupt failure after `acquire_or_reconcile` returns. This is not proof
  that every earlier crash window or provider-side price rejection is closed;
  retain existing unknown-create reconciliation and ownership restrictions.
- Warmup and object-info retries are deadline bounded. The changed object-info
  retry does not automatically retry a prompt submission.
- Legacy `gifs` output normalization preserves byte/media verification downstream;
  real H3 `SaveVideo` schema/output parsing is still a separate integration task.
- Invoice resolved-window acceptance retains account, pod, settle-lag, skipped
  bucket, period-edge and mismatch checks. The new positive test was run along
  with the existing negative tests. This is not a provider API finality guarantee.
- Pool opening now reaches the actual CLI instead of only a monkeypatched open
  fixture. The CLI still deliberately retains its pool until process exit; do
  not reuse `main()` as a long-lived service API without lifecycle design.

Serena tools were not exposed in this session. Inspection used AST symbol
overviews, selected symbol bodies, an AST caller inventory and the immutable Git
diff. No whole Python module was dumped as a reading shortcut.

## Verification actually performed

Focused offline run under `systemd-run --scope -p CPUQuota=45%`, isolated
`--basetemp`, 1,500-second process timeout: **150 passed, 1 warning in 60.52 s**,
exit 0. The warning is an existing Pydantic enum-serialization warning in the
billed-zero invoice test. Command, from `microdrama/`:

```bash
systemd-run --scope --quiet -p CPUQuota=45% env \
  MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK \
  PYTEST_ADDOPTS=--basetemp=/root/AIVORA/drama-box/.scratch/t031-steps123/basetemp-review \
  timeout 1500 .venv/bin/python -m pytest \
  tests/unit/rendering/test_runpod_transport.py \
  tests/unit/rendering/test_comfy_transport.py \
  tests/unit/rendering/test_pods_filters.py \
  tests/unit/rendering/test_lease_lifecycle.py \
  tests/unit/budget/test_t045_invoice_period.py \
  tests/unit/pipeline/test_t045_canary_runner.py \
  tests/integration/pipeline/test_t045_canary_composed.py
```

Log: `.scratch/t031-steps123/canary-review-tests.log`. A passing existing suite
does not cover R1/R2's new counterexamples. Reproduction is saved in
`docs/microdrama-system/t031-benchmark/review-probes.txt` as commands, not a
production test or an accepted fix. `git diff --check 13da3e2..0851374` passed.
No full `make check`/pilot was rerun; no real provider calls, production writes,
resources, paid inference, publication, commits or pushes occurred.

## Disposition

Step 1 review is complete with these findings open. Steps 2–3 require the
Large-work design review before implementation. The integration specification
must address R1/R2, native-audio graph binding, runtime image verification and
shared experiment budget/recovery. It must not raise the old canary's global
attempt cap, synthesize approvals, enable an unqualified preset or reset funds.
