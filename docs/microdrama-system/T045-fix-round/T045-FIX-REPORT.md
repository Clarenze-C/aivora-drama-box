# T045-FIX build report (sessions 1–5, final)

Branch `feat/microdrama-m0-m4`, base `7f857eb`, HEAD at hand-off `4acc67d`, HEAD at close-out
`0161120`. All work offline/mock: fixture transports, loopback PostgreSQL only, no provider
call, no live key, nothing left this machine. Commit, never push.

## What each session did

- **Session 1–2** (commits `488ba9e..9720a90`): the T045-A review rulings (A-B1, A-S1–A-S8,
  A-N1–A-N9), the T045-B runner rulings (B-B1, B-B2, B-S2–B-S9, B-N1–B-N6) and B-S4.
- **Session 3** (`ff5ae5c..b05b66a`): RR-S4/RR-N1, RR-S1, B-S1, RR-N5, B-S10/B-N7,
  RR-S2/S3/N2, RR-N3/B-N1; stopped on a z.ai usage limit.
- **Session 4** (`4acc67d`): docs-only handoff; stopped on the usage limit with F-1 in flight.
- **Session 5 (this close-out)** (`10d7d31..HEAD`): F-1, F-4, O-1, F-5, F-2, F-3, O-2,
  the rest of B-S1, F-6, the runbook, the evidence, the gates.

## Rulings by ID (commit, tests, red/green)

The per-ID table with every test name and red/green line is
`microdrama/evidence/T045.md`, section "T045-FIX (2 Nov)" (Sections A, B, RR and O/F,
plus accepted-as-is). Commit-by-commit red/green narratives are in each commit message.
Close-out summary:

| ID | Commit | One-line outcome |
|----|--------|------------------|
| F-1 (money) | `10d7d31` + `0161120` | failed terminate retried through the shared stop→terminate→verify→close tail; the billing ingest of a still-unverified terminal Pod defers to the tail (never ingests an unfinal window); follow-up `0161120` scopes the retry to Runpod (the only provider whose tail writes `terminate_verified_at`) after `make check` caught a non-Runpod re-stop loop |
| F-4 (money) | `ac8969c` | a prompt hold no retry can reuse settles at 0 at run end; production FAILED lease-covered attempts settle at once again (`retry_reuses_hold` scopes the deferral to the canary) |
| O-1 | `ee5ae9b` | `MICRODRAMA_OBJECT_STORE_ROOT` (absolute) required for execute/sweep/invoice, refused exit 2 before any call; preflight creates no store; the committed canary object untracked, strays deleted, `.gitignore`, runbook |
| F-5 | `786ad2c` | PGSERVICE refused whenever set; PGHOSTADDR loopback-checked even with a DSN-named host (DSN-pinned hostaddr makes it inert) |
| F-2 | `6991747` | handlers installed inside the try; repeat SIGTERM/SIGINT during shutdown ignored and logged; originals restored only after the record is written; refusal leaks nothing |
| F-3 | `9f06a3b` | the sweep composes the shared `durable_cleanup_guard` (lease-row check); a lease-less owned-NAME Pod is refused with zero stop/terminate calls; the sweep print no longer crashes on stopped_pods |
| O-2 | `13e5e83` | `_prepare_durable_root` never widens an existing directory (refuse exit 2 naming the untraversable ancestor); only tool-created dirs are 0755; the two `_prepare_durable_root` tests run under scratchpad basetemps again |
| B-S1 rest | `1c1a32e` | the FILE resolver lstats (symlink refused) and requires the invoking user's ownership |
| F-6 | `9191bbd` | db mark only on the two tests that use a DB; dead setattrs removed |

## SPEC-GAPs

None. F-3's SPEC-GAP branch was considered and rejected (all ruling-required stops carry a
lease row). F-1 was fixed janitor-side; the guardian-owned contract validator was not touched.

## Accepted as is (recorded in the evidence)

B-S10's "failed attempt is charged" reading (the lease invoice carries its GPU seconds; the
operation row stays FAILED); F-7 (two `Database(...)` constructions, missing `LIMIT` in
`_terminal_podless_lease`); RR-S3's untested partial-first-seed case; the V2 submit base
token; the B-S1-rest check-then-read gap on this single-operator host; A-N5 and B-N4 from
the earlier sections.

## Tests whose assertions were loosened, changed or removed across `7f857eb..HEAD`

- `test_the_default_data_root_is_var_lib_and_its_parent_is_traversable` (canary_db unit) —
  **rewritten by O-2** (`13e5e83`): it asserted the old widening behavior ("makes its parent
  0755 whatever it was"); the O-2 ruling inverts the requirement, so the test now asserts the
  refusal (mode unchanged, nothing created) and the tool-created-0755 chain. This is the
  ruling's own test list, not a quiet loosening.
- `test_up_composes_the_durable_server` and `test_an_injected_seed_failure_leaves_no_running_server`
  (canary_db unit) — **pinned to a non-root caller** (`monkeypatch.geteuid → 1000`) by O-2:
  they fake the server lifecycle and were silently relying on the old widening to prepare
  tmp_path; the traversal behavior is covered by the O-2 tests.
- `test_the_durable_cluster_runs_with_fsync_synchronous_commit_and_full_page_writes` —
  **re-parented** by O-2: it builds its own traversable parent (mkdtemp set 0755 when
  tmp_path's chain is 0700) and asserts tmp_path's mode is unchanged. Its durability
  assertions are unchanged.
- `test_a_zero_amount_is_not_a_missing_amount`, `_main_env`-based CLI tests, the sweep CLI
  test — **extended** by O-1 with `MICRODRAMA_OBJECT_STORE_ROOT` under their own tmp_path
  (the ruling's requirement); no assertions weakened.
- `test_preflight_makes_zero_transport_and_zero_resolver_calls` — **extended** by O-1
  (chdir + no-store assertion); its zero-call assertions unchanged.
- `tests/integration/persistence/test_t045_finality_migration.py` — **formatted only**
  (committed unformatted by an earlier session; `make check`'s format gate caught it;
  no assertion or code change).
- One gate-caught regression, fixed in `0161120` before the final gates: the F-1 retry
  re-stopped a non-Runpod terminal Pod on every sweep
  (`test_dead_worker_expired_lease_is_reclaimed_idempotently`); the retry is now
  Runpod-only. No test assertion was changed for it — the production code moved back to
  the ruling's intent.
- No test had assertions deleted. Earlier sessions' strengthened/renamed tests are listed in
  their own evidence rows (A-S7/A-S8, B-S10).

## Operator checks the briefs demanded

- `git status --porcelain` after the suites: nothing under `microdrama/canary-objects/`
  (the directory does not exist; the only entry ever seen was the staged untrack of the
  stray `.json`, committed in `ee5ae9b`).
- `/tmp/pytest-of-root`: **755 before** the full run (already widened by earlier sessions'
  pre-O-2 code), **700 after** — pytest's own default when it recreated its root; nothing
  in this round widened anything (the O-2 code refuses rather than widens).
- After the gates: `stat -c '%a %n' /tmp/claude-0 /tmp/claude-0/-root-AIVORA` →
  `700 /tmp/claude-0` and `700 /tmp/claude-0/-root-AIVORA` (both 700, as required).
- The red-rerun worktree `wt-t045-red` is kept under the session scratchpad (not removed),
  per the brief.

## Gates

From the real runs at the end of this session (all under `systemd-run -p CPUQuota=45%`):

```
make check   → last line: "make check: all offline checks passed" (exit 0)
               unit 2765 passed, 2 warnings (0:48:39)
               contract 462 passed (0:05:35)
               integration 263 passed (0:38:55)
               ruff check + format clean; contracts-check clean; git diff --check clean
make pilot   → exit 0; W01–W12 all OK (W07 GREEN_WITH_UNKNOWNS, W08 APPROVED);
               exactly two gates: GATE1 season_approval APPROVED (HUMAN),
               GATE2 (W08 gate2_approval) APPROVED (HUMAN);
               media exported: 16 file(s); settled micro-usd: 303000 (fake providers)
```

One intermediate `make check` failed and was fixed before the passing run above: the
format gate caught `tests/integration/persistence/test_t045_finality_migration.py`
committed unformatted by an earlier session (formatted, no content change), and the
integration lane caught the F-1 non-Runpod re-stop loop (fixed in `0161120`). Both are
recorded above and in the evidence.

## The final canary command lines (as the runbook states them)

```bash
# 1) validate the authorization and every gate; print the plan and the sha to approve
python -m microdrama.pipeline.canary preflight --authorization runbooks/canary-authorization.json

# 2) the bounded run itself
MICRODRAMA_OBJECT_STORE_ROOT=/var/lib/microdrama/canary-objects \
python -m microdrama.pipeline.canary execute \
  --authorization runbooks/canary-authorization.json \
  --authorization-sha256 <hex-from-preflight> \
  --prompts runbooks/canary-prompts.json

# 3) one janitor pass over the same attested world
MICRODRAMA_OBJECT_STORE_ROOT=/var/lib/microdrama/canary-objects \
python -m microdrama.pipeline.canary sweep \
  --authorization runbooks/canary-authorization.json \
  --authorization-sha256 <hex-from-preflight>

# 4) verify the operator's period invoice
MICRODRAMA_OBJECT_STORE_ROOT=/var/lib/microdrama/canary-objects \
python -m microdrama.pipeline.canary invoice \
  --authorization runbooks/canary-authorization.json \
  --pod-id <pod-id> --period-start <iso> --period-end <iso> \
  --amount-micro-usd <int> --source INVOICE --evidence <invoice-file>

# the dedicated canary database
make canary-db            # or: python tools/canary_db.py up   [--data-root <abs>]
python tools/canary_db.py status
python tools/canary_db.py down [--data-root <abs>]
```

Env: `MICRODRAMA_DATABASE_URL` (loopback only, never from argv),
`MICRODRAMA_OBJECT_STORE_ROOT` (absolute, required for execute/sweep/invoice).
Both example files in `runbooks/` load through the real parsers in tests
(`test_the_example_authorization_file_is_valid`,
`test_the_example_prompts_file_loads_against_the_example_authorization`).

## Not done

- A-section red lines for `488ba9e` (A-N6), `e2f6899` (A-B1/N3/N4) and `5d208f5`
  (A-S1/A-S4) were never recorded by the earlier sessions and were **not** rerun in this
  close-out (usage budget); the evidence says so plainly and their suites pass on HEAD.
- Same honest gap for B-S2/B-N3, B-S3/B-S9, B-S5, and the B-S6/S7/S8+B-N1/N2/N5/N6 group:
  red lines never recorded; suites pass on the HEAD gates.
- Everything else in the four briefs is done: every ruling ID has code + tests + evidence,
  docs are at the final CLI, and the gates below are green.
