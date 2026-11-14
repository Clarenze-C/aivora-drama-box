**FIX-REQUIRED** — reviewed the complete `104b26b..6bcdbfa` range against spec v0.3 and its rulings.

1. **R5V-1 — BLOCKING — Completed boot is timed out during resume.**  
   [experimental_world.py:240](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/src/microdrama/pipeline/experimental_world.py:240) applies the initial boot deadline before checking persisted readiness. An offline probe with `cold_start_ms` already recorded at minute 40 raises `BOOT_TIMEOUT`. The minute-40 test instead advances time before creating the full-phase pod.  
   **Fix:** bypass initial boot timing throughout `acquire()` once readiness is durable; test a genuinely existing full-phase acquisition through resume/reconcile. **RR-T5/T16; R5C-9.**

2. **R5V-2 — BLOCKING — Deadline exhaustion can make a pre-sample boot failure terminal.**  
   [experimental_world.py:371](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/src/microdrama/pipeline/experimental_world.py:371) checks time before the ready poll but immediately starts `/object_info` afterward. If the first read consumes the remainder, the transport raises `EffectDenied`; the generic handler sets the experiment outcome to FAILED. Confirmed offline. The post-ensure provider GET also sits outside the boot request bound.  
   **Fix:** bound the complete initial acquisition path, recheck between requests, and classify boot-budget exhaustion as typed `BOOT_TIMEOUT` before sample admission. **RR-T5/T13; R5C-2/8.**

3. **R5V-3 — BLOCKING — Persisted boot failure does not guarantee cleanup after interruption.**  
   [benchmark_service.py:768](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/src/microdrama/pipeline/benchmark_service.py:768) commits incident and state separately, then suppresses sweep failures. With a live lease, neither `unresolved_items()` nor `_needs_finalization()` recognizes `PROVISION_FAILED`/`BOOT_TIMEOUT` as cleanup owed. Offline probes return no blockers and `False`, respectively.  
   **Fix:** atomically persist the incident and a cleanup obligation under the existing ownership/lock rules; route these states exclusively through cleanup until verified. Test interruption before sweep and failed shutdown. **RR-T13/T14; R5C-2/3.**

4. **R5V-4 — BLOCKING — Required acceptance evidence remains incomplete.**  
   The [build report:43](/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/r5-build-REPORT.md:43) explicitly leaves RR-T3 blocked. RR-T7’s test constructs enum listings by appending manifest names, rather than exercising placeholder discovery in the pinned runtime. No HEAD-specific `make pilot` receipt was supplied.  
   **Fix:** complete the rebuilt-image CPU hash comparison, actual offline placeholder smoke, and pilot receipt before accepting **RR-T3/T7/T11**.

5. **R5V-5 — SHOULD-FIX — Readiness retries permanent HTTP failures.**  
   [experimental_world.py:394](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/src/microdrama/pipeline/experimental_world.py:394) converts every `ProviderError`, including HTTP 401/403, into another paid wait. An offline 401 probe returns `UNREACHABLE`.  
   **Fix:** retry the specified tolerated statuses and connection failures; immediately classify other failures through typed pre-sample cleanup. Apply the same distinction to `boot_object_info()`. **RR-T5/T13.**

6. **R5V-6 — SHOULD-FIX — Billing wrapper lacks acquisition-specific provenance.**  
   [t031_billing_verify.py:81](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/tools/t031_billing_verify.py:81) takes the latest experiment authorization and forwards an arbitrary pod ID without checking its acquisition. It can target another experiment’s pod or choose a different account from the target acquisition’s original authorization.  
   **Fix:** resolve experiment → target pod/lease → acquisition authorization before invoking the unchanged verifier. Add foreign-pod and differing-authorization tests. **RR-T17; R5C-7.**

7. **R5V-7 — SHOULD-FIX — Results repeat the entire bill on every sample.**  
   [t031_results.py:76](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/tools/t031_results.py:76) copies experiment-level `billed_micro_usd` into all 24 rows. A 123,456 µUSD export produces 2,962,944 µUSD across those rows.  
   **Fix:** leave unallocated sample costs unknown and report the aggregate separately; use sample costs only when supported by an allocation. **RR-T10.**

8. **R5V-8 — SHOULD-FIX — Recovery can permanently lose available timings.**  
   [benchmark_service.py:1558](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/src/microdrama/pipeline/benchmark_service.py:1558) looks up duration using the sample’s old `operation_id`, which can still be NULL when recovery discovers a successful operation. Confirmed offline: a valid result operation produces a `(None,)` lookup and no timing write. Sampler timing also exists only in the transient completion return.  
   **Fix:** use the verified result operation ID and persist sampler evidence with terminal completion so replay survives interruption before sample projection. **RR-T6; R5C-12.**

9. **R5V-9 — SHOULD-FIX — Registration replay does not enforce the promised frozen fields.**  
   [t031_prepare_run.py:216](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/tools/t031_prepare_run.py:216) compares digest sets, broad state/provenance, rights count and preset presence. A probe with a one-µUSD account cap and wrong asset kinds still reports successful replay.  
   **Fix:** compare the named immutable identities, account cap, asset fields, exact rights versions/content and preset pins; test drift beyond asset hashes. **RR-T9.**

10. **R5V-10 — SHOULD-FIX — Real voice rows receive fictional media metadata.**  
    [t031_prepare_run.py:299](/root/AIVORA/drama-box/.scratch/t031-r5/microdrama/tools/t031_prepare_run.py:299) uses fixture `media_info()`: four-second H.264 video/AAC metadata for the real PCM WAV references.  
    **Fix:** derive validated metadata from the actual WAV bytes before registration. **RR-T9.**

All six §6 packages are represented. RR-T1/T2/T4/T8/T12/T15 have relevant code/test coverage; the composed flag guard, role/subject staging and mandatory live schema comparison are present. The remaining acceptance rows are addressed above.

Independent read-only checks passed: contracts, lint, formatting, diff whitespace and gateway byte identity. The existing gate log records **3,121 unit / 462 contract / 275 integration passes**; I did not rerun that suite. No provider calls or workspace changes were made.

