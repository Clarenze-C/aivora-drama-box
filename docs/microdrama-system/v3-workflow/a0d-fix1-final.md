**A0-D fix round 1 complete** — all 13 findings closed, red→green per finding, three commits on `ea1cc10` (tip `6974d5a`, nothing pushed, no test units left loaded):

- **AD-1 CLOSED** — complete frozen request through the real A0-R1 interface (prompt file + model/budget/deadline/schema flags), accept refuses incomplete requests, settlement binds the policy identity; the shim now enforces the exact CLI interface
- **AD-2 CLOSED** — canonical UUIDs required before every ledger lookup + realpath containment; `/etc`-class IDs refused before any write
- **AD-3 CLOSED** — invocation id recovered through `llm_invocations.operation_id` for reconciliation *and* cancellation; tests model the real lost-ack + unreachable-GET condition
- **AD-4 CLOSED** — settled recovery finishes under the reconciler's lease (WaitExternal / correctly-timed deferral / Failed-CANCELLED); no janitor LEASE_EXPIRED at max attempts, quota deferral timing and attempt accounting kept
- **AD-5 CLOSED** — every reconciler mutation is one fenced transaction (job lock → lease re-verify → op settle → outcome); lease lost ⇒ Conflict, nothing written; two-connection janitor-storm race test on real PostgreSQL
- **AD-6 CLOSED** — the §5.7 gate is admission-only; red health still settles FAILED→LlmBlocked, outages keep the connect-level deferral path
- **AD-7 CLOSED** — isolation quarantine persisted qualification-bound, restored before serving, enforced in `pump()`, cleared only by identity-bound `POST /v1/requalify`
- **AD-8 CLOSED** — inspection failure ≠ absence (`SystemdInspectionError`); ambiguous launches reconciled by deterministic unit name; uninspectable work stays blocking; no false cancel confirmations
- **AD-9 CLOSED** — shared envelope+integrity+identity+frozen-schema validation across step, reconciler, adoption and the gateway reader (twin stdlib implementation, corpus cross-checked); `{}` vs required `line` is never SUCCEEDED
- **AD-10 CLOSED** — every settled attempt row persisted with conflict-rejecting evidence hashes, plus `quota_observations` per attempt with readings
- **AD-11 CLOSED** — the completion race reconciles the authoritative DONE/REFUSED answer: op settles, job stays cancelled, content discarded, nothing in flight forever
- **AD-12 CLOSED** — the reconciler CLI opens its pool
- **AD-13 CLOSED** — gateway UNKNOWN outranks the existing-record row: PENDING_SUBMIT+UNKNOWN goes straight to the operator

Green lines: `tests/unit/llm` 62, `tests/integration/llm_gateway` 53, regression sweep 1406 + 162, `make lint` clean per commit. Two monolithic full-unit background sweeps were killed at the background time limit (reported in the report; chunked + targeted runs are the recorded coverage). Six documented deviations, each with its reason — the notable ones: the AD-9 twin validators (the gateway cannot import the package, §4.1) and AD-2's `/etc` case proven green-only (the pre-fix gateway would really have written to `/etc` on this host).

Report: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0d-fix1-REPORT.md`
