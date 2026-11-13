# A3 note critique round 1 — GLM rulings (13 Nov 2026)

Input: `codex-a3-note-critique.md` (verdict REWORK; N3-1..5, N3-7 BLOCKING; N3-6, N3-8..10 SHOULD-FIX)
against `A3-design-note.md`. Every ruling is a **GLM ruling, Opus re-check Mon**. The 0035 allocation,
table guards, catalog-registration plan and the revision resolver were confirmed to fit. **All 10
ACCEPTED**; no operator decision; no acceptance test weakened (A-T12a's expectation is *corrected* to
the reachable path, not lowered).

| ID | Ruling (one line) |
|---|---|
| N3-1 | ACCEPT — V3 revision CHECK requires a present non-null JSON integer in range; missing/null → FALSE explicitly; V1 branch unconditional; direct-SQL rejection tests (missing/null/string/bool/fractional/negative/overflow). |
| N3-2 | ACCEPT — explicitly authorized V3 recovery path discovers unresolved operations on CANCELLED jobs (ownership, legal transitions, evidence, settlement specified); job stays terminal; operation success never restores content authority; V1 transitions unwidened; A-T12a corrected accordingly. |
| N3-3 | ACCEPT — observation/settlement of existing operations split from admission of new work; stale/cancelled recovery may observe/record/preserve/settle but never create/rearm/submit/install/enqueue; integration points named in `LlmStep` + reconciler; every terminal/refusal/not-found branch tested. |
| N3-4 | ACCEPT — under ordered scope locks, enqueue + canonical mutation reject scope-or-ancestor cancellation independently of revision equality; admission pre-checks; durable cancellation intent for jobs awaiting reconciliation; recovery observation-only; evidence defined for equal-expected/actual cancelled results (CHECK extended). |
| N3-5 | ACCEPT — full audit of `begin`/rearm through their real reservation FOR SHARE + advisory + operation locks (incl. the #7→#6 chain and `resubmit_allowed`); conforming V3 order specified; V1 semantics preserved; competing-transaction coverage; the 'budget-side only'/`pg_try_advisory_xact_lock` claims removed; A1 §9 handoff stays open until the audit passes. |
| N3-6 | ACCEPT — the V3 collector and its caller-owned transaction named explicitly; provider bytes prepared outside; fenced registration/result/quarantine/installation via transaction-taking helpers inside it (`comfy_assets.persist_output(tx,…)` seam); V1 orchestration preserved; crash recovery between result persistence and settlement specified. |
| N3-7 | ACCEPT — scope-specific source→target edges enumerated against the real state columns; unsupported targets rejected; extension handling stated; display revision advanced once per changed scope, content revision only where required; cancellation sweeps enumerate cancellable statuses (excluding NEEDS_RECONCILIATION, retaining recovery intent); no indiscriminate `cancel_in`. |
| N3-8 | ACCEPT — `StaleContentRevision` derives from `Conflict`/sets `http_status=409`; each V3 submit/collector's conversion of stale detection + lease loss into control flow specified; self-cancellation/revoked ownership stops without ordinary finish; quarantine detection preserves the evidence transaction. |
| N3-9 | ACCEPT — A3 chooses enforced name ownership (duplicate-name refusal) with the CLI, scaling example and tests aligned; documented no-flag V1 behavior preserved; no A6c-owned startup-refusal promises. |
| N3-10 | ACCEPT (strengthens) — test-only child bootstrap exercising the real CLI/runtime with shared fake-provider state surviving worker death; every A0 signal raised (incl. lease loss) with no finish after ownership loss; race interleavings synchronized; SIGTERM coverage; A-T18 distinguishes zero-submits from one accepted submission, recovery uses provider reconciliation evidence. |

**Apply:** fold all 10 into `A3-design-note.md` **v1.1** (job `dramabox:a3-note-rev1`, docs only, queued
behind f-spec-v03). Codex round 2 follows the revision.
