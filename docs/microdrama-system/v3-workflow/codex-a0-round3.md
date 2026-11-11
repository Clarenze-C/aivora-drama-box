**Verdict: REWORK**, limited to the new automatic-reconciliation contract. The other corrections can be handled during the build.

Read-only check of [v0.3](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md), round 2, and the specified code. Installed Claude **2.1.322** help was captured completely through a PTY. No writes, systemd units, or model calls; transition checks used a read-only AST probe.

| Finding | Status | Evidence |
|---|---|---|
| A0R-1 | **RESOLVED** | §5.1 records `SUBMITTED` before `WaitExternal`, supplies token/deadline, and avoids repeated `RUNNING` transitions; compatible with `finish()`’s waiting guard. |
| A0R-2 | **RESOLVED** | §4.2 makes readmission replayable; §5.5 adds evidence-gated refusal rearm, while §5.1 renews deadlines and §5.6 retains attempt results. |
| A0R-3 | **RESOLVED** | §5.2 specifies claim-aware refunds, persisted reasons, signal ordering, ambiguity quarantine, and deliberate outcome-contract changes. |
| A0R-4 | **RESOLVED** | Explicit outcome classification, settlement before blocking, cancellation confirmation, and the kind-limited pending cancellation extension address the reported defects. |
| A0R-5 | **PARTIAL** | Lease loss correctly stops writes and skips `finish()`; the newly added recovery continuation conflicts with current job/operation transitions—A0S-1/2. |
| A0R-6 | **RESOLVED** | §4.3 passes complete properties as individual argv elements and includes ai-route’s cache plus precreated write paths. |
| A0R-7 | **RESOLVED** | §4.3 handles absent units with results, queued/starting/stopping/failed states and cancellation intent; §5.4 persists cancellation delivery. |
| A0R-8 | **RESOLVED** | §3.3 specifies complete PTY capture, policy-source inventory, refusal conditions and qualification-bound policy identity. |
| A0R-9 | **PARTIAL** | Production now captures initialization/tool/result events, but qualification conflicts with empty-cwd admission; missing initialization also needs explicit rejection—A0S-3/4. |
| A0R-10 | **RESOLVED** | Budgets use integer micro-USD; arbitrary schema/output JSON moves to hash-bound text, compatible with migration 0009’s integer guard. |

**A0S-1 — BLOCKING — The auto-reconciler cannot return active operations to the queue (§5.3).**

`resolve_reconciliation()` has no queue resolution: `RESUME` grants a running lease. Moreover, [`claim()`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py:478) quarantines queued jobs carrying `SUBMITTED`/`RUNNING` operations, creating a reconciliation loop.

**Replacement:** “The reconciler uses audited `RESUME` with its own worker identity and lease. For active accepted operations, it finishes with `WaitExternal`; for settled operations, it resumes the handler to adopt the result or defer/rearm. Do not queue a job while a linked operation remains in flight.”

**A0S-2 — BLOCKING — The auto-reconciler’s mappings are not state-dependent (§5.3).**

Unconditional `404 → NOT_FOUND` is illegal from `SUBMITTED`/`RUNNING`. Likewise, `found → SUBMITTED` can repeat `SUBMITTED` or regress `RUNNING`; [`ALLOWED_MOVES`](/root/AIVORA/drama-box/microdrama/src/microdrama/core/provider_ops.py:41) rejects these transitions.

**Replacement:** “Reconcile from the current operation state using legal transitions; identical observations are no-ops. For previously accepted/running work, a missing gateway record becomes `UNKNOWN`, requiring authoritative no-execution evidence before `NOT_FOUND` or readmission.”

**A0S-3 — SHOULD-FIX — Project canaries prevent qualification from launching (§7.2 versus §3.2).**

The qualification populates the cwd, while ai-route must refuse every nonempty cwd.

**Replacement:** “Qualification alone may use an explicitly allowlisted, hash-bound canary fixture directory. Production retains empty-cwd enforcement; clear the fixtures and verify refusal of unexpected contents afterward.”

**A0S-4 — SHOULD-FIX — Missing initialization is not covered by the runtime assertion (§3.5).**

The predicates reject extra tools/servers but do not explicitly reject absent or malformed initialization evidence.

**Replacement:** “Success requires one valid initialization event with explicit tool and MCP inventories. Missing, malformed or conflicting initialization evidence discards the output and fails isolation validation.”

**A0S-5 — NIT — Recovery has no outcome for persistent `deactivating` (§4.3).**

After the bounded wait, none of the subsequent rows covers a unit still stopping.

**Replacement:** “If still `deactivating` at the bound, preserve cancellation intent, mark recovery unresolved/unhealthy, and never relaunch.”