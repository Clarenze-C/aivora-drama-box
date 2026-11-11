**FIX-REQUIRED.** One reachable recovery defect and one invalid deadlock proof remain BLOCKING.

Reviewed `4e28514...7060e0212368c9a45ca7b2803be72bea8179c091`, covering F1–F5. HEAD matches `.scratch/gate/head.txt`; there are no tracked uncommitted changes. No tests, database operations, provider calls or writes were performed. `git diff --check` passed. The running gate was untouched.

The required diff against `45e4f2a` is **empty** for both `budget/service.py` and `rendering/leases.py`. Ruling 1’s canonical reversion is satisfied.

**HD-1 — BLOCKING — the fresh RECOVERY probe is never bound, allowing forced resolution of recoverable work.**

[benchmark_service.py:2978](/root/AIVORA/drama-box/.scratch/t031-gate-hcf/microdrama/src/microdrama/pipeline/benchmark_service.py:2978), `:2985`, `:2987`.

`resolve_sample` binds its CLEANUP world, then constructs a separate RECOVERY world and immediately calls `reconcile_unknown` through it. That new world has a fresh, unbound `PikaHttpClient`: construction at [experimental_world.py:1319](/root/AIVORA/drama-box/.scratch/t031-gate-hcf/microdrama/src/microdrama/pipeline/experimental_world.py:1319) does not bind an endpoint. Its first HTTP request therefore raises `EffectDenied` at `comfy_transport.py:205`.

The broad exception handler interprets that local composition failure as unrecoverability. With force, execution reaches `resolve_unknown_operation`.

Failure scenario: an accepted prompt remains discoverable by deterministic client ID, while its durable operation is UNKNOWN without `external_id`. The CLI’s fresh-world resolution path binds CLEANUP successfully, probes the unbound RECOVERY client, then force-transitions the operation to FAILED and finalizes it. Recoverable accepted work is discarded.

An in-memory probe executing the actual `resolve_sample` body produced:

```text
CLEANUP:bind
RECOVERY:probe bound=False
CLEANUP:OPERATOR-FAILED
finalize
```

The new expired-hold test hides this because its factory returns the same adapter for RECOVERY; see `test_t031_hcf_f4_r7_replay.py:180`.

**Fix:** bind the newly composed RECOVERY world to the owning acquisition before probing. Treat local binding/composition failures distinctly from evidence that work is unrecoverable. Prove force refusal using independently constructed, initially unbound clients.

**HD-2 — SHOULD-FIX — interval identity still changes when a reservation closes between posting and replay.**

[benchmark_experiments.py:927](/root/AIVORA/drama-box/.scratch/t031-gate-hcf/microdrama/src/microdrama/rendering/benchmark_experiments.py:927).

The normalizer chooses the receipt identity from the reservation’s **current** state. An interval posted while ACTIVE retains its original ACCRUAL identity. After closure, replaying that identical interval becomes a different `late:` ADJUSTMENT identity.

The canonical replay lookup consequently misses the existing charge, and its overlap check raises `Conflict("interval already attributed")`. The replay cannot advance `accrued_until`.

Failure scenario: an interval commits, the worker crashes before advancing `accrued_until`, settlement closes the reservation, and recovery retries that interval. The builder explicitly acknowledges this residual case, but it contradicts immutable replay identity.

The actual normalizer’s in-memory probe confirmed ACCRUAL → ADJUSTMENT, a different receipt UUID, and a changed provider receipt key. The new crash test closes the reservation **before both calls**, so it misses this transition.

I classify this SHOULD-FIX under the requested final-round threshold: the current live `RunpodRestProvider.usage` returns no interval receipts (`runpod_transport.py:542`), so I have not established this failure on the current paid route.

**Fix:** recover an already posted interval’s immutable identity before choosing a late identity; serialize the decision with posting/closure. Add the ACTIVE-post → crash → close → replay case.

**HD-3 — BLOCKING — the strengthened race test still accepts translated deadlocks and lock timeouts.**

[test_t031_h2b_p4_resolution.py:574](/root/AIVORA/drama-box/.scratch/t031-gate-hcf/microdrama/tests/unit/rendering/test_t031_h2b_p4_resolution.py:574), `:719`, `:725`.

`_deadlocks` recognizes only raw `psycopg.errors.DeadlockDetected`. The worker implementations use `Database.transaction`, which translates deadlocks and lock timeouts into `ServiceUnavailable`, a `MicrodramaError`.

The subsequent assertion accepts **every** `MicrodramaError`. Thus a worker deadlock or timeout can satisfy both assertions, while the final “no operations / acquisition UNKNOWN” assertions also remain true after rollback.

A probe using the actual production error translator confirmed:

```text
40P01 → ServiceUnavailable → deadlock check misses it → whitelist accepts it
55P03 → ServiceUnavailable → deadlock check misses it → whitelist accepts it
```

This meets the specified BLOCKING threshold for a proof that passes despite the defect it claims to exclude. It is a proof defect; I am not claiming a currently reproduced database deadlock.

**Fix:** whitelist specific expected admission refusals and reject `ServiceUnavailable`, including translated SQLSTATE `40P01` and `55P03`. Inject those translated failures and assert that the proof fails.

The remaining ruling checks are mixed:

- **Transaction inventory:** the helper now locks **A → L → D → S → R → O → uploads**. Acquisition, claim, gate and both sweep-finalization paths use it. It contains no billing advisory acquisition. `resolve_create` separately takes **account/categories → E → A → advisory → L**. `_observe`, terminal projection, activation, ambiguity writes and deadline recomputation retain separate lock sequences; `reserve_linked` retains its own sequence. Therefore ruling 4’s “one helper … every listed transaction” requirement is not fulfilled. The new `_shorten_recovery_deadline` transaction is also absent from the report’s inventory. I found no additional concrete paid-path lock cycle warranting BLOCKING.
- **Deadline recomputation:** the multiple-window consumption and shutdown-margin calculation is repaired. However, recomputation locks only the target A row, and both recovery paths bind/read the provider before recomputing (`benchmark_service.py:2136`, `:2480`). This remains partial against the required locking and read ordering.
- **HC-10 proofs:** the real wrapper and gate are now called, operation insertion is covered, and dedup counts are exact. However, the wrapper race queues the wrapper first behind an account holder (`test_t031_h2b_p4_resolution.py:632`), permitting orderly completion even with the historical wrapper inversion. AT-9’s `sweep_finalization_mid` still performs two completed sweeps without injecting a mid-finalization crash (`test_t031_h2b_p5_terminal.py:530`). F2’s L-lock test sets `lock_timeout` on the holder, without explicitly setting it on its worker connection.
- **S08:** it is now driven into the full phase and passed through the real binder with outfit B. Both S01 and S08 assert their own outfit hash and exclusion of the other. L-1/L-2’s missing bind proof is closed.
- **Existing assertions:** the invoice-tail additions, stricter fixture finality, durable success assets and prompt-history eviction are consistent with the binding rulings. They do not justify closing the remaining proof gaps.
- **CLI:** the non-ASCII SHA crash is fixed, but generation documents are still loaded before service construction and recovery. The builder’s substitution of soft validation for the binding recovery-first ordering leaves HC-11 partial.

The reported red summaries are consistent with the narrow F1–F5 regressions inspected. They were **not rerun**. Some F2 reds are missing-method/signature failures, and F4’s successful durable-output case is correctly identified as a pre-fix passing control. Neither establishes the broader properties still missing above.

| ID | Status | Evidence and proof assessment |
|---|---|---|
| HC-1 | **CLOSED** | `benchmark_experiments.py:108`; `benchmark_service.py:1797`, `:1864`. Invoice-pending U5 and EXPIRED-hold assertions distinguish the old early closure. |
| HC-2 | **PARTIAL** | `benchmark_experiments.py:865`, `:927`. Canonical reversion, final reuse and already-closed crash replay repaired; cross-close replay remains HD-2. |
| HC-3 | **PARTIAL** | `benchmark_service.py:2978`. Client-ID discovery/mode selection repaired; fresh-client binding remains HD-1. |
| HC-4 | **CLOSED** | `benchmark_service.py:2795`, `:2846`; `benchmark_experiments.py:371`. Slot/outcome repair and missing-asset negatives distinguish the old behavior. |
| HC-5 | **CLOSED** | `benchmark_service.py:495`, `:1020`, `:1303`; `comfy_jobs.py:732`. Live ownership checks reach control writes and first-send authorization. |
| HC-6 | **PARTIAL** | `benchmark_service.py:404`, `:2384`, `:2655`. L/S locking repaired at helper sites; universal-helper requirement and inventory remain incomplete. |
| HC-7 | **CLOSED** | `benchmark_experiments.py:638`. Transaction-core mode refusal added; inherited unrestricted behavior fails the new negative. |
| HC-8 | **CLOSED** | `benchmark_service.py:2485`. Non-BOUND exits persist grace and route exhausted episodes to sweep; the prior null-deadline behavior fails the new assertion. |
| HC-9 | **PARTIAL** | `benchmark_service.py:890`, `:2384`, `:2480`. Shortening and multiple-window arithmetic repaired; required lock/read ordering remains incomplete. |
| HC-10 | **PARTIAL** | `test_t031_h2b_p4_resolution.py:725`; `test_t031_h2b_p5_terminal.py:530`. Real implementations and exact counts improved; HD-3 and crash/fresh-world gaps remain. |
| HC-11 | **PARTIAL** | `benchmark.py:169`, `:187`, `:259`. Poisoned-SHA test distinguishes the old crash; literal recovery-first ordering remains unmet. |
| HC-12 | **CLOSED** | `benchmark_experiments.py:470`, `:1074`; `benchmark_service.py:3028`. Durable incident derivation survives closure/export; absent-field behavior fails the new tests. |
| HB-5 | **CLOSED** | `benchmark_service.py:2485`; HC-8. |
| HB-6 | **PARTIAL** | `benchmark_service.py:890`, `:2384`; HC-9. |
| HB-7 | **CLOSED** | `benchmark_service.py:1303`; `comfy_jobs.py:732`; HC-5. |
| HB-8 | **PARTIAL** | `benchmark_service.py:1104`, `:2384`; ownership repaired, HC-6 remains partial. |
| HB-9 | **PARTIAL** | `benchmark_service.py:404`, `:2230`; shared predicate improved, ruling 4 incomplete. |
| HB-10 | **PARTIAL** | `benchmark.py:169`, `:259`; HC-11. |
| HB-11 | **CLOSED** | `benchmark_experiments.py:638`; HC-7. |
| HB-12 | **CLOSED** | `benchmark_experiments.py:278`; `benchmark_service.py:1864`; HC-1. |
| HB-13 | **PARTIAL** | `test_benchmark_experiments.py:307`; financial-finality fixture repaired, fresh-world proof remains incomplete. |
| L-1 | **CLOSED** | `test_t031_h2b_lf_luna.py:456`, `:589`. S08 actually binds outfit B. |
| L-2 | **CLOSED** | `test_t031_h2b_lf_luna.py:589`. Both binds require their own asset and exclude the other. |
| HD-1 | **OPEN — BLOCKING** | `benchmark_service.py:2978`. Unbound fresh RECOVERY probe permits forced loss of recoverable work. |
| HD-2 | **OPEN — SHOULD-FIX** | `benchmark_experiments.py:927`. Receipt identity changes across reservation closure. |
| HD-3 | **OPEN — BLOCKING** | `test_t031_h2b_p4_resolution.py:725`. Translated deadlocks/timeouts pass the race assertions. |

**Verdict: FIX-REQUIRED.**

