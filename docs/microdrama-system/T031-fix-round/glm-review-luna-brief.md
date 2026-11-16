# GLM review — Luna's H-3..H-9 commit `82135d4` (Codex may not review Luna code)

You are the **reviewer**: do not edit or commit anything. Orchestrator: Opus, 10 Nov 2026.

## Scope

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, branch
  `feat/t031-fix3`.
- **Scope: `git show 82135d4` only** (12 files, +324/−131). Luna (Codex gpt-6-luna)
  wrote it. The orchestrator committed it because Luna's sandbox could not commit.
- Earlier commits are out of scope. H-2 (`628fe5b`) is being redesigned under a
  separate spec, `/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md`,
  so do not review H-2 behaviour. Do flag any place where `82135d4` will conflict with
  that spec.

## Inputs

- The findings these changes are meant to fix: sections H-3..H-9 of
  `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/glm-review-harness-REPORT.md`
  (your own earlier review).
- The rulings for each ID: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix3-brief.md`.
- Luna's report: `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix3-luna-REPORT.md`.
  It recorded no red baselines.
- The orchestrator already ran `tests/unit/pipeline/`, `test_pika_h3_flex.py`,
  `test_runpod_transport.py`, `test_t045_billing_ingestion.py` and
  `test_t045_storage_ownership.py`: 215 passed.

## For each of H-3..H-9, answer

1. **CLOSED / PARTIAL / OPEN** against the original finding and the ruling.
2. **Red check.** Do the new tests fail on the parent `628fe5b`? Prove it with
   `git stash`-free methods: in a scratch copy under `/tmp/t031-luna-redcheck/`
   (`git worktree add --detach /tmp/t031-luna-redcheck 628fe5b`), write the new or changed
   test files into it **from the commit** (`git show 82135d4:<path>`, never from the
   working tree, because another builder is editing that tree now), and run only them.
   Read all Luna code via `git show 82135d4` as well, not from the working tree. Report the exact pytest summary lines. Use
   `systemd-run --scope -p CPUQuota=45% --quiet` and
   `--basetemp=/tmp/t031-lunarev-basetemp`. Leave the scratch worktree in place;
   the orchestrator will remove it.
3. **New defects** introduced by the commit, with special attention to the following:
   - **H-3:** do preflight and the factory really share one validation source, or is it
     duplicated?
   - **H-4:** is evidence written before allocation, in the same transaction or
     replay-safe, with no headers or secrets stored (§G)?
   - **H-5:** is the 0026 edit safe, with all guards kept?
   - **H-6:** can the deny-list be bypassed by a re-hash or by relabelling?
   - **H-7:** is the cleanup-hold link correct under multiple acquisitions?
4. Any weakened assertion or skipped test.

## Constraints

- Read-only except under `/tmp/t031-luna-redcheck/` and your report file. No provider
  or network calls, no docker, no deletion commands (`rm`, `git rm`, `git clean`,
  `git reset`, `find -delete`), never print secrets.
- Report to
  `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/glm-review-luna-REPORT.md`.
  Findings use IDs `L-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`,
  a failure scenario and a fix. End with a verdict: **ACCEPT** / **FIX-REQUIRED**.
- Final message: the verdict, the counts by severity, and the report path.
