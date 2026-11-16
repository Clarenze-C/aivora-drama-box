# T031 H-2 build — benchmark recovery per spec v3 (GLM build, Large)

Orchestrator: Opus, 10 Nov 2026. The operator approved building spec v3. You are the
builder.

## The spec is the requirement

Read it fully first:
`/root/AIVORA/drama-box/docs/microdrama-system/T031-H2-recovery-spec.md` (v3).

Also read:
- `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-codemap.md`, a
  verified map of the current code;
- `/root/AIVORA/drama-box/docs/microdrama-system/T031-integration-contract.md` (§A, §C,
  §E, §F, §G).

Where the spec quotes Codex's replacement wording (R1–R8, SC2-1..SC2-3), that wording is
binding. If anything in the spec is impossible against the code, or contradicts the
contract, **stop that package at a red test** and explain it in the report. Do not
invent behaviour. Record every judgement call you make, with the reason.

## Where

- Worktree (your cwd): `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, branch
  `feat/t031-fix3`, HEAD `82135d4`. That includes GLM's CN2/H-1/H-2 commits and Luna's
  H-3..H-9 WIP, which is under a separate GLM review.
- Replace the H-2 implementation of `628fe5b` wherever v3 differs. Keep everything else.
- Commit on top. Never amend or rewrite. `microdrama/.venv` is a symlink: never stage
  it.

## Work packages, in order

Commit at the end of each package with its ATs green. After **each** package, update the
report (below) so that another builder could resume from it.

| Pkg | Spec sections | Acceptance tests |
|-----|---------------|------------------|
| P1 | §3 (modes, provenance, EXPIRED-read exception with R4, binding), §8 persistence (edit 0026 in place, keep all guards, update the schema tests) | AT-4, AT-20, AT-23, AT-24 |
| P2 | §4 (`unresolved_items` U1–U6 + U3p, blocking scopes, first-send right, gate placement, CLI `resume` ordering) | AT-0, AT-5, AT-10, AT-11, AT-13, AT-14 (plus the §9.3 extensions for AT-0/AT-10) |
| P3 | §5 (classification, pending submit, uploads, durable grace with R3 and SC2-2, deadline fence) | AT-1, AT-2, AT-3, AT-15, AT-16, AT-17, AT-18, AT-19, AT-25 (plus the §9.3 extensions) |
| P4 | §6 (shared lock order with R5, billing-wrapper reorder, `resolve_create` with SC2-3 replay, storage release only at sweep with R1, contradiction incident path) | AT-6, AT-7, AT-21, AT-26 (plus the §9.3 extensions) |
| P5 | §7 (`finalize_terminal`, mapping, monotonic projection, R6 atomic fail-fast, operator resolution with R7) | AT-8, AT-9, AT-12 (with R8), AT-22 (plus the §9.3 extensions) |

Within each package, follow these rules:

- **Tests first:** run each new AT red and record its pytest summary line, then
  implement it.
- **Real PostgreSQL** for every lock and race test (use the integration fixtures; two
  or more connections, barriers, and a bounded `lock_timeout`).
- **At least one real subprocess SIGKILL/`os._exit` death test** (§9.3 death harness).
  Fake provider state and send counters must persist outside process memory.
- **Never call `_advance` directly**, except AT-10 as the spec allows.
- **The fake ComfyUI server lives only as long as its fake pod.**
- **Restore the cleanup fixture's strictness:** `terminate_verified_at` plus the two
  dropped assertions.

## Hard limits

- Offline only. Export `MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK
  MICRODRAMA_PAID_REQUESTS_ENABLED=false MICRODRAMA_CLOUD_RESOURCES_ENABLED=false
  MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false`.
- No provider or network calls, no docker build or push, no pod creation, no service
  restarts, no clearing of shared data. No pushes, no merges.
- No contract package change. Leave migrations 0001–0025 alone. Edit only 0026, in
  place.
- The only canonical edits allowed are those the spec permits: the billing-wrapper lock
  order (§6.1), the EXPIRED recovery-read exception (§3.3) and the `_settle_if_needed`
  EXPIRED handling. The canonical and canary suites must stay green (AT-26).
- Run every pytest under `systemd-run --scope -p CPUQuota=45% --quiet` with
  `--basetemp=/tmp/t031-h2b-basetemp`. Keep each command under 10 minutes and run
  focused files. For anything longer, run it as
  `systemd-run --unit=t031-h2b-<name> -p CPUQuota=45% --collect` and read its log
  afterwards.
- Never print env vars, `.env` files, keys, tokens or auth headers. Use synthetic
  secrets only.
- No deletion commands in shell (`rm`, `git rm`, `git clean`, `git reset`,
  `find -delete`). Overwrite files instead.
- Do NOT run the full `make check` or `make pilot`. The orchestrator runs them.

## Report

`/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/h2-build-REPORT.md`, a
separate file from `--out`. Update it after every package. It must contain:

- each package's status, with its commit hashes;
- red/green pytest summary lines for each AT;
- the transaction-inventory table (function → locks in order → writes; canonical
  suffix-only vs full-order transactions);
- every judgement call, with its reason;
- anything stopped at red, and why;
- a "Resume here" line naming the next package or AT.

Final message: one line per package, then the report path.
