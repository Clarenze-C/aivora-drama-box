# T031 H-2 build — RESUME (GLM). Earlier sessions stopped at the z.ai window limit.

You continue the H-2 build. **The full original brief still binds you:**
`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-build-brief.md`.
Read it, then spec v3 (`/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md`),
then the progress report:
`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-build-REPORT.md`.

## Where to start

- Your cwd is `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, branch
  `feat/t031-fix3`.
- The report's **"Resume here"** line and its package table are the source of truth
  for what is done. `git log 82135d4..HEAD` shows the commits. Do not redo committed,
  green work.
- If the tree has uncommitted changes from a stopped session, review them against the
  spec before keeping them. Record red runs for any new AT against the committed code:
  write the tests, restore the committed file versions with `git show HEAD:<path> > <path>`,
  run the tests red, then re-apply your saved diff. Never use `git stash`,
  `git checkout --`, `git reset` or deletion commands.
- Continue the remaining packages in order (P3 → P4 → P5) exactly as the original brief
  says. Commit and update the report after each package or each coherent part.

## Pace

- You have a z.ai budget. When you are near the limit or get a 429, stop at a clean
  point: commit green work, list any uncommitted files in the report, and update
  "Resume here".
- When **all** of P1–P5 are DONE, with every AT green and the report complete, put this
  exact line at the top of the report: `H2-BUILD: ALL PACKAGES DONE`.

Final message: one line per package, then the report path.

## UPDATE 10 Nov ~17:00Z (orchestrator): review findings to fix (package HBF)

Codex reviewed P1–P3: **FIX-REQUIRED**, 13 BLOCKING + 1 SHOULD-FIX, findings HB-1..HB-14 in
`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/codex-review-h2-p1p3.md`.
All 14 are accepted; the rulings, including Codex's grading of your judgement calls, are at the end of
`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/rulings-canary-night.md`.

**New package order:**
1. Finish the package in progress (P4) to a clean commit.
2. Then **HBF**: fix HB-1..HB-14 one by one. For each:
   - write the failing test first; Codex's suggested test cases are the minimum;
   - use the §6.1 shared lock helpers from P4 for HB-8 and HB-9;
   - commit, citing the ID.
3. Then **LF**: fix L-1..L-7 from the GLM review of Luna's commit
   (`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/glm-review-luna-REPORT.md`;
   rulings at the end of the rulings file). L-1 and L-2 are BLOCKING. Tests first.
4. Then P5.

Add an HBF row to the report's status table. The completion marker
`H2-BUILD: ALL PACKAGES DONE` may be written only once P4, HBF, LF and P5 are all DONE.
Do not weaken the test fixtures to make a finding pass. HB-13 is specifically about fixtures that are too
permissive.
