# T031 H-2 build — RESUME (GLM, re-runnable)

Earlier sessions stopped at a quota limit or a full context. **You continue the build.**
This brief may run several times in a row, so always start by reading the current state.

**Still binding:**
- the original brief: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-build-brief.md`;
- spec v3: `/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md`.

## Start every session like this

1. Read the progress report
   `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-build-REPORT.md`,
   especially the status table and the **"Resume here"** line.
2. In your cwd `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree` (branch
   `feat/t031-fix3`), run `git log --oneline 82135d4..HEAD` and `git status --short`.
3. **Uncommitted changes** are a previous session's half-finished work. The report should
   list them. If it doesn't, list them yourself before touching anything.
4. If a package's tests were not yet recorded red, keep tests-first honest:
   1. Save the draft with `git diff > /tmp/t031-h2b-draft-<n>.patch`.
   2. Restore the committed files with `git show HEAD:<path> > <path>`.
   3. Record the reds.
   4. Re-apply with `git apply`.

   Never use `git stash`, `git checkout --`, `git reset` or deletion commands.

## Work

- Continue from "Resume here". At the time of writing that is **P3 part 2**:
  - §5.3 upload readback (AT-17);
  - the §5.4 grace mechanics and the R3 deadline fence (AT-18, AT-19);
  - AT-2 and AT-3;
  - the §9.3 extensions for P3.
- Then P4 and P5, in the order of the original brief.
- Commit at every package boundary, plus WIP commits at clean intermediate points.
  Update the report after each commit, including the "Resume here" line.

## Stopping

Stop cleanly in each of these cases:
- a 429 usage-limit error;
- your context getting nearly full;
- everything is done.

Before stopping:
- Commit what is clean.
- Make the report's "Resume here" line exact.
- List any uncommitted files in the report.

Final message: one line per package (DONE / PART n / pending), then the report path.
