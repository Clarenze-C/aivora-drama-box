All six findings fixed, committed, and verified. Final summary:

1. **CN-1** (`9197c52`) — billing totals convert with ceiling, components normalised to sum exactly; GPU 0.6 + disk 0.6 / total 1.2 no longer disputes; run-14 value → 35_175 with CN-1 comment.
2. **CN-2** (`ce3ff4e`) — `created_pod_recorder` binds the pod id the moment the POST is accepted; once a create request is durably recorded, retries are reconciliation-only (list miss → NeedsReconciliation, never a second POST).
3. **CN-3** (`d372e03`) — URL userinfo + signed-URL params redacted; uncertainty causes are exception type + sanitised category only; e2e test proves secrets never reach exception, record, traceback or stderr.
4. **CN-4** (`881aab6`) — storage ownership opens with the durable pod binding (before verify can fail) and is healed before shutdown; disk now attributes to the lease's episode, readiness never RECOVERY_REQUIRED.
5. **CN-5** (`eed977b`) — stdlib token-checking gateway in both images (ComfyUI on 127.0.0.1 only, 401 on every route incl. websockets without the bearer, token via pod env from the credential ref, fail closed); offline tests only, no image build — shipping needs an operator build + digest re-pin.
6. **CN-6** (`5d0ffa9`) — deadline checked immediately before every attempt incl. right after sleeping; transport timeouts bounded by remaining time (removed before cleanup so stop/terminate keep defaults); plus style commit `d971435`.

All focused suites green (rendering+billing 397, pipeline/transports 174, composed canary 44, crash-recovery 4, contract 462), `make lint` and `make contracts-check` pass; tree clean except pre-existing untracked.

Report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix2-REPORT.md`
