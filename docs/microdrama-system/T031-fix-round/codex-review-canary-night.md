Reviewed **`13da3e2...0851374`** on `feat/microdrama-m0-m4`; HEAD matches the requested endpoint. Uncommitted files were excluded. No files were changed and no repository test suite was run. Line numbers below refer to `0851374`.

**CN-1 — BLOCKING — Billing conversion can under-record cost and manufacture component discrepancies**

Location: [`rendering/runpod_transport.py:602`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/runpod_transport.py:602), [`rendering/runpod_transport.py:615`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/runpod_transport.py:615).

`ROUND_HALF_UP` rounds positive amounts down whenever the fractional µUSD is below 0.5. For example, a bucket with `totalAmount = gpuAmount = "0.0000014"` becomes **1 µUSD instead of 1.4 µUSD**. Repeated buckets accumulate the shortfall; no fractional remainder is retained. The new test explicitly expects downward rounding for the observed GPU amount.

The four fields are also rounded independently. A valid response with GPU = 0.6 µUSD, disk = 0.6 µUSD, and total = 1.2 µUSD becomes GPU = 1, disk = 1, total = 1. [`map_billing_history()` then marks it DISPUTED](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/runpod_billing.py:193), blocking invoice finalization despite consistent provider data. Both arithmetic failures were reproduced in memory using the committed conversion function.

Suggested fix: retain exact Decimal provider amounts, apply a conservative ceiling when determining charge/exposure, and normalize components against one total with an explicit residual policy. Test accumulated fractional costs and component/total consistency, rather than only the run-14 values.

**CN-2 — BLOCKING — Acquisition retries can create a second pod before the first pod is durably bound**

Location: [`pipeline/canary.py:959`](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:959), [`rendering/leases.py:902`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/leases.py:902).

Concrete sequence:

1. `POST /pods` successfully creates P1.
2. Before `create_pod()` returns, its [`_verify_existing_match()` GET](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/runpod_transport.py:377) returns 502.
3. The resulting `TransientProviderError` reaches the new retry loop. `_record_pod_id()` has not executed.
4. The next ownership list temporarily omits P1.
5. [`acquire_or_reconcile()` issues another create](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/pods.py:176), producing P2 under the same reservation.

`create_requested_at` is persisted but does not prevent another submission. The deterministic name supplies reconciliation evidence; this code does not establish provider-enforced name uniqueness. An in-memory probe of the committed manager method confirmed two create calls under this sequence. P1 also remains outside ID-based lease cleanup.

Suggested fix: atomically gate the first submission and make subsequent acquisition attempts reconciliation-only. Persist an acknowledged pod ID before secondary provider verification can fail, while retaining ownership validation. Add a composed test covering successful POST → verification 502 → list miss, asserting exactly one POST and eventual verified cleanup.

**CN-3 — BLOCKING — Error diagnostics copy unredacted provider content into durable evidence and stderr**

Location: [`rendering/runpod_transport.py:251`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/runpod_transport.py:251), [`rendering/comfy_transport.py:75`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/comfy_transport.py:75), [`rendering/comfy_transport.py:88`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/comfy_transport.py:88).

If an upstream rejection contains an echoed bearer token, authentication header, or signed URL within its first 500 characters, that value enters the exception unchanged. Canary handling copies exception messages into the [persisted run record](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:1052) and [stderr](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:1637). The new `URLError` cause interpolation has neither redaction nor a length bound.

The 500-character slice limits displayed length; it provides no secret protection. ComfyUI also reads the entire error body before slicing it. A synthetic echoed bearer token survived the committed transport’s exception message in an in-memory check. **Historical disclosure is unproven; the leakage path is demonstrated.**

Suggested fix: emit allowlisted diagnostic fields and sanitized cause categories. Redact resolved credentials, auth fields, and URL credentials/signatures before constructing exceptions, persistence, or logging; bound body reads and resulting messages. Add synthetic-secret tests for both transports and uncertainty causes.

**CN-4 — SHOULD-FIX — Early pod binding skips storage ownership when activation never succeeds**

Location: [`rendering/leases.py:911`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/leases.py:911).

A pod is now bound while its lease remains CLAIMED. If endpoint verification keeps failing until the deadline, shutdown sees the bound `pod_id` and skips the adoption/activation branch. Storage ownership is normally opened by [`_activate()`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/leases.py:1013), which never ran.

Termination can succeed, but closing storage ownership updates no row. Later positive disk charges go to the recovery pool, and readiness becomes `RECOVERY_REQUIRED`. The janitor’s bound-pod cleanup path also skips the stray-adoption operation that opens ownership. Thus a normal failed startup requires manual accounting recovery despite known ownership.

Suggested fix: establish storage ownership alongside durable pod binding and heal any missing ownership before shutdown/accounting. Extend the new durability test through failed verification, termination, billing ingestion, and correct disk attribution.

**CN-5 — SHOULD-FIX — The canary image exposes unauthenticated rendering through the public proxy**

Location: [`deployment/canary-image/Dockerfile:50`](/root/AIVORA/drama-box/microdrama/deployment/canary-image/Dockerfile:50), [`rendering/runpod_transport.py:338`](/root/AIVORA/drama-box/microdrama/src/microdrama/rendering/runpod_transport.py:338).

The image starts ComfyUI on `0.0.0.0:8188`, and creation exposes that port publicly. No server-side authentication layer is installed or configured. The [README explicitly describes the endpoint as public and unauthenticated](/root/AIVORA/drama-box/microdrama/deployment/canary-image/README.md:71).

A caller who obtains the endpoint can submit graphs directly, bypassing the runner’s reservation, prompt, and attempt checks. They can also consume resources or interfere with the canary through its API. Sending an Authorization header from the legitimate client does not enforce authentication at the server.

Suggested fix: place an authenticated gateway in front of ComfyUI or restrict network access to the operator host. Verify that unauthenticated requests cannot submit or mutate work. This finding concerns the shipped configuration; no live endpoint was probed.

**CN-6 — SHOULD-FIX — Retry loops can begin another provider operation after the hard deadline**

Location: [`pipeline/canary.py:959`](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:959), [`pipeline/canary.py:1004`](/root/AIVORA/drama-box/microdrama/src/microdrama/pipeline/canary.py:1004).

Both loops check the deadline after a failed operation, then sleep and retry without checking again before dispatch.

For example, a list failure at `deadline − 1 second` passes the deadline check, sleeps two seconds, and calls `ensure_pod()` after the deadline. If no pod exists and the quote remains current, that call can create one after the authorized wall limit. The `/object_info` loop can likewise start another request after expiry, using the transport’s fixed 30-second timeout before cleanup begins.

Suggested fix: check the deadline immediately before every attempt, including after sleeping, and bound request timeouts by remaining time. Add fake-clock tests asserting no new request begins after expiry.

The remaining focus checks produced these conclusions:

- **Price ceiling:** changing equality to `>` is correct for the stated ceiling contract. Hourly values above the ceiling remain rejected; sub-µUSD hourly precision is rejected during parsing. `_gpu_second_price()` requires exact divisibility by 3,600, so it does not floor the reservation rate.
- **Invoice window:** I found no introduced wrong-pod, wrong-period, or duplicate-posting path in `9b133f1`. Account/pod restrictions, bucket-edge checks, latest-revision selection, overlapping-evidence controls, and allocation conservation remain in place.
- **Prompt uncertainty:** the new retry surrounds the initial catalog read. Uncertain prompt submission still stops for reconciliation rather than blindly resubmitting.
- **Tests:** existing assertion changes reflect the intended exception type and revised price message. Added tests cover the reported happy paths, but omit the failure combinations above. The committed diff cannot establish historical tests-first execution. `git diff --check` passed; validation here was static review plus small in-memory probes.

**Verdict: FIX-REQUIRED.** The range improves live diagnostics and startup handling, but still permits duplicate paid creation, downward cost recording, and unredacted diagnostic persistence. Early binding also leaves a storage-accounting gap, while public unauthenticated access and deadline overshoot need correction. The invoice-window and price-ceiling changes appear sound on static inspection, but the range should not be accepted until the blocking findings are fixed and the composed failure cases are verified.

