# Phase B spec v0.5: apply the Codex round-1 critique rulings (GLM docs-only job)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Docs only — no code edits, no worktree, no tests.**

## Read first (absolute paths)

- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/codex-phase-b-critique.md` — the 16
  findings, each with a **Replacement:** paragraph (authoritative wording).
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-b-critique-rulings.md` — every
  finding ACCEPTED; PB-11 takes the **first** option (prerequisites in `conditions`, Approve blockers at
  the start of the Approve callback).
- `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md` — current v0.4.
- Cross-check only: `phase-A-spec.md` v0.3, `A1-design-note.md`, `A2-design-note.md` (§4 account
  hierarchy PB-7/PB-8 build on), `A3-design-note.md`.

## The job

Produce **v0.5** of `phase-B-spec.md` in place, folding each replacement into the section it corrects
(§2 identity/generation rounds, §3 gate behaviour, §5.1–§5.5, §6 records incl. the new authorization
row from PB-8 and typed beat effects from PB-12, §7.1 completion seam + §7.3 prompt registry, §8
extension branch, §9 commands (reopen/intake-replacement), B-T5/B-T9/B-T10/B-T11 upgrades, package
routing for the three critic prompts per PB-6). Rules:

1. Replacement wording wins over v0.4 prose; integrate, don't append a diff.
2. PB-15 **strengthens** B-T5 — keep the stronger form. No other acceptance row may be weakened.
3. Never contradict `SPEC-v3.md`/`DECISIONS.md` or an operator decision; the operator's O-B1..6
   answers stand. If a replacement cannot be integrated without contradiction, stop, leave it out,
   report BLOCKED.
4. New persistence uses symbolic migration names (B-…); no real migration numbers.
5. Update the version header (v0.5, 13 Nov, "Codex round-1 critique applied per
   `phase-b-critique-rulings.md`") and fix stale v0.4 self-references.

## Hard limits

Offline docs job: no model/network calls, no pushes, no merges, no service restarts, no deletion
commands, never print environment variables or keys. Commit on `feat/microdrama-m0-m4`:
`docs(v3): phase B spec v0.5 — Codex round-1 critique applied (GLM)`.

## Report

Final message: one line per finding (applied / BLOCKED + why), the commit hash, and the v0.5 line
count. No separate report file.
