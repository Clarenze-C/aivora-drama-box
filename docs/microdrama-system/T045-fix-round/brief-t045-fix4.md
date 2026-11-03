# Finish build T045-FIX (session 4): commit the last fixes, Opus and round-2 rulings, docs, evidence, gates, report

Three earlier sessions of this build stopped on z.ai usage limits (HTTP 429). Their work is committed, apart from
one uncommitted diff described below. You finish the build.

**Binding briefs, in order:**
1. `/root/AIVORA/drama-box/docs/microdrama-system/T045-fix-round/brief-t045-fix.md`: every ruling,
   gate, commit rule, hard limit and report requirement in it applies unchanged. Read it in full first.
2. `/root/AIVORA/drama-box/docs/microdrama-system/T045-fix-round/brief-t045-fix-final.md`: the
   re-review (RR) rulings and items 5–7 (docs, evidence, gates, report). Read it in full.

This file says where to start, adds two new rulings, and changes where the report goes.

## Hard limits (repeated; they bind you)

- No provider calls, no paid runs, no live keys. Nothing leaves this machine except loopback.
- Never print env vars or `.env` contents. Never read `~/.claude/.env`, `/root/.secrets` or any secrets file.
- Stubs never echo `Authorization` headers or keys.
- Commit, never push.
- Run test suites under `systemd-run --scope --quiet -p CPUQuota=45%`. Use pytest `--basetemp` under
  your own session scratchpad, with `basetemp` in the folder name.
- **No deletion verbs in any Bash command text.** That covers the `rm` command, `git rm`, `git clean`, `git reset`
  and `find -delete`, including inside heredocs and strings. A hook holds such commands for 10 minutes and then
  refuses them. Use these instead:
  - to untrack a file: `git update-index --force-remove <path>`;
  - to delete files from disk: write a small Python script file (with `pathlib.Path.unlink`) to the scratchpad with
    the Write tool, then run it;
  - for temporary files: fresh names instead of cleanup.

## State at hand-off

- **Branch:** `feat/microdrama-m0-m4` in `/root/AIVORA/drama-box`. Base of the fix round: `7f857eb`.
- **HEAD:** `7faef9e`. Check `git log --oneline 7f857eb..HEAD` and `git status`.
- **Committed by session 3** (don't redo):

  | Commit | Rulings |
  |--------|---------|
  | `ff5ae5c` | RR-S4, RR-N1 |
  | `9831b2d` | RR-S1 |
  | `a19150c` | B-S1 |
  | `8664c08` | RR-N5 |
  | `dbb29f7` | B-S10, B-N7 |
  | `7faef9e` | RR-S2, RR-S3, RR-N2 |
- **Uncommitted** (session 3 stopped before committing): **RR-N3 and B-N1**, in
  - `budget/billing.py` (`// timedelta(seconds=1)`);
  - `rendering/janitor.py` and `rendering/runpod_billing.py` (`round_up_to_bucket_end`, integer microseconds);
  - `tests/unit/rendering/test_t045_billing_ingestion.py` (the RR-N3 skip-row assertion, the B-N1 boundary property
    test and the no-float source test).

  Read `git diff`. Then:
  - Get the red lines: run the new tests against the parent code. Stash only the `src/` changes, or check out
    `HEAD`'s versions of those three files into a scratch copy. Record honestly any test that passes on the old
    code; the float rounding is correct for most instants, so say which of the tests is the red proof.
  - Run the focused suites green.
  - Commit as `fix(microdrama): T045-FIX RR-N3/B-N1 - ...`.

## New Opus rulings (binding; red test, then green test, as for every other ruling)

**O-1: a test wrote canary objects into the repo, and one got committed.**
- Commit `dbb29f7` added
  `microdrama/canary-objects/.meta/renders/1c0ffee0-0000-4000-8000-00000000cafe/canary-0/a1/9.mp4.json`. The matching
  `.mp4` sits untracked in the working tree, kept out of git only by `*.mp4`. The cause is in `pipeline/canary.py`
  `main()`: `store_root = settings.object_store_root or Path("canary-objects")`, so a composed test that leaves the
  root unset writes into the cwd.
- **Ruling:**
  - `execute`, `sweep` and `invoice` require an explicit object-store root (`MICRODRAMA_OBJECT_STORE_ROOT`). It must
    be an absolute path. Without it, the command refuses with exit 2, a clear message, zero transport calls and
    zero resolver calls. Remove the relative default.
  - Decide whether `preflight` needs the store. If it reads the store, the same rule applies. If not, it must not
    create one.
  - Every test that runs `main(argv)` sets the root under its own `tmp_path`.
  - Untrack the committed `.json` with `git update-index --force-remove`, and delete both stray files from disk with
    a Python script, as the hard limits say.
  - Add `canary-objects/` to `microdrama/.gitignore`.
  - The runbook's canary commands name `MICRODRAMA_OBJECT_STORE_ROOT` and give the durable path
    `/var/lib/microdrama/canary-objects`.
- **Tests:**
  - `main(["execute", ...])` with no root is refused before any transport or resolver call;
  - a relative root is refused;
  - after the full T045 suite runs, `git status --porcelain` lists nothing under `microdrama/canary-objects`. Make
    this a check in the report, not a test.

**O-2: `_prepare_durable_root` (`tools/canary_db.py`) widens existing directories.**
- When run as root, the function walks up from the data root and runs `chmod 0755` on every ancestor that isn't
  traversable. With `--data-root` under a 0700 directory (an operator home, or `/root` on a stock host), that opens
  the directory to every user. The test run already widened `/tmp/pytest-of-root` from 0700 to 0755. The walk
  also stops at the first traversable ancestor, so a 0700 directory above that one is never noticed.
- **Ruling:**
  - Never change the mode of a directory that already existed before the call. Only directories the tool creates
    itself in this call (below the deepest existing ancestor) are created 0755 root.
  - Then check **every** ancestor, from `/` down to the data root's parent: each must be traversable by the server's
    OS user. If one isn't, refuse with exit 2 and an error that names that directory and says how to fix it. Change
    no mode.
  - The data dir stays 0700, owned by the server user. The default `/var/lib/microdrama/canary-pg` still works, since
    `/var/lib` is 0755.
- **Tests:**
  - An existing 0700 ancestor is refused and its mode is unchanged afterwards.
  - Ancestors the tool creates are 0755.
  - The real durable-cluster integration test still passes. It builds its own traversable parent: a directory it
    creates and sets to 0755 itself, under its `tmp_path`'s parent chain only if that chain is already traversable.
    Otherwise it uses a fresh `tempfile.mkdtemp()` directory that it sets to 0755 itself. Either way it widens no
    directory it did not create.
- Report the mode of `/tmp/pytest-of-root` before and after your full test run. Don't change it yourself.
- **Until O-2 is committed**, never run a test that calls `_prepare_durable_root` with a `--basetemp` under the
  scratchpad. Today's code walks up from `tmp_path` and would set the scratchpad, the session folders and
  `/tmp/claude-0` to 0755. Two tests call it:
  - `tests/integration/pipeline/test_t045_canary_db_durable.py::test_the_durable_cluster_runs_with_fsync_synchronous_commit_and_full_page_writes`
  - `tests/unit/pipeline/test_t045_canary_db.py::test_the_default_data_root_is_var_lib_and_its_parent_is_traversable`

  Before the O-2 commit, pass both to `--deselect` on every scratchpad-basetemp run. Alternatively, run them alone
  with no `--basetemp`; pytest's default `/tmp/pytest-of-root` is already 0755.
- `make check` sets no basetemp, so it uses `/tmp/pytest-of-root`. After the O-2 fix, the tests must widen nothing
  wherever they run. After the full gates, check that `stat -c '%a %n' /tmp/claude-0 /tmp/claude-0/-root-AIVORA`
  still shows 700 for both, and put that line in the report.

## Round-2 re-review rulings (binding; red test, then green test)

A Sonnet re-review of `9720a90..7faef9e` found:
- 9 IDs FIXED: RR-S4, RR-N1, RR-S1, RR-N5, B-S10, B-N7, RR-S2, RR-S3, RR-N2;
- B-S1 PARTIAL;
- no BLOCKING findings.

The full text is at `/root/AIVORA/drama-box/docs/microdrama-system/T045-fix-round/rereview2-t045fix.md`. Read
it; its section "New findings" carries the file:line and the probes. The reviewer's probe tests are in
`docs/microdrama-system/T045-fix-round/rr2-probes/` (saved with a `.txt` suffix). You may copy them into the repo as the red tests.

| ID | Defect | Fix + test |
|----|--------|------------|
| F-1 (money) | `_adopt_late_pod` (`rendering/janitor.py`) commits the attach before stop and terminate. If terminate fails, the next sweep finds `pod_id` set and takes the plain orphan path, which only stops the Pod. `terminate_verified_at` then stays NULL, storage ownership stays open, and volume cost keeps accruing. | In the orphan path, an owned Pod held by a terminal lease whose `terminate_verified_at IS NULL` gets the same stop → terminate → verify → `close_storage_ownership` tail. This applies to every terminal lease, not only adopted ones. Each failure keeps the existing per-Pod backoff. Test: first sweep fails terminate (503) → second sweep terminates and verifies → readiness then advances to the invoice match. A third sweep adds nothing. |
| F-2 | `canary.py` ~925: `restore_handlers()` runs first in the `finally`, before the shutdown, so a second SIGTERM during shutdown kills the process with the default action. The handlers are also installed before `_refuse_execute`, and they leak if it raises. | Install the handlers inside the `try`. While shutdown runs, ignore repeat SIGTERM/SIGINT, logging each one. Restore the old handlers only after the record is written. Fix the wrong comment. Tests: a second SIGTERM delivered during shutdown → stop/terminate still complete and the record is written; if `_refuse_execute` raises, the original handlers are back in place; SIGINT takes the same path as SIGTERM. |
| F-3 | `run_sweep` builds the provider with `cleanup_guard=lambda ...: None`, which drops the guard B-S1 required. | Extract the real cleanup guard from `pipeline/live_world.py` (~412) into one shared function, and use it in both `live_world` and `run_sweep`. Never use a no-op guard. If the shared guard would block a stop that the janitor rulings require (the orphan stop of an owned Pod, F-1, RR-S4), keep a guard that still checks ownership (name prefix and account), and record a SPEC-GAP. Test: `canary sweep` refuses to stop or terminate a Pod that the guard does not accept (not owned), with zero DELETE/stop calls. Owned Pods still go through the janitor rulings. |
| F-4 (money) | A FAILED lease-covered prompt hold is left ACTIVE when no retry follows. The probe used `max_attempts=1` with a failing attempt: 84000 micro-USD stayed reserved after the run and the sweep, past `expires_at`. | When a prompt ends without success (attempt cap reached, run stopped, deadline hit), settle its open hold at 0 with a reason, in the prompt-end path or the shutdown path. The hold must not stay reserved. A retry still reuses the hold, as now. Production (non-canary) routing must keep its existing settlement for FAILED lease-covered attempts; prove it with a test. Tests: the probe scenario → the hold ends SETTLED at 0 and the account has nothing outstanding for it; the existing retry test still passes; the composed `main(argv)` test still equals the invoice. |
| F-5 | The DSN guard doesn't check `PGHOSTADDR` or `PGSERVICE` when the DSN names a `host`. `host=localhost` with `PGHOSTADDR=10.1.1.1` passes, and so does `host=localhost` with `PGSERVICE=prod`. | `PGSERVICE` set (any value) → refuse, always. `PGHOSTADDR` set → it must pass the loopback rule unless the DSN has its own `hostaddr`. `PGHOST` keeps today's rule. Messages name the variable and the host, never a password. Tests: both probe cases are refused; a loopback `PGHOSTADDR` with `host=localhost` passes. |
| F-6 (NIT) | `tests/unit/pipeline/test_t045_canary_db.py` puts a module-wide `pytestmark = pytest.mark.db` on pure unit tests, and one test ends with a dead `monkeypatch.setattr`. | Mark only the tests that need a DB. Remove the dead line. No assertions change. |
| B-S1 (rest) | The resolver's `os.stat` follows symlinks and doesn't check the owner. | Refuse a symlink (`lstat`), and refuse a file not owned by the effective uid. Leave the check-then-read gap: it is accepted on this single-operator host; note it in the evidence. Tests: a symlinked key file is refused, and a file with a foreign owner is refused. Fake the owner with a monkeypatched stat if the test can't chown. |

**Accepted as is.** Record each in the evidence, with no code change:
- The B-S10 retry test reads "the failed attempt is charged" as the lease invoice carrying the failed attempt's
  GPU seconds. The operation row stays FAILED.
- F-7: the two `Database(...)` constructions, and the missing LIMIT in `_terminal_podless_lease`.
- RR-S3's untested partial-first-seed case.
- The V2 submit path's base token. V2 is not on the canary path.

**Order:** commit RR-N3/B-N1 → F-1 → F-4 → O-1 → F-5 → F-2 → F-3 → O-2 → B-S1 rest → F-6 → docs (brief-t045-fix-final
item 5, plus O-1's runbook line) → evidence → gates (item 6) → report. Commit by ruling group, each with its red and
green lines in the message.

## Docs and evidence: what is still missing

- **Runbook** (`docs/microdrama-system/T045-live-provider-runbook.md`, last touched in `dbb29f7`): bring the canary
  section to the final CLI and check it against `main()`'s argparse. It must cover:
  - `preflight`, `execute`, `sweep`, `invoice`;
  - every flag, exactly as argparse spells it;
  - `--authorization`, `--authorization-sha256`;
  - `--source INVOICE|CONSOLE`;
  - the env vars (`MICRODRAMA_DATABASE_URL` loopback only, `MICRODRAMA_OBJECT_STORE_ROOT`, the FILE credential ref
    and its 0600/0400 rule);
  - `canary_db up/down` and `--data-root`;
  - the authorization schema fields, including `episode_id`, the full image ref and the `max_attempts` global-cap
    wording.

  The example files in `runbooks/` must load through the real parser in a test, or show that one already does.
- **Evidence:** `microdrama/evidence/T045.md`, section "T045-FIX (2 Nov)".
  - Complete it for **every** ruling ID across all four sessions: A-*, B-*, RR-*, O-1, O-2, F-1–F-6, and the rest of
    B-S1.
  - Give each ID: its commit, test names, red line and green line.
  - Take earlier sessions' red/green lines from their commit messages and tests. Where a red line was never
    recorded, rerun that test against the parent commit's code. Use a `git worktree add` under the scratchpad with a
    fresh name, and don't remove it afterwards.
  - If a red line can't be obtained, say so plainly.
  - Add a gates subsection with the tails and counts.

## Report

- **Write the full report with the Write tool to**
  `/root/AIVORA/drama-box/docs/microdrama-system/T045-fix-round/T045-FIX-REPORT.md`, not to the
  `--out` file. ai-route overwrites `--out` with your final message.
- Its contents are as brief-t045-fix-final item 7 lists, covering all four sessions, plus:
  - O-1, O-2, F-1–F-6, the rest of B-S1, and each accepted-as-is item;
  - the `git status --porcelain` check;
  - the `/tmp/pytest-of-root` modes;
  - the list of tests whose assertions were loosened or removed across `7f857eb..HEAD`, with reasons.
- **Your final message** is only that path, the HEAD hash and a 5-line summary.

**If you hit a usage limit again:** stop cleanly. Commit only work whose tests pass. Write what is done and what is
left to the REPORT path above.
