# T031 fix round 3, continuation — Luna takes over from GLM (z.ai window spent)

Orchestrator: Opus session, 10 Nov 2026. You are the builder. GLM started this round
and was stopped when the z.ai quota ran low. **Continue its work; do not restart it.**

## Read first

1. The full round brief, which binds you to every ruling, hard limit and the definition
   of done:
   `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix3-brief.md`
2. The findings it cites:
   - `.../T031-fix-round/glm-review-harness-REPORT.md` (H-1..H-9)
   - `.../T031-fix-round/codex-rereview-fix2.md`
   - `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md`
     (§E, §G)

## State you inherit

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, branch
  `feat/t031-fix3`.
- Already committed by GLM. Do NOT redo or modify these; `git log d971435..HEAD` shows
  them: CN2-1 `726a56e`, CN2-2 `252a6dc`, CN2-4 `4330780`, CN2-3 `e3ab087`, H-1
  `8e23104`, **H-2 `628fe5b`** (provider-operation reconciler and CLI `resolve`).
- The only uncommitted change is a ruff format and import-order fix GLM left in
  `microdrama/tests/unit/pipeline/test_benchmark_world_composition.py`. Check it with
  `make lint`, then commit it on its own as a `style(...)` commit before you start.
- Your work: **H-3, H-4, H-5, H-6, H-7, H-8, then H-9 (docs only)**, in that order.

## Differences from the round brief, for you

- Your sandbox may block `systemd-run` and Docker. The orchestrator already runs your
  whole job under a CPU-quota scope, so run pytest directly, without `systemd-run`,
  using `--basetemp=/tmp/t031-fix3-basetemp`.
- If an integration test cannot run in your sandbox (for example, it needs a database
  you can't start), don't work around it. List the exact pytest commands in the report
  under **"Probes for the orchestrator"** and continue with unit and contract tests.
- Report path:
  `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/fix3-luna-REPORT.md`.
  Per ID it covers: root cause, files, red/green pytest summary lines, commit hashes,
  and conservative choices where the contract was silent.
- Your code will be reviewed by GLM, not Codex. Write commit messages that cite each
  ID.

All hard limits from the round brief apply: offline only, the four MICRODRAMA_* flags
set off, no provider/network calls, no docker build or push, no pushes or merges, no
migrations 0001–0025, no `microdrama/contracts/` edits, no deletion commands, never print
secrets, and no full `make check` / `make pilot`.

Your final message: one line per ID, plus the report path.
