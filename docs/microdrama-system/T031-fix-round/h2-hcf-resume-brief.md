# T031 H-2 fix round HCF: RESUME (GLM). The last session stopped at the z.ai 5 h limit during F3.

You continue HCF. **The full original brief still binds you:**
`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-hcf-brief.md`. Read it, then the
findings (`codex-review-h2-p4p5.md`), then your report `T031-fix-round/h2-hcf-REPORT.md`.

## State at the stop (orchestrator-verified, 11 Nov 13:58Z)

- Branch `feat/t031-fix3`: **F1 `6db5fe8`** and **F2 `9b736da`** are committed.
- The worktree's tracked files equal HEAD.
- **Your F3 code edits are NOT in the tree.** You stashed them to run red tests, then the 429 stopped
  you. They are preserved as:
  - stash `1f9bc18eb17e6a1fee5f166c1fddd9516fb2817d` ("t031-hcf-f3-wip"): `benchmark_service.py`
    +177/−…, `benchmark_experiments.py` +97/−…;
  - pinned by the orchestrator on branch `wip/t031-hcf-f3-stash`.
- **Untracked in the tree:** `microdrama/tests/unit/rendering/test_t031_hcf_f3_finality.py` (your F3
  tests) and a stray `test_t031_hcf_f1_receipts.md`. Never stage the `.md` file.

## Where to start

1. Run the F3 tests **red against HEAD now** (code edits absent) and record the summary line.
2. Restore your edits with **`git stash apply 1f9bc18eb17e6a1fee5f166c1fddd9516fb2817d`**.
   - **Apply by SHA, never `pop`.** The stash stack is shared with other sessions.
   - Review the restored edits against HC-1/7/8/9 before keeping them.
3. Finish F3, then F4, then F5, exactly as the original brief says. Commit and update the report after
   each package.
4. **After F3 is committed,** find the stash entry by its message and drop it:
   `git stash list --format='%gd %H %gs'` → `git stash drop <stash@{n}>` **only if** that entry's SHA is
   `1f9bc18…`. The `wip/t031-hcf-f3-stash` branch stays; the orchestrator removes it.
5. **For any future red run, don't stash.** Make a temporary WIP commit on a scratch branch, or restore
   committed file versions with `git show HEAD:<path> > <path>` and re-apply your saved diff from a file.

## Pace

- At the z.ai limit or a 429: stop at a clean point, commit green work, list uncommitted files in the
  report, and update "Resume here".
- **Never leave code edits only in a stash.**
- When F1–F5 are all done: the exact line `H2-HCF: ALL FIXES DONE` goes at the top of the report.

Final message: one line per package, then the report path.
