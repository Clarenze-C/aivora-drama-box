# T045 review and fix round, 2–4 November 2026

This folder records the T045 review cycle: the review reports, the rulings, and the build briefs that carried them.
Briefs were copied here from an Opus session scratchpad on 3 Nov, so the next orchestrator can use them. Their
scratchpad paths now point to this folder.

## Who did what

- **Builds:** GLM-5.3 wrote all T045 code, through headless `ai-route build` sessions.
- **Reviews:** Claude Sonnet 5.5 (read-only `code-reviewer`) stood in for Codex through 2 Nov. The Codex week was
  at 97% until 2026-11-04 06:57Z. From 4 Nov, Codex reviews again (`codex-review-t045fix5.md`).
- **Rulings:** Opus 5.5 ruled on every finding, and every ruling is binding unless it says "accepted as is". From
  3 Nov, GLM orchestrates and rules; see HANDOFF.

## Files

| File | What it is |
|------|------------|
| `t045a-rulings.md` | Rulings on the T045-A review: A-B1, A-S1–S8, A-N1–N9. A-N5 accepted as is. |
| `review-t045b.md` | Sonnet review of T045-B (R9–R11): B-B1, B-B2, B-S1–S10, B-N1–N7. |
| `brief-t045-fix.md` | **Binding fix brief:** every A and B ruling with its test, plus gates, commit rules and hard limits. B-N4 accepted as is. |
| `rereview-t045fix.md` | Re-review round 1 of `7f857eb..9720a90`: 29 FIXED, 3 PARTIAL (B-S8, B-S9, B-N1). |
| `brief-t045-fix-final.md` | RR rulings: RR-S1–S4 and RR-N1–N5, plus the items left open from the first brief. |
| `rereview2-t045fix.md` | Re-review round 2 of `9720a90..7faef9e`: 9 FIXED, 1 PARTIAL (B-S1), no BLOCKING. New findings F-1–F-7. |
| `brief-t045-fix4.md` | Opus rulings O-1 and O-2, round-2 rulings F-1–F-6 and the rest of B-S1, the accepted-as-is list, the order, and the docs, evidence and report rules. |
| `brief-t045-fix5.md` | Session 5's brief: resumes where session 4 stopped. Launched 3 Nov by the GLM orchestrator. |
| `rr2-probes/*.py.txt` | The round-2 reviewer's probe tests (DSN forms, late-Pod extras, the held prompt hold). `WT` points at a removed worktree; adapt it before use. |
| `T045-FIX-REPORT.md` | Session 5's close-out report (sessions 1–5): every ruling's commit, the changed-tests audit, the gates. |
| `codex-review-brief-t045fix5.md` | The scoped Codex review brief for `7faef9e..HEAD` (operator-approved 4 Nov). |
| `codex-review-t045fix5.md` | The Codex review: FIX-REQUIRED, 4 BLOCKING / 3 NON-BLOCKING / 1 NIT (CR-1..CR-8), recovered from the session rollout after the sandbox refused the write, with the orchestrator rulings appended. |
| `brief-t045-fix6.md` | **Session 6's brief:** fixes CR-1..CR-8 under the rulings. |
| `T045-FIX6-REPORT.md` | Session 6's report. Doesn't exist yet. |

## History

| Step | Commits | Outcome |
|------|---------|---------|
| T045-A build (R0–R8) | `65fae0b..1a60fc5` | Sonnet review A → `t045a-rulings.md` |
| T045-B build (R9–R11) | `4886331..7f857eb` | Sonnet review B → `review-t045b.md`, ruled in `brief-t045-fix.md` |
| Fix sessions 1–2 (z.ai 429 each time) | `488ba9e..9720a90` (16) | Round 1 → `rereview-t045fix.md` → RR rulings |
| Fix session 3 (429) | `ff5ae5c..7faef9e` (6) | Round 2 → `rereview2-t045fix.md` → F rulings, plus O-1/O-2 from Opus's own check |
| Fix session 4 (429 after 24 min) | `b05b66a` (RR-N3, B-N1) | F-1 written but **uncommitted** in the working tree |
| Fix session 5 (4 Nov, clean finish) | `10d7d31..c51c709` (12) | All 9 remaining rulings fixed red→green; gates green (unit 2765 / contract 462 / integration 263), re-confirmed by the orchestrator → `T045-FIX-REPORT.md` |
| Scoped Codex review (4 Nov 06:58Z, operator-approved) | `7faef9e..c51c709` | FIX-REQUIRED: CR-1..CR-8 (4 BLOCKING) → rulings in `codex-review-t045fix5.md` → `brief-t045-fix6.md` |

**Session 6 (CR fixes) is the open work.** The Sonnet re-review cap applied to the closed DB cycle and the
round-1/2 T045 cycle; the Codex review of 4 Nov started a fresh verification layer for the post-round-2 fixes.

**Hard limits for every session:** no provider calls, no paid runs, no live keys, and no env or `.env` printing.
Stubs never echo auth headers. Commit, never push. T031 is not started until the RunPod key is rotated and the
operator sets the spend cap.
