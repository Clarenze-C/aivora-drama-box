# Codex review: A1 fix round 1 — round 2 (scoped to the round-1 findings)

Diff: `57df5a9..3bd8c90` on `feat/a0d-gateway` (9 commits). Your round-1 report is
`codex-review-a1.md` (A1V-1..11). **Round 2 under the operator's standing waiver: re-check those
eleven findings only**; new defects from the fixes in scope.

Builder context: `.scratch/a0d-gateway/a1-fix1-REPORT.md` (per-finding commits + red/green; note
A1V-1's red line was recorded retroactively against the verbatim pre-fix function — the finding was
already addressed in the 429-recovery commit; weigh that evidence honestly). The evidence gate at
`57df5a9` was GREEN (495 integration); the decisive gate runs at `3bd8c90` in parallel with this
review.

## Output: read-only; ≤100 lines; per finding CLOSED/PARTIAL/REGRESSED + file:line + fix directions;
issues `A1V2-n`; verdict **ACCEPT / FIX-REQUIRED**.
