**Verdict: REWORK.**

**P is acceptable for this bounded benchmark**, provided the guarded live schema comparison remains mandatory before every acquisition’s first upload. A placeholder capture can authorize a paid cold start whose GPU runtime cannot start or whose real model files produce different enums. A live capture would discover that before sealing; P discovers it after spending boot time. Neither schema capture establishes successful inference. **This critique does not require alternative C.**

The push → predict using the registry digest → author → verify → sign sequence is sound. The image’s proposed provisioning-failure behavior is fail-closed. Both gateway copies and the transport’s world-agnostic flag layer are correctly identified. The remaining problems are below.

Code references are relative to `microdrama/src/microdrama/` in the reviewed worktree, HEAD `104b26b`.

**R5C-1 — BLOCKING — The readiness gate starts after an earlier cold-start refusal.**

Location: [T031-run-readiness-spec.md:68](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:68); `pipeline/experimental_world.py:176`; `rendering/pods.py:213`; `pipeline/benchmark_service.py:1270`.

`world.acquire()` calls `ensure_pod()`, which requires RUNNING state and an exposed endpoint. Pending hardware or image pulling raises `TransientProviderError` before the proposed post-acquire wait can run. The service then records terminal FAILED and sweeps. The stated A40 queueing behavior therefore cannot reach `BOOT_TIMEOUT`.

**Replacement:** “Boot handling covers positively identified pod warmup and endpoint discovery before `acquire` completes, then gateway/Comfy readiness. Retry owned reads against the same durable lease/pod; uncertain create outcomes retain H-2 reconciliation semantics. Test pending state and missing endpoint, asserting exactly one create.”

**R5C-2 — BLOCKING — The promised boot retries conflict with terminal failure handling.**

Location: [T031-run-readiness-spec.md:312](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:312); `pipeline/benchmark_service.py:1270`, `:334`; `migrations/0026_t031_benchmark_experiments.sql:111`.

`PolicyDenied PROVISION_FAILED`, or an ordinary timeout exception, reaches the generic handler that sets `execution_outcome=FAILED`. That outcome is set-once. A fresh quote cannot make the next `execute` admissible. The three-attempt limit also has no specified durable enforcement point.

**Replacement:** “Handle typed, pre-sample boot failures before generic terminal failure handling. Persist their incident and cleanup obligation without setting a sample/model failure outcome. Admit another acquisition only after canonical blockers clear. Record phase and attempt identity durably and enforce three attempts under the admission locks, preserving the same experiment, authorization and budgets.”

**R5C-3 — BLOCKING — Failed boots have no specified coverage carrier.**

Location: [T031-run-readiness-spec.md:79](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:79), `:312`; `pipeline/benchmark_service.py:2032`.

The SQL facts are correct: **coverage is mutable, and acquisition state has no CHECK**. The ownership rule is incomplete. Acquisition records live on its “first claimed sample,” while boot failures explicitly precede claiming. Cleanup then replaces the incident state with CLOSED/CLEANUP_PENDING/UNKNOWN. There is no defined surviving carrier for that attempt’s incident or timings.

**Replacement:** “Store acquisition records on a deterministic, already-prepared sample row without claiming it. Key records by acquisition ID so retries preserve every attempt. Atomically merge incident, timing and capture keys without replacing existing coverage; commit refusal evidence before cleanup.”

**R5C-4 — BLOCKING — The provisioning flag is not connected to actual request construction.**

Location: [T031-run-readiness-spec.md:55](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:55); `rendering/leases.py:682`; `rendering/pods.py:60`.

The real path constructs `PodCreateRequest` through `LeaseService._spec_for()` → `PodSpec.to_request()`. Neither reads the acquisition intent. Adding a default-False field, recording True in intent, and mapping True in transport leaves the composed create request False unless this bridge is built. RR-T4’s direct field-to-payload test can miss that.

**Replacement:** “Specify benchmark-scoped request construction that transfers the frozen provisioning flag into the actual `PodCreateRequest`. The benchmark create guard requires both intent and request to contain True before POST. Test through the composed acquisition path and captured RunPod payload.”

**R5C-5 — BLOCKING — Office-image reuse passes validators but can fail staging.**

Location: [T031-run-readiness-spec.md:142](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:142); `pipeline/experimental_world.py:740`, `:1290`; `rendering/pika_transport.py:241`.

The seal permits one asset in different roles; the conditional fallback is unnecessary. However, identity:A and outfit:A-office share a digest-derived upload key. Staging creates separate role rows, while the guard fetches one row by acquisition/key without role. It can select the already VERIFIED identity row and reject the outfit POST because that selected row is not UNKNOWN. The same applies to B.

An in-memory probe of the actual guard reproduced this refusal.

**Replacement:** “Support one verified byte upload reused by distinct semantic bindings, preserving exact role/subject receipts and checksum readback. Eliminate ambiguous key-only guard lookup. Exercise the authored eight-shot maps through real staging/binding, including office reuse and S08’s home outfit.”

**R5C-6 — BLOCKING — One `execute` does not finish a phase.**

Location: [T031-run-readiness-spec.md:236](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:236); `rendering/comfy_jobs.py:768`; `pipeline/benchmark_service.py:1243`.

A normal submit returns SUBMITTED. The service observes it, returns status, and the CLI exits successfully. Following step 11 with step 12 therefore reaches screening with only the first sample submitted, rather than three completed outputs. Full has the same issue.

**Replacement:** “After each phase’s initial execute, provide exact bounded `resume`/reconciliation commands and terminal-state checks. Advance screen to SCREEN_REVIEW with verified cleanup before Pass A; advance full to COMPUTE_COMPLETE. Stop on admission blockers or unresolved effects, preserving reconciliation-only handling.”

**R5C-7 — BLOCKING — Billing finality is needed before full or another boot attempt.**

Location: [T031-run-readiness-spec.md:243](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:243); `pipeline/experimental_world.py:312`; `pipeline/benchmark_service.py:2040`; `budget/billing.py:208`, `:449`.

Ordinary billing ingest records provider observations; it does not supply invoice verification. Watching status cannot perform that verification. After screen termination, pending financial finality leaves the acquisition CLEANUP_PENDING and retains STORAGE exposure. H-2 correctly blocks full admission. The same blocks boot retries. Postponing invoice finality until after full makes the printed sequence unexecutable.

**Replacement:** “After every acquisition’s verified termination, provide an executable per-pod billing-ingest and invoice/console-evidence verification procedure using the existing verifier, followed by sweep. Require cleared canonical blockers before another acquisition. Verified shutdown alone does not release all holds.”

**R5C-8 — BLOCKING — A healthy 25-minute wait lacks lease liveness maintenance.**

Location: [T031-run-readiness-spec.md:71](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:71); `rendering/leases.py:135`, `:1176`; `rendering/janitor.py:238`.

The default heartbeat timeout is five minutes. The proposed wait specifies polling but no heartbeat. An independent janitor can therefore terminate a healthy provisioning pod well before its 25-minute deadline. RR-T5 does not currently require this composition.

**Replacement:** “Maintain authorized lease liveness throughout boot without extending the hard deadline or reviving a fenced lease. Check deadlines before every request and after sleeps, and bound transport timeout by remaining time. Test a 25-minute boot with concurrent janitor sweeps.”

**R5C-9 — BLOCKING — Recovery must not inherit an expired initial boot deadline.**

Location: [T031-run-readiness-spec.md:69](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:69), `:76`; `pipeline/benchmark_service.py:2473`.

The instruction applies readiness waiting to recovery reads, but its deadline remains creation + 25 minutes. Consider a healthy full-phase pod at minute 40 with a newly submitted, recoverable prompt. A fresh recovery world can encounter an already-expired boot deadline and classify that acquisition as BOOT_TIMEOUT despite its valid source.

**Replacement:** “Persist successful initial readiness. Apply the boot deadline only to unfinished initial boot. Recovery of already-admitted work uses H-2’s existing source binding, read authorization and recovery deadlines; elapsed boot budget cannot reclassify recoverable work as boot failure.”

**R5C-10 — SHOULD-FIX — Placement (b) contradicts the no-sample failure contract.**

Location: [T031-run-readiness-spec.md:70](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:70), `:312`; `pipeline/experimental_world.py:690`.

The cited `_scope()` is a **sample job/PROMPT-hold scope**, not acquisition lease authorization. Placement (a) can conform through a narrowly guarded acquisition-read scope. Placement (b), even with sufficient expiry, has already claimed/materialized a sample whose reservation, request and acquisition links are set-once. It cannot also satisfy “no sample state” and uncomplicated boot retry.

**Replacement:** “Choose placement (a): no PROMPT reservation or sample materialization before readiness. Authorize only the two boot reads through exact acquisition/COMPUTE-hold/lease/pod linkage. Preserve the existing sample/operation guards for uploads and prompts.”

**R5C-11 — SHOULD-FIX — Boot arithmetic does not establish completion within four GPU-hours.**

Location: [T031-run-readiness-spec.md:314](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:314); `pipeline/benchmark_service.py:628`.

Six 25-minute boots consume 150 minutes, leaving **90 minutes for all 24 samples and shutdown**—about 84 minutes after six one-minute shutdown allowances. That permits roughly 3.5 minutes per sample on average, with throughput unproven. Furthermore, admission reserves the quote’s complete runtime plus shutdown margin against remaining aggregate time; a four-hour quote is refused even initially.

**Replacement:** “Three attempts is an upper bound, conditional on remaining canonical exposure, GPU time and deadlines. Size each acquisition’s runtime window against that remainder. Use measured screen throughput to report whether the remaining full run fits; do not promise completion from boot arithmetic alone.”

**R5C-12 — SHOULD-FIX — First-observe timing measures submission acknowledgement.**

Location: [T031-run-readiness-spec.md:82](/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md:82); `pipeline/benchmark_service.py:1241`; `rendering/comfy_jobs.py:768`.

The first observation normally contains SUBMITTED. Recording `full_job_ms` there produces a near-zero acknowledgement duration, not time to verified output. Sampler timestamps are also currently discarded by `PikaHttpClient.history()`.

**Replacement:** “Keep completion duration UNKNOWN until the first terminal observation with verified durable output; preserve that measurement across replay. Carry genuine sampler timing evidence through transport when available, otherwise export UNKNOWN. Test submission, multiple polls, completion and delayed recovery.”

Verification comprised static review and read-only in-memory validator/guard probes. No files were changed and no database or provider operations were performed.

