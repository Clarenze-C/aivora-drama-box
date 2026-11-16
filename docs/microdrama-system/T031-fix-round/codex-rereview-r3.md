**Verdict: FIX-REQUIRED.** CN2-1 through CN2-4 and H-1 are closed. H-2 is partial: recovery methods exist, but the default recovery path remains broken, and operator resolution has a race that can release protection for an existing pod.

Reviewed exactly **`d971435...628fe5b`**, six GLM commits across 17 files. The checkout matches the requested endpoint. No files were written, no external requests were made, and no integration suite was run. The native harness base and later builder commits were excluded.

| Finding | Result | Re-run evidence |
|---|---|---|
| **CN2-1** | **CLOSED** | The Decimal boundary returns ceiling total **4 µUSD**, components **(2, 1, 1)**, without crashing. A genuine discrepancy remains mismatched. |
| **CN2-2** | **CLOSED** | Through the real urllib transport, an HTTP 400 containing the unlabelled synthetic Comfy token becomes `[REDACTED]`. The formatted traceback is clean; the body read remains bounded to **8,192 bytes**. |
| **CN2-3** | **CLOSED** | An in-memory execution of the real recorder opens ownership in the binding transaction. Independent janitor cleanup preserves that interval and also heals a missing interval before stop/termination. |
| **CN2-4** | **CLOSED** | A real-transport probe recorded only the initial GET at `t=0`, timeout **1 second**. After it advanced the clock to `t=2`, the nested POST was refused before `urlopen`. A **0.1-second** remainder produces a **0.1-second** timeout; cleanup reset restores the default. |

**H-1: CLOSED.** `acquire()` now calls `bind_pod_endpoint(pod.pod_id, pod.endpoint_url)`. The `hasattr` escape is gone. My probe successfully bound the real `PikaHttpClient`. The added default-factory test also constructs that real client and exercises its actual signature; its policy bypass is explicitly limited to testing composition. I did not run that database-backed test.

**H-2: PARTIAL against §E.** Token-based create adoption requires a positive match, and listing absence does not automatically become `NO_CREATE_PROVEN`. Prompt reconciliation uses durable prompt IDs or adopts one through queue/history using the deterministic client ID; the new reconciler contains no prompt resubmission. Those are correct foundations. The following defects prevent acceptance.

**CN3-1 — BLOCKING — Default prompt reconciliation has no usable recovery composition**

Location: [benchmark_service.py:713](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark_service.py:713), with CLI wiring at [benchmark.py:208](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark.py:208).

After an ambiguous prompt, a fresh CLI invocation reconstructs a world whose Comfy client is unbound. `_reconcile_slot_sample()` calls `world.comfy.reconcile_unknown()` directly, without binding that client to the sample’s acquisition. Using the real default factory and real Pika client, I reproduced:

```text
the Comfy endpoint is not bound; it is derived from the leased Pod
```

There are two further obstacles on this same path:

- CLI `reconcile` supplies **`store=None`**, because object-store construction excludes the new command. Successful output recovery therefore lacks its durable destination.
- The ambiguity handler already calls `sweep()`, whose real cleanup terminates the pod. Its Comfy history and output endpoint cannot subsequently serve recovery. The composed tests retain a separate fake Comfy server after cleanup, concealing this problem.

**Fix:** provide an explicit recovery composition bound to the original acquisition and durable object store. Attempt bounded history/output recovery before destructive cleanup. Once termination has removed that recovery source, retain ambiguity for audited resolution rather than assuming the fake-server recovery remains available.

**CN3-2 — BLOCKING — Normal execute/resume bypasses the new reconciliation gate**

Location: [benchmark_service.py:291](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark_service.py:291).

The new branch runs only when `_advance_owned()` sees `NEEDS_RECONCILIATION`. However, `resume()` calls `execute()`, which first overwrites that state with `SCREEN_RUNNING` or `FULL_RUNNING`.

A sequencing probe starting in `NEEDS_RECONCILIATION` confirmed that `_advance` receives `SCREEN_RUNNING`; the new reconciliation branch is bypassed.

Concrete consequence: after ambiguity cleanup leaves an acquisition `CLEANUP_PENDING` with a released lease, resume selects it and calls `acquire()`. `ensure_pod()` rejects the terminal lease, and the coordinator’s general exception handler records a terminal experiment failure. If the acquisition has already closed, resume can admit another acquisition before resolving the occupied sample slot.

**Fix:** reconcile before changing execution state or admitting acquisition work. Gate admission on durable unresolved operations and dispatch-slot contents, independently of the experiment’s status label.

**CN3-3 — BLOCKING — Operator create resolution can free the slot and storage hold after a pod becomes known**

Location: [benchmark_service.py:786](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark_service.py:786).

`resolve_create()` performs its podless check, billing resolution, and final acquisition/storage updates in separate transactions. The final transaction locks the acquisition but never rechecks the lease binding or a contradicted resolution.

Concrete interleaving:

1. The initial check finds no attached pod.
2. Billing records the audited podless resolution.
3. Janitor late adoption binds P1.
4. The final transaction still writes `NO_CREATE_PROVEN` and releases storage protection.

An in-memory sequencing probe produced:

```text
acquisition_state = NO_CREATE_PROVEN
pod_id             = late-P1
storage_released   = True
```

This frees the acquisition index slot and excludes that acquisition from aggregate GPU-time accounting despite a known pod. The initial attached-pod refusal does not protect this interleaving.

**Fix:** coordinate settlement, resolution state, slot release, and hold release under shared transactional locking with lease adoption. Recheck the pod binding and contradiction state before releasing protection. Later contradictions must also block admission until the discovered resource is safely reconciled.

**CN3-4 — SHOULD-FIX — Reconciliation requires current generation eligibility**

Location: [benchmark_service.py:611](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark_service.py:611).

The new recovery command constructs `_world(..., cleanup_only=False)`. Consequently, it neither reloads the recorded authorization/quote automatically nor permits recovery after their eligibility expires.

Real-factory probes reproduced both refusals:

```text
experiment world needs a durable seal, recorded authorization and acquisition quote
benchmark authorization or rights deadline has expired
```

This conflicts with the contract’s allowance for reconciliation using the existing attested world after quote, authorization, or rights expiry.

**Fix:** reconstruct an identity-checked recovery world from durable authorization and acquisition records. Permit scoped reconciliation/readback while keeping create, upload, and prompt dispatch denied.

**CN3-5 — SHOULD-FIX — Interrupted sample resolution cannot replay cleanly**

Location: [benchmark_service.py:862](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/pipeline/benchmark_service.py:862), with the retry refusal at [comfy_jobs.py:1039](/root/AIVORA/drama-box/.scratch/t031-review-r3/microdrama/src/microdrama/rendering/comfy_jobs.py:1039).

Operation resolution commits before `_observe()` finalizes the sample and frees its slot. A crash between them leaves a terminal operation behind an occupied dispatch slot.

I reproduced that boundary. Retrying `resolve` refuses because the operation is no longer UNKNOWN. Calling `reconcile` then changes the experiment to `SCREEN_RUNNING` while leaving `S01-R1` in the slot: its detection and projection paths handle only UNKNOWN operations.

**Fix:** make audited resolution replayable and let reconciliation project already-terminal operations into unfinished samples and release their slots without acquiring another pod. Commit the audit and operation transition atomically.

The operator path therefore **can release protection for an existing pod through CN3-3**. In the uncontended case, create resolution records actor, reason, evidence hash, and settlement, and refuses an already attached pod. Evidence remains an operator attestation; the code validates its shape, not its contents. Prompt resolution frees the slot on uninterrupted completion, but CN3-5 breaks crash recovery.

Test assessment: no new `skip` or `xfail` markers were introduced. The billing conservation grid and real-signature test provide useful coverage. H-2 coverage is insufficient: it calls `_advance()` directly, injects an existing adapter, and preserves fake Comfy state across cleanup. The cleanup fixture also removes two unconditional assertions and accepts stop verification where production requires termination. Its late-listing fixture manufactures a pod through a fake create inside `find_pods()`, so it does not independently establish the claimed no-second-create behavior.

**Validation:** 14 existing regression cases passed when invoked directly in memory, alongside the production-class and sequencing probes described above. `git diff --check` passed. Full-gate results were not rerun or treated as proof of live readiness.

