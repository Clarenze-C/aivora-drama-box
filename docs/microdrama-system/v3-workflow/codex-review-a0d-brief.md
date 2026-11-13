# Codex review: A0-D — the LLM gateway, `LlmStep` and migration 0027 (drama-box)

Read-only. Pinned checkout `/root/AIVORA/drama-box/.scratch/a0d-gate` (detached at `ea1cc10`). **Scope: `git diff 0cda424..ea1cc10`** (D1 `365bff9`, D2 `2352e73`, D3 `c25b527`, plus `ea1cc10`: the orchestrator's migration-tail test fix after its first full gate). GLM wrote it; you did not. Base `0cda424` is the accepted T031 tip.

## The requirement

- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A0-spec.md` **v0.4 §4 (gateway) and §5 (`LlmStep`, runtime, recovery)** and their acceptance rows; your wording in `codex-a0-critique.md`, `codex-a0-recritique.md` and `codex-a0-round3.md` is folded in and binding.
- `A1-design-note.md` §3 (jobs-column ownership) and §12 OQ-3 (the closed `DeferReason` enum, owned by A0-D).
- The builder's brief and report beside it: `a0d-build-brief.md`, `a0d-build-REPORT.md` (judgement calls, transaction inventory, the §4.3 recovery matrix).
- The orchestrator's full offline gate (run 1 at `c25b527` failed only on two hard-coded migration-tail tests, fixed in `ea1cc10`; run 2 at `ea1cc10`): receipts in `/root/AIVORA/drama-box/.scratch/a0d-gate/.scratch/gate/`.

## Review

1. **A0S-1 / A0S-2, the auto-reconciler (§5.3): verify explicitly.** Every recovery-table row: the state, what proves it, what the reconciler does, and that it never re-submits or double-charges. Name any row the code does not implement exactly.
2. **Migration 0027:** guarded; `llm.subscription` in `UNMETERED_OPERATION_KINDS` plus 0016's per-kind CHECK; `REFUSED_PRELAUNCH`; the kind-limited `resubmit_allowed` rearm and `PENDING_SUBMIT → CANCELLED`; the closed `DeferReason` enum with its CHECK on `jobs.defer_reason`. V1 rows and behaviour unchanged.
3. **Runtime (§5.2):** the `Deferred` outcome, `defer(refund_attempt)`, `consumed_attempt`, signal translation before generic handling, refusing a deferral with in-flight operations; the outcome-union test extension is deliberate.
4. **Gateway (§4):** isolation (no credentials, env or argv leak; strict argv; the systemd-unit-per-call model), quota admission, timeouts, crash between launch and record, and the fake `ai-route` shim's fidelity to the real A0-R1 contract.
5. **Locks and transactions:** the report's transaction inventory is accurate; no lock-order inversion against A1 §9 or the T031 helper order.
6. **Tests:** real PostgreSQL where it matters; red-before-green credible; nothing weakened in pre-existing tests.

## Output

- Read-only; no writes. Final message at most about 200 lines.
- Findings `AD-1`…, severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`, a concrete failure scenario, and the fix.
- Verdict: **ACCEPT** / **FIX-REQUIRED**.
