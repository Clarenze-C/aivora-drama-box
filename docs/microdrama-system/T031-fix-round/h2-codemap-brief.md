# Fact-gathering for the H-2 recovery spec (read-only code map, no opinions)

The orchestrator will write a spec for the T031 benchmark's recovery and reconciliation
subsystem. It needs a precise, compact map of the current code. **Report facts only**:
no design advice and no review verdict. Keep it tight. Quote code only where a line
matters, with `file:line`.

Checkout: `/root/AIVORA/drama-box/.scratch/t031-review-r3` (detached `628fe5b`).
Python sources are under `microdrama/src/microdrama/`. Background (skim):
`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-rereview-r3.md`
(CN3-1..CN3-5).

## Produce, in this order

1. **Contract text, verbatim.** Quote the reconciliation, recovery and expiry sections of
   `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md`: §E, plus
   any § on quote, authorization or rights expiry, and on billing finality (§G). Copy
   the clauses verbatim, with their headings.
2. **State machines.** List every state and every transition (with the function and line
   that writes it) for:
   - `benchmark_experiments.execution_state`
   - `benchmark_acquisitions.state`
   - benchmark samples and their slot
   - `benchmark_dispatch_slots`
   - `provider_operations.state` (as used by the benchmark)
   - `pod_leases.lease_state` (as touched by the benchmark)

   Note which writes share one transaction.
3. **Call graph, entry points down to provider effects.** Cover CLI commands
   (`pipeline/benchmark.py`: execute, resume, reconcile, resolve, sweep, preflight) →
   `BenchmarkService` methods → world/adapter (`pipeline/experimental_world.py`) →
   leases / pods / Comfy jobs. Mark each provider effect (pod create, pod
   stop/terminate, prompt POST, upload, history/queue/view GET).
4. **Transaction boundaries.** For `execute`, `resume`, `_advance`, `_advance_owned`,
   `reconcile`, `_reconcile_slot_sample`, `resolve_create`, prompt resolution,
   `_observe` and `sweep`, plus the ambiguity handler: list each
   `db.transaction()` block, the rows it locks (`FOR UPDATE`), what it writes, and any
   provider call made between transactions.
5. **World composition.** How `build_experiment_world` / `_world(...)` composes for
   execute vs `cleanup_only` vs reconcile. What it requires: seal, authorization, quote,
   rights deadline, object store. When and how the Comfy client is bound to a pod. What
   a fresh CLI process has available.
6. **Existing canonical recovery primitives** the benchmark could reuse:
   - `rendering/leases.py`: janitor adoption, `resolve_podless_create`, storage ownership
     open/close/heal;
   - `rendering/pods.py` `reconcile_by_token`;
   - `rendering/comfy_jobs.py` `reconcile_unknown` (and what it needs bound);
   - the canary's operator resolution path in `pipeline/canary.py`.

   Give one line each: signature, preconditions, locking, effects.
7. **Holds and money.** Which budget holds exist per acquisition and per sample
   (compute, storage, prompt, cleanup), and when each is placed, retained, released or
   settled, with function and line. Note where release currently happens on the
   recovery and resolution paths.
8. **Tests.** List the existing tests that cover reconciliation, resolution and resume,
   one line each: file::name, what it asserts, and whether it uses fakes that survive
   cleanup or call `_advance` directly.

## Constraints

- Read-only sandbox: no file writes, no `systemd-run`, no test suites, no network.
- Put the whole map in your final message. Aim for under about 450 lines.
