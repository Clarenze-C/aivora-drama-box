**Verdict: FIX-REQUIRED**

Counts: **2 BLOCKING · 4 SHOULD-FIX · 3 NIT**

Report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/glm-review-harness-REPORT.md`

The two blockers, both in the default live composition the fixture tests never touch:

- **H-1** `experimental_world.py:150` calls `bind_pod_endpoint(pod)` with one `PodInfo` argument; `ComfyHttpClient.bind_pod_endpoint` (`comfy_transport.py:124`) requires `(pod_id, endpoint_url)` — the canary calls it correctly (`canary.py:1019`). Every default `execute`/`resume` crashes with `TypeError` in `acquire()` **after** the paid pod is created, then `except BaseException` marks the experiment terminally FAILED and sweeps. The 124-test fixture's fake client lacks the attribute, so `hasattr` skips the branch — only the live `PikaHttpClient` inherits the method.
- **H-2** No reconciliation path exists for UNKNOWN effects: a single prompt-POST timeout or ambiguous pod create parks the experiment in `NEEDS_RECONCILIATION` forever (`poll` refuses UNKNOWN without re-checking history; nothing ever sets `NO_CREATE_PROVEN`; sweep rewrites UNKNOWN→CLEANUP_PENDING which keeps the unique slot occupied). Contract §E mandates a provider-operation reconciler; money stays safe (holds retained), but the $8 one-shot experiment is unresumable by any in-repo path.

Key SHOULD-FIX items: preflight says `ready` from labels/hashes while the default factory later refuses on rights/preset/account state (H-3); the §G `benchmark_billing_evidence` table and its writer have no caller — raw amount strings never persist (H-4); shot-scoped seal port maps validate but crash staging (`UNIQUE(acquisition_id,destination_slot)`), leaving S08's costume change unrepresentable (H-5); the `LIVE_PROVIDER` schema label is self-asserted and the known CPU/no-weight hash (`339021b1…`, identical to the fixture — probe-verified) isn't machine-denied, though weight-enum drift keeps it from misqualifying a provisioned runtime (H-6).

Money, rights and safety architecture checked out clean: shared $8 envelope with atomic intent+holds before any effect, canonical price units (quote rates forced to whole µ$/GPU-second, so no rounding loss), model-rights pins plus per-reference grants both required, digest-pinned weightless image with explicit-only provisioning, full 0026 trigger guards, and secret-safe diagnostics throughout.
