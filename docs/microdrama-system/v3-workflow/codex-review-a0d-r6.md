**Verdict: FIX-REQUIRED.** Reviewed `15ce674...1e43b70`, scoped to AD8-1/2 and defects introduced by their fixes. No files changed.

- **AD8-1 — CLOSED:** [step.py:225](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:225). Both raw quota fields and both concurrency spellings now participate in the evidence hash, including presence. Additions, removals and changed reset timing produce different hashes. No further fix required.

- **AD8-2 — PARTIAL. AD9-1, SHOULD-FIX — interrupted repair can launch stale prompt bytes:** [gateway.py:1429](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:1429). Cancel/rearm works uninterrupted, but `repaired` exists only in memory. With unchanged configuration, interrupt repair after replacing `request.json` but before replacing `prompt.txt`. On restart, the persisted request hash already equals the current hash, so requalification skips the remaining replacements, binds the request and launches using the stale prompt file.

  **Reproduction:** seeded a marked legacy probe with a self-consistent doctored request and matching foreign prompt; injected failure before prompt replacement. After restart, authorization and `pump()` both returned true, and the captured launch consumed the foreign prompt. The uninterrupted control consumed the correct probe prompt.

  **Fix:** persist repair intent before cancellation, require all request/prompt/schema replacements to complete durably before binding and rearming, and resume incomplete repairs after restart. Add fault-injection coverage at those write boundaries.

The four reported deviations:

1. **Both concurrency spellings:** accepted; each spelling is evidence.
2. **Cancel/rearm:** sound choice over adopting legacy bytes, but incomplete until AD9-1 is fixed.
3. **Cross-version hash vocabulary break:** accepted under the stipulated pre-production exception. Affected older rows retain incompatible replay hashes.
4. **Launched-ledger recovery coverage:** accepted; launched probes remain outside cancellation repair and earn no receipt before authorized rearming.

Verification: **17 direct hash assertions passed; all four new probe cases passed with memory-backed files and mocked systemd; interrupted-repair reproduction confirmed AD9-1; `git diff --check` clean.** PostgreSQL/systemd suites and full gates were not rerun; their totals remain builder-reported.