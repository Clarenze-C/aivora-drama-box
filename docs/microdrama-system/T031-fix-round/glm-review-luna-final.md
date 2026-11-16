**VERDICT: FIX-REQUIRED** — 0 BLOCKING, 3 SHOULD-FIX, 4 NIT.

Report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/glm-review-luna-REPORT.md`

**Per-ID:** H-3, H-4, H-6, H-7, H-8, H-9 **CLOSED** · H-5 **PARTIAL**.

**Key findings:**
- **L-1 (SHOULD-FIX, H-5):** the binder still rejects shot-scoped maps the validator accepts — probe-verified: the commit's *own* costume-change test seal fails `bind_v2_workflow`'s ordinal rule for every shot (SchemaInvalid after pod acquisition → terminally FAILED), and no test executes shot-scoped stage/bind. The only new H-5 test passes at the parent (seal validator was never the obstacle).
- **L-2 (SHOULD-FIX, H-5):** `bind()`'s upload lookup keys on `(role, subject_id)` (`experimental_world.py:665`), collapsing rows for a legal same-subject costume change → wrong receipt → SchemaInvalid after acquisition.
- **L-3 (SHOULD-FIX):** `test_preflight_uses_the_same_policy_as_the_default_factory` passes at parent `628fe5b` (`1 passed in 6.00s`) — vacuous, because the composed seal is UNVERIFIED so `_validate_authorization` fails before the monkeypatched policy ever runs, at both revisions.
- NITs: preflight omits `public_actions_enabled` + budget headroom (L-4); all existing LIVE seals now refuse until re-issued with the new attestation-source field, undocumented (L-5); H-8's removal dropped the only preset-non-widening regression test (L-6); §G evidence write path never ran on a real DB (L-7).

**Red checks at `628fe5b`** (scratch worktree left at `/tmp/t031-luna-redcheck`): H-6 ×2 and H-3-unit red (`3 failed, 1 passed in 0.64s`), H-4 red (`1 failed in 0.69s`, `AttributeError: _record_benchmark_raw_evidence`). H-6's deny-hash pin independently re-verified by probe (recomputed mapped hash from the CPU attestation = pinned constant). H-2-recovery-spec conflicts: 0026 edited by both, spec line anchors drift (+33/+13), and the H-9 runbook's "terminal FAILED" claim will be softened by the redesign's §3.3 — flagged, no semantic conflict.
