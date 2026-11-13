# R5 spec v0.3: apply the 12 Codex critique replacements (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only — no code edits, no worktree, no tests to run.**

## Read first (absolute paths)

- `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-r5-critique.md` — the 12 findings,
  each with a **Replacement:** paragraph (that wording is authoritative).
- `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/r5-critique-rulings.md` — every finding
  ACCEPTED (placement choice = (a)); nothing rejected, nothing weakened.
- `/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md` — current v0.2.

## The job

Produce **v0.3** of `T031-run-readiness-spec.md` in place, folding each accepted replacement into the
sections it corrects (§2 scope wording, §3 design/R5a–R5e, §4 budget arithmetic, §5 acceptance tests,
§6 plan, §8 wherever a replacement names a section). Rules:

1. Each replacement's own wording wins where it conflicts with v0.2 prose; integrate cleanly, don't
   append a diff.
2. Add the tests the replacements demand where §5 lacks them: pending-state + missing-endpoint with
   exactly one create; typed boot-failure handling that leaves sample/model outcomes unset; acquisition
   records keyed by acquisition ID surviving cleanup; the composed flag path with captured RunPod
   payload; office-reuse staging through real binding; per-phase resume/reconciliation commands with
   terminal checks; the per-pod billing verification procedure; a 25-minute boot with concurrent janitor
   sweeps; recovery of already-admitted work not re-classified BOOT_TIMEOUT; placement (a) linkage.
3. Never weaken an existing acceptance row, never touch operator decisions ($8.00 envelope, P, the
   12 Nov DECISIONS row, T031-authorization), never edit other files.
4. Update the version header (v0.3, 13 Nov, "applies the Codex round-1 critique per
   `r5-critique-rulings.md`") and bump any internal cross-references that say v0.2.
5. If a replacement cannot be integrated without contradicting the operator decisions, stop, leave that
   replacement out, and report it as BLOCKED in your final message.

## Hard limits

Offline docs job: no model/network calls, no `git push`, no merges, no service restarts, no deletion
commands, never print environment variables or keys. Commit on `feat/microdrama-m0-m4` in the main
checkout: message `docs(t031): R5 spec v0.3 — Codex round-1 critique applied (GLM)`.

## Report

Final message: one line per finding (applied / BLOCKED + why), the commit hash, and the v0.3 line count.
No separate report file needed.
