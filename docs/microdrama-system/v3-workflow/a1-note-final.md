**Note written:** `docs/microdrama-system/v3-workflow/A1-design-note.md` (599 lines, v1.1)

Ten-line summary:

1. **Migrations 0028–0031**, one purpose each: discriminator (`workflow_version` + immutability + episode re-parent guards), version-aware gate rules replacing the five 0002 CHECKs (V1 rules reproduced verbatim inside `md_approval_gate_rules`, V3 Revise backed by a deferred notes trigger), the five track/activation/notes tables, and jobs work-scope columns + `alert_dismissals` + the full `track_waits` view SQL.
2. **A0/A1 jobs-column split** flagged for the master §10.0 amendment: A0 owns `defer_reason`/`consumed_attempt` + provider-operation state changes; A1 owns `track`/`extension_id`/`logical_work_id`/`replaces_job_id` — zero overlap.
3. **Contracts:** `GateType` += 4 gates; `GATE_ACTIONS` and the V1 `ApprovalCommand` untouched — the invalid `gate1_revise` example (`contracts/examples.py:2180`) stays as-is because V3 LOCK Revise travels on a new `V3DecisionCommand` with typed `RevisionNoteTargets` validated against the recomputed binding.
4. **Decision transaction:** 10 steps in one caller-owned transaction, idempotency-replay-first, `GateHandlerRegistry` (all methods take the caller's `tx`), test handlers only via `allow_test_handlers=True` which `build_production_world` refuses; missing handler → `NOT_AVAILABLE` before any write; `core/approvals.py:64` untouched.
5. **Command table:** all ten §3 commands with actor/scope/revision/edges/prereqs/writes/replay, activation per AR-6 (`create_*`→A2, `cancel_*`/`rewind`→A3, `create_extension`→B per OQ-1), and AR-3's Reject semantics = no state move, activation closed, revision advanced.
6. **`require_workflow` inventory:** every critique-listed entry point with `file:line` — refusals on services/handlers/replayed jobs, candidate filters on all fourteen scheduler selectors, per-version janitor adapters (GPU janitor gains a `human_wait` V3 arm).
7. **GPU safety (AC-9):** one `v3_human_wait` predicate attached at gate activation, lease admission, heartbeat, claim/adoption/transfer and janitor candidate+`_cause`, all with `file:line`.
8. **Lock audit:** six transactions against the §6 order, all conforming; three pre-existing inversions recorded with owners (job-before-track → A3, billing child-before-parent → A2, cadence insert); three competing-transaction tests specified.
9. **Test plan:** A-T1..A-T6 + A-T16 mapped to concrete files, including V1-byte-equality assertions and the populated-V1-database upgrade test.
10. **Six open questions** with recommendations (extension activation, cancelled-track representation, `DeferReason` enum ownership with A0, scope-level dismissals, zero production handlers in A1, V3 Gate 2 binding).

One disclosure: besides the note, a small reflow helper script was left at `.scratch/a1-note-reflow.py` (used to unwrap prose paragraphs; the task's no-deletion limit kept me from removing it). No code, tests, commits or network; no keys printed.
