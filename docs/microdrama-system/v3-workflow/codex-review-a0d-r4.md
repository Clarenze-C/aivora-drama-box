**Verdict: FIX-REQUIRED.** Reviewed `b84a397...a4e9913`, scoped to AD6-1–10 and regressions from their fixes. No files changed.

- **AD6-1 — PARTIAL. AD7-1, SHOULD-FIX:** [step.py:1003](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:1003). Frozen identity A now survives replay after configuration changes to B, but normal DONE validation still expects B. A valid A result therefore settles `FAILED/INVALID_OUTPUT`. **Fix:** validate completion against the frozen call’s identity; extend the A→B test through successful completion.

- **AD6-2 — CLOSED:** [gateway.py:1027](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:1027). Both non-live classifications consult durable results. Targeted probes produced `SUCCEEDED` with a valid result and `UNKNOWN` without one.

- **AD6-3 — CLOSED:** [result_validation.py:199](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/result_validation.py:199), [gateway.py:393](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:393). Omitted properties default to empty; recursive equality distinguishes nested booleans from numbers. Both twins pass the validator tests.

- **AD6-4 — CLOSED:** [cancel_outbox.py:91](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/cancel_outbox.py:91), [reconciler.py:328](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/reconciler.py:328). DONE recovery uses the persisted frozen identity ahead of current configuration.

- **AD6-5 — PARTIAL. AD7-2, BLOCKING:** [step.py:399](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:399). Complete result comparison still depends on the latest invocation mirror. After attempts 1 and 2 settle, replaying attempt 1 with a changed `cli_version` raises no Conflict: its number differs from `prior_max`, and historical payload processing compares only quota evidence. **Fix:** persist immutable complete result evidence per attempt and compare historical replays, including field absence.

- **AD6-6 — CLOSED:** [step.py:350](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/step.py:350). The stale result is attributed to its named attempt; the later cancellation derives its outcome from its own entry.

- **AD6-7 — CLOSED:** [cancel_outbox.py:148](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/src/microdrama/llm/cancel_outbox.py:148). A missing record is skipped explicitly, allowing the sweep to continue.

- **AD6-8 — PARTIAL**, with two issues:
  - **AD7-3, BLOCKING:** [gateway.py:1436](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:1436). Receipt generation still trusts the probe UUID without checking internal authorization. Recovering a pre-reservation ordinary RUNNING ledger at that UUID reproduced `authorized=false`, receipt written, and quarantine cleared. **Fix:** require internally created, hash-bound probe authorization before issuing a receipt, including during recovery.
  - **AD7-4, SHOULD-FIX — regression:** [gateway.py:1356](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:1356). Changing `requalify_model` while a genuine probe is queued invalidates authorization. Requalification leaves it `ACCEPTED`, while every pump returns false. **Fix:** preserve authorization for its frozen request, or safely cancel and rearm the never-launched probe when configuration changes.

- **AD6-9 — CLOSED:** [gateway.py:1269](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:1269). Recovery examines every recorded violation. Targeted probes retained an uncovered newer violation and cleared only when all epochs were covered.

- **AD6-10 — CLOSED:** [gateway.py:1451](/root/AIVORA/drama-box/.scratch/a0d-gateway/microdrama/deployment/llm-gateway/gateway.py:1451). Receipt-write failure returns before clearance; the targeted probe retained both quarantine and its latch.

Verification: **36 validator tests passed**; `git diff --check` clean. Additional in-memory probes reproduced AD7-1–4. PostgreSQL/systemd suites and full gates were not rerun in the read-only sandbox. AD6-GATE-1 was not reopened.