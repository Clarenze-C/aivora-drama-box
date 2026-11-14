**A0-D FIX4: ALL FINDINGS ADDRESSED**

- **AD7-1** (SHOULD-FIX) — ADDRESSED at `0f48aaa`: `_done` validates completion against the invocation's persisted frozen identity (configured identity only as fallback); the A→B test now runs through successful completion. Red: op settled `FAILED` on the honest identity-A result.
- **AD7-2** (BLOCKING) — ADDRESSED at `8a0c5ae`: each append-only attempt row pins its COMPLETE result evidence (entry + the payload the record exposes for that attempt, absence included), so a doctored historical replay below `prior_max` is a Conflict; the fake gateway gained durable-result fidelity and one round-2-era fixture was repaired to the faithful status shape. Red: 4× `DID NOT RAISE Conflict`.
- **AD7-3** (BLOCKING) — ADDRESSED at `51a7337`: `_maybe_complete_requalify` requires internally created, hash-bound probe authorization before any receipt — every settlement path funnels through it, recovery included; the squatter still settles DONE but writes no receipt and clears nothing. Red: receipt existed with `authorized=false`.
- **AD7-4** (SHOULD-FIX, regression) — ADDRESSED at `15ce674`: probe authorization binds to the state-recorded `probe_request_hash` (only `_ensure_requalify_probe` writes it) plus content self-consistency, so a `--requalify-model` change no longer strands a queued probe; re-arm re-freezes under the new config, and AD6-8c stays shut. Red: `_is_authorized_probe` was `False` after the config change.

Verification on tip `15ce674` (4 commits on `a4e9913`, nothing pushed): `tests/unit` **3222 passed** (incl. `tests/unit/llm` 118 with the 6 new tests), `tests/integration/llm_gateway` **80 passed** (real systemd; the AD5-10 e2e probe still earns its receipt), `make lint` clean before every commit. No full `make check`/`make pilot`, per the brief — gated to the orchestrator after R5.

Report: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0d-fix4-REPORT.md`
