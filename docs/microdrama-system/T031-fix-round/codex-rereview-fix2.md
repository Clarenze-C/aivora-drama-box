Reviewed **`2ceb341...d971435`**: seven commits, 22 files. HEAD matches the requested endpoint. Earlier commits and untracked files were excluded. No files were changed, no integration suite was run, and no external requests were made.

| ID | Result | Assessment |
|---|---|---|
| **CN-1** | **PARTIAL** | Original probes now pass: 1.4 µUSD becomes 2; GPU 0.6 + disk 0.6 conserves total 2 without dispute. Genuine Decimal discrepancies remain mismatches. A new ceiling-boundary case crashes normalization. |
| **CN-2** | **CLOSED** | Durable binding precedes secondary verification; recorded requests cannot submit another create. A production-provider probe confirmed binding survives verification 502. A foreign-name response raised `Conflict` without binding. |
| **CN-3** | **PARTIAL** | Error-body reads are bounded to 8,192 bytes, URL redaction works, and uncertainty causes contain categories. Resolved credentials carried in headers are redacted. The newly injected Comfy token can still leak through a Runpod rejection. |
| **CN-4** | **PARTIAL** | Normal failed startup followed by worker shutdown heals ownership. Worker death immediately after the new POST-accept binding still leaves the janitor without storage ownership. |
| **CN-5** | **CLOSED** | Gateway authentication removes the unauthenticated access path in both image sources. Token-handling leakage is covered by CN2-2 below. Image rebuild and digest re-pin remain outstanding, as explicitly reported by the builder. |
| **CN-6** | **PARTIAL** | Outer retry loops prevent the original sleep-then-dispatch failure. Requests inside one acquisition operation can still start after expiry, and the timeout floor exceeds a short remaining deadline. |

**CN2-1 — BLOCKING — Ceiling conversion can crash normalization on tolerated provider noise**

Location: [rendering/runpod_transport.py:670](/root/AIVORA/drama-box/.scratch/t031-native-worktree/microdrama/src/microdrama/rendering/runpod_transport.py:670).

Reproduced with these USD amounts:

```text
total = 0.0000030000001
GPU   = 0.0000009999999
CPU   = 0.0000009999999
disk  = 0.0000009999999
```

The discrepancy is `4e-13` USD, within the declared `1e-12` tolerance. The ceiling total is 4 µUSD; all component floors are zero. The residual allocator visits each of three components only once, producing a sum of 3 and raising `AssertionError`.

With the base’s half-up conversion, the same normalizer returns total 3 and components `[1, 1, 1]`. This is introduced by the scoped ceiling change. `billing_history()` does not catch `AssertionError`, so the bucket can abort billing ingestion instead of reaching settlement.

The residual ordering is deterministic—largest fractional remainder, ties GPU → CPU → disk—but does **not always conserve the ceiling total**.

**Fix:** handle the complete residual, including tolerance crossing an integer boundary, using a documented deterministic rule. Add this boundary case alongside conservation and genuine-mismatch tests.

**CN2-2 — BLOCKING — The newly injected Comfy token can enter persisted diagnostics**

Location: [rendering/runpod_transport.py:381](/root/AIVORA/drama-box/.scratch/t031-native-worktree/microdrama/src/microdrama/rendering/runpod_transport.py:381).

The create payload now contains the resolved Comfy token. Both Runpod sanitization passes know only the Runpod request headers, so they cannot remove that different credential when it appears without a secret-shaped field name.

A probe through the real `UrllibRunpodTransport`, with `urlopen` replaced in memory, returned:

```text
HTTP 400
{"detail": "invalid environment value synthetic-new-comfy-token"}
```

The synthetic Comfy token survived into `ProviderError` and its formatted traceback. Canary handling then has the same persistence/stderr path identified in round 1. The probe also confirmed that the body read was bounded; length limiting does not resolve this disclosure.

**Fix:** include every resolved credential exposed by the request in its diagnostic redaction context, including credentials sent in the body, or emit allowlisted rejection categories without arbitrary provider text. Test an unlabeled reflection of the injected Comfy token through exception, record, and stderr.

**CN2-3 — SHOULD-FIX — POST-accept binding still leaves a worker-death storage gap**

Location: [rendering/leases.py:235](/root/AIVORA/drama-box/.scratch/t031-native-worktree/microdrama/src/microdrama/rendering/leases.py:235).

The new recorder durably binds the pod but does not open storage ownership. The later ownership open in `ensure_pod()` is unreachable until `create_pod()` returns.

Concrete sequence:

1. POST succeeds; the recorder binds P1.
2. Verification GET fails or the worker dies before returning.
3. The worker never executes another ensure or its shutdown handler.
4. Janitor cleanup sees the bound ID and skips stray adoption, which normally opens ownership.
5. Termination closes no ownership row; positive disk charges remain unowned.

An in-memory execution of the recorder followed by the real janitor cleanup method, with database/provider dependencies replaced, confirmed **zero ownership opens and a close against a missing row**. Thus worker shutdown healing closes the common path, but independent recovery retains the round-1 accounting failure.

**Fix:** establish ownership with the durable binding and heal missing ownership in the janitor’s bound-pod cleanup path before termination/accounting. Add a worker-death case immediately after POST acceptance.

**CN2-4 — SHOULD-FIX — Deadline enforcement stops at outer operation boundaries**

Location: [rendering/diagnostics.py:122](/root/AIVORA/drama-box/.scratch/t031-native-worktree/microdrama/src/microdrama/rendering/diagnostics.py:122).

`bound_request_timeout()` returns at least one second, including after expiry. Outer checks cannot protect subsequent HTTP requests inside `ensure_pod()` or acquisition.

A fake-clock probe using the real manager, provider, and urllib transport recorded:

```text
Deadline: t=1
GET  /pods       starts t=0, timeout=1
POST /pods       starts t=2, timeout=1
GET  /pods/P1    starts t=2, timeout=1
```

The list operation consumed the remaining time; the paid POST still started afterward. Separately, **0.1 seconds remaining produces a 1-second timeout**.

**Fix:** reject expired dispatch at the transport boundary and cap timeout at the actual positive remainder. Preserve the cleanup deadline reset. Test requests that advance the clock between nested calls, plus subsecond and expired deadlines.

**Additional checks and test assessment**

- **CN-2 recovery:** recording the request and crashing before sending intentionally prevents automatic resubmission. The worker raises `NeedsReconciliation`; shutdown or janitor cleanup closes the podless claim, while live billing remains `PENDING_PROVIDER_FINALITY` until audited `resolve_podless_create()` resolution. This is recoverable through the operator path.
- **CN-5 gateway:** comparison uses `hmac.compare_digest()` on bytes. Missing and empty configuration fail closed. In-memory HTTP requests with actual websocket upgrade headers returned 401 without reaching upstream for absent/wrong credentials. Authorization is stripped before forwarding. ComfyUI binds only `127.0.0.1:8189`; the exposed port is the gateway. Authenticated websocket tunneling is unsupported; the documented runner does not use it.
- No new `skip` or `xfail` markers were added. The renamed billing test remains present; changed rounding, uncertainty-message, and capacity-retry expectations follow the rulings.
- Coverage gaps matter: billing cases omit the tolerance/ceiling boundary; CN-4 tests retain worker-driven shutdown; deadline tests advance time through sleeps rather than within requests. The new timeout test explicitly codifies the faulty one-second floor.
- CN-2’s composed regression uses a fake that implements the recorder itself. It provides lifecycle coverage, but does not independently prove production transport wiring.
- Nine existing diagnostic test cases passed when invoked directly in memory. Production-path probes reproduced the findings above. `git diff --check` passed. Builder-reported gate results were not rerun here.

**Verdict: FIX-REQUIRED.** This completes round 2 of 2; the remaining findings go to the operator.

