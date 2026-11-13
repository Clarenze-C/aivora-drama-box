R5 spec v0.3 is committed. Per-finding report:

| Finding | Status |
|---|---|
| R5C-1 (readiness gate starts after cold-start refusal) | **applied** — §3 R5b "What boot handling covers": warmup/endpoint discovery before `acquire()` completes, owned-read retries on the same lease/pod, H-2 semantics for uncertain creates; §11; RR-T5 (pending + missing endpoint, exactly one create) |
| R5C-2 (retries conflict with terminal failure handling) | **applied** — §3 R5b "Typed pre-sample boot failures": handled before the generic handler, no sample/model outcome set, durable attempt identity under admission locks; §2 seam wording; §10; RR-T13 |
| R5C-3 (no coverage carrier for failed boots) | **applied** — §3 R5b landing zone: deterministic prepared-but-unclaimed sample row, keyed by acquisition ID, atomic merge, refusal evidence committed before cleanup; §12 glossary; RR-T14 |
| R5C-4 (flag not connected to request construction) | **applied** — §3 R5a: transfer through `_spec_for()` → `to_request()`, create guard requires intent ∧ request True before POST; §6 R5a row; RR-T4 (composed path, captured payload) |
| R5C-5 (office reuse fails staging) | **applied** — §3 R5d: one verified upload reused by distinct bindings, role/subject-scoped guard lookup replacing the key-only fetch (`experimental_world.py:1290`); RR-T15 (eight-shot maps, office reuse, S08 home outfit) |
| R5C-6 (one execute ≠ phase completion) | **applied** — §7 steps 11-12/15-16: bounded `resume`/`reconcile` (verified to exist at `benchmark_service.py:1470/:2058`, terminal states at `:1463`) to SCREEN_REVIEW / COMPUTE_COMPLETE; RR-T16 |
| R5C-7 (billing finality before full/retry) | **applied** — new §3 R5f + G7: per-pod ingest + `verify_invoice_period` from evidence sha (existing verifier, `canary.py:1300-1335` pattern, new thin `t031_billing_verify.py`) + sweep; §7 steps 14/17/19; §8; RR-T17 |
| R5C-8 (no lease liveness during 25-min wait) | **applied** — §3 R5b "Lease liveness during boot": heartbeat maintained (5-min default vs janitor sweep cited), deadline checks before every request/after sleeps, transport timeout bounded; RR-T5 |
| R5C-9 (recovery inherits expired boot deadline) | **applied** — §3 R5b "Boot deadline and recovery": persisted initial readiness, deadline only for unfinished initial boot, H-2 recovery deadlines; RR-T5 (minute-40 case) |
| R5C-10 (placement (b) contradicts no-sample contract) | **applied** — §3 R5b placement (a) chosen with acquisition/COMPUTE-hold/lease/pod linkage; §8 records (b) as impossible; RR-T5 |
| R5C-11 (boot arithmetic ≠ completion) | **applied** — §4 note, §10 attempt-limit rewrite, §11 "Completion fit": 3 attempts a conditional upper bound, runtime windows sized against the remainder (`benchmark_service.py:627-631`), fit reported from measured screen throughput; caps unchanged |
| R5C-12 (first-observe timing = acknowledgement) | **applied** — §3 R5b `t031_timings`: `full_job_ms` UNKNOWN until first terminal observation with verified durable output, preserved across replay, sampler timing carried when transport preserves it; RR-T6; §9 CON-N7 updated |

No finding was BLOCKED — none contradicted the operator decisions ($8.00 envelope, P, the 12 Nov DECISIONS row, T031-authorization all untouched; no acceptance row weakened).

- **Commit:** `980eb19` on `feat/microdrama-m0-m4` (only the spec file staged; 248 insertions / 51 deletions)
- **v0.3 line count:** 560 lines

Every new `file:line` cite the replacements introduced was re-verified in the read-only worktree at `104b26b` before being written in (the header notes this). The rulings' "Apply" note expects the R5a–R5f build brief to follow against v0.3.
