# R5 Codex critique round 1 — GLM rulings (13 Nov 2026)

Input: `codex-r5-critique.md` (verdict REWORK; 9 BLOCKING R5C-1..9, 3 SHOULD-FIX R5C-10..12) against
`T031-run-readiness-spec.md` v0.2. Every ruling below is a **GLM ruling, Opus re-check Mon**.

**Verdict-level ruling.** Codex accepts **P (predicted schema)** for this bounded benchmark, provided the
guarded live schema comparison stays mandatory before every acquisition's first upload. The spec already
makes live verification decisive (R5c); it stays a hard gate. No change to the operator's P decision.

| Finding | Ruling | Reason (short) |
|---|---|---|
| R5C-1 | **ACCEPT replacement** | `ensure_pod()` requires RUNNING + endpoint before the post-acquire wait, so the spec's BOOT_TIMEOUT row was unreachable as written; warmup/endpoint discovery must precede `acquire` completing, retries ride the same lease/pod, uncertain creates keep H-2 semantics. |
| R5C-2 | **ACCEPT replacement** | `execution_outcome` is set-once and `PROVISION_FAILED` reaches the generic terminal handler, so the promised retries are impossible; typed pre-sample boot failures need their own incident/cleanup path without a sample outcome, and the three-attempt cap needs a durable enforcement point under the admission locks. |
| R5C-3 | **ACCEPT replacement** | Boot failures precede claiming, so "record on the first claimed sample" has no carrier; a deterministic prepared-but-unclaimed sample row keyed by acquisition ID preserves every attempt's incident/timings through cleanup. |
| R5C-4 | **ACCEPT replacement** | The real create path is `LeaseService._spec_for()` → `PodSpec.to_request()` and reads no acquisition intent, so a default-False composed request would silently defeat the flag; the guard must require intent **and** composed request True, tested through the captured payload. |
| R5C-5 | **ACCEPT replacement** | Codex reproduced the role-collision refusal in an in-memory probe of the real guard: digest-derived upload keys collide across identity/outfit roles; guard lookup must be role/subject-scoped, one byte upload reused by distinct bindings with per-role receipts. |
| R5C-6 | **ACCEPT replacement** | `execute` returning SUBMITTED means step 11 → step 12 would reach screening unfinished; each phase needs explicit bounded resume/reconciliation commands and terminal checks (screen → SCREEN_REVIEW before Pass A; full → COMPUTE_COMPLETE). |
| R5C-7 | **ACCEPT replacement** | Ordinary billing ingest records observations but does not verify invoices; without an executable per-pod verification procedure the acquisition stays CLEANUP_PENDING and correctly blocks full/boot retries — the printed sequence must include that procedure plus sweep. |
| R5C-8 | **ACCEPT replacement** | Default heartbeat timeout (5 min) vs a 25-min healthy wait means an independent janitor kills the pod; boot waits must maintain lease liveness, check deadlines before every request and after sleeps, and bound transport timeouts by remaining time. |
| R5C-9 | **ACCEPT replacement** | Recovery must not re-apply the initial boot deadline to already-admitted work at minute 40; persist successful initial readiness and use H-2's recovery deadlines for recovery reads. |
| R5C-10 | **ACCEPT placement (a)** | Placement (b) cannot conform: claiming/materializing a sample is set-once and contradicts the no-sample failure contract the spec itself carries; `_scope()` is a PROMPT-hold scope, not lease authorization. Technical conformance choice within the package spec — flagged for Opus re-check with the note that (b) is impossible, not merely worse. |
| R5C-11 | **ACCEPT replacement** | Six 25-min boots leave ~3.5 min/sample unproven; make three attempts a conditional upper bound against remaining exposure/GPU time, and report full-run fit from measured screen throughput instead of boot arithmetic. |
| R5C-12 | **ACCEPT replacement** | First observation is usually SUBMITTED, so `full_job_ms` there measures acknowledgement; completion duration stays UNKNOWN until the first terminal observation with verified durable output, preserved across replay; carry real sampler timing only when the transport preserves it. |

No finding is rejected and no acceptance test is weakened. Nothing here changes an operator decision
($8.00 envelope, P, the 12 Nov DECISIONS row).

**Apply:** fold all twelve replacements into the spec as **v0.3** (job `dramabox:r5-spec-v03`); the R5a–R5e
build brief follows against v0.3.
