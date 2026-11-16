**FIX-REQUIRED** — reviewed `6bcdbfa..c02e918`. Tracked `git diff HEAD` is empty.

Paths below are relative to `microdrama/`.

- **R5V-1 — FIXED** — `src/microdrama/pipeline/experimental_world.py:242`: durable readiness bypasses boot timing; the new minute-40 test uses an existing acquisition through public resume/reconcile.
- **R5V-2 — FIXED** — `src/microdrama/pipeline/experimental_world.py:260`: acquisition requests share the boot deadline; exhaustion becomes typed `BOOT_TIMEOUT`.
- **R5V-3 — FIXED** — `src/microdrama/pipeline/benchmark_service.py:773`: incident and cleanup obligation commit atomically; persisted failures route through cleanup.
- **R5V-4 — PARTIAL** — `tests/unit/pipeline/test_t031_r5c_seal.py:43`: discovery still uses a stand-in loader. RR-T3 remains blocked; complete pinned-runtime discovery and retain verifiable final gate receipts before acceptance.
- **R5V-5 — FIXED** — `src/microdrama/pipeline/experimental_world.py:453`: permanent HTTP failures receive immediate typed cleanup; tolerated failures keep waiting.
- **R5V-6 — FIXED** — `tools/t031_billing_verify.py:83`: target pod resolves through its experiment acquisition to its original authorization.
- **R5V-7 — FIXED** — `tools/t031_results.py:99`: unallocated sample costs stay blank; the aggregate is reported separately.
- **R5V-8 — FIXED** — `src/microdrama/pipeline/benchmark_service.py:1578`: timing uses the result operation; terminal sampler evidence persists and is recovered during finalization.
- **R5V-9 — PARTIAL** — `tools/t031_prepare_run.py:377`: asset identities/object keys and rights expiry/disclosures remain unchecked. An in-memory replay probe accepted all that drift; compare these frozen fields too.
- **R5V-10 — PARTIAL** — `tools/t031_prepare_run.py:169`: valid PCM metadata is derived, but payload validation and failure recovery remain defective below.

**R5W-1 — SHOULD-FIX** — [t031_prepare_run.py:169](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/tools/t031_prepare_run.py:169): chunk bounds are unchecked. A two-second PCM payload with an oversized data header is accepted as 100 seconds; valid unsigned eight-bit PCM is labelled `pcm_s8le`. Validate container/chunk lengths and framing, correct codec naming, and add malformed-payload tests.

**R5W-2 — SHOULD-FIX** — [t031_prepare_run.py:509](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/tools/t031_prepare_run.py:509): WAV validation occurs after registration commits. A malformed first voice leaves the account and six image assets registered; correcting the inputs then produces “stored asset bytes drifted.” Validate all inputs before writes, or make registration atomic; test correction followed by retry.

Independent checks passed: contracts, lint, formatting, diff whitespace, and in-memory probes. PostgreSQL suites were not rerun under read-only constraints. No provider calls or file changes were made.

