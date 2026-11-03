# T045 review and fix round, 2–3 November 2026

This folder records the T045 review cycle: the review reports, the rulings, and the build briefs that carried them.
Briefs were copied here from an Opus session scratchpad on 3 Nov, so the next orchestrator can use them. Their
scratchpad paths now point to this folder.

## Who did what

- **Builds:** GLM-5.3 wrote all T045 code, through headless `ai-route build` sessions.
- **Reviews:** Claude Sonnet 5.5 (read-only `code-reviewer`) stood in for Codex. The Codex week was at 97% until
  2026-11-04 06:57Z. Every review ran in an isolated worktree, and the reviewer reran red proofs itself.
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
| `brief-t045-fix5.md` | **The next build's brief:** resumes where session 4 stopped. Not launched yet. |
| `rr2-probes/*.py.txt` | The round-2 reviewer's probe tests (DSN forms, late-Pod extras, the held prompt hold). `WT` points at a removed worktree; adapt it before use. |
| `T045-FIX-REPORT.md` | Written by the final build session. It doesn't exist yet. |

## History

| Step | Commits | Outcome |
|------|---------|---------|
| T045-A build (R0–R8) | `65fae0b..1a60fc5` | Sonnet review A → `t045a-rulings.md` |
| T045-B build (R9–R11) | `4886331..7f857eb` | Sonnet review B → `review-t045b.md`, ruled in `brief-t045-fix.md` |
| Fix sessions 1–2 (z.ai 429 each time) | `488ba9e..9720a90` (16) | Round 1 → `rereview-t045fix.md` → RR rulings |
| Fix session 3 (429) | `ff5ae5c..7faef9e` (6) | Round 2 → `rereview2-t045fix.md` → F rulings, plus O-1/O-2 from Opus's own check |
| Fix session 4 (429 after 24 min) | `b05b66a` (RR-N3, B-N1) | F-1 written but **uncommitted** in the working tree |
| Fix session 5 | — | Brief ready; to be launched by the GLM orchestrator |

**Review cap:** both re-review rounds are used up. Verifying F-1–F-6, O-1, O-2 and the rest of B-S1 needs the
operator's decision on a third check; HANDOFF recommends one scoped Codex review.

**Hard limits for every session:** no provider calls, no paid runs, no live keys, and no env or `.env` printing.
Stubs never echo auth headers. Commit, never push. T031 is not started until the RunPod key is rotated and the
operator sets the spend cap.
