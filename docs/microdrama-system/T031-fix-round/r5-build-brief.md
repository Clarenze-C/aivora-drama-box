# R5 build: T031 run-readiness packages R5a–R5f (GLM build; drama-box repo)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. Spec v0.3 is accepted for building (Goldfish resolved,
Codex round-1 critique applied per `r5-critique-rulings.md`; all 12 findings folded in).

## The spec is the requirement

Read fully: `/root/AIVORA/drama-box/docs/microdrama-system/T031-run-readiness-spec.md` **v0.3** (560
lines). Build §6's packages **in order**: R5a → R5b → R5c → R5d → R5e → R5f, one commit each, tests
first. The RR acceptance tests (T1–T17) are in §5; the file map is §6's table. If anything is impossible
against the code, stop at a red test and explain — never silently deviate, never weaken an RR row.

Also read:
- `T031-fix-round/r5-critique-rulings.md` (why each replacement is there; R5C-10 = placement (a));
- `T031-fix-round/codex-r5-critique.md` (the findings behind the rulings — the review's file:line cites
  are your map of today's behavior);
- `phase-A0-spec.md` is **not** in scope; H-2 recovery semantics are referenced but not changed (§2).

## Where you work

- Worktree `/root/AIVORA/drama-box/.scratch/t031-r5`, branch `feat/t031-r5`, starting at `104b26b`
  (the `feat/t031-fix3` tip). Commit on top; never amend; never rebase; never merge.
- `microdrama/.venv` is a symlink to the main checkout's venv (created by the orchestrator): never
  stage it.
- **If `T031-fix-round/r5-build-REPORT.md` already exists, you are resuming:** read it, continue from its
  "Resume here", don't redo committed packages.

## Package notes (spec §6 is authoritative; these are the traps)

- **R5a:** the flag must travel the **composed** path `_spec_for()` → `PodSpec.to_request()` → transport
  env (R5C-4); the benchmark create guard requires intent **and** composed request `True` before POST.
  The image rebuild is **local only** (`docker build`, no push, no registry calls) under the documented
  flock/CPUQuota command from `deployment/pika-h3-flex/README.md:13-16`; adapt the superseded
  `BUILD_EVIDENCE.md` variant's paths. The operator pushes the image — you never do.
- **R5b:** boot handling covers warmup/endpoint discovery **before** `acquire()` completes; typed
  pre-sample boot failures bypass the generic terminal handler (no sample/model outcome); acquisition
  records land on a deterministic prepared-but-unclaimed sample row keyed by acquisition ID; lease
  liveness is maintained during the 25-min wait (deadline checks before every request and after sleeps;
  transport timeout bounded by remaining time); persisted initial readiness so recovery never
  re-classifies admitted work as BOOT_TIMEOUT. Role/subject-scoped upload verification (R5C-5 office
  reuse). RR-T5 includes pending state + missing endpoint with exactly one create, and the minute-40
  recovery case.
- **R5c:** prediction + seal evidence, **one commit** for all touch points; live verification stays
  decisive.
- **R5d/R5e:** the two tools, per §6 file lists.
- **R5f:** thin `t031_billing_verify.py` wrapper over the existing `RunpodInvoiceFinality` verifier —
  **no new verification logic, no migration, no network calls** (offline tests only).
- **No new migrations at all** (0026 is the tail at your base; 0027 belongs to the A0-D branch).

## Test rules

- Tests first per package: record the red lines against the base, then implement, then green.
- Real PostgreSQL where the path touches the DB (admission locks, acquisition records, attempt
  enforcement).
- The offline env vars and pytest incantation:
  `env PATH="/usr/sbin:$PATH" systemd-run --scope -p CPUQuota=45% --quiet microdrama/.venv/bin/python -m pytest …`
  from the `microdrama/` directory, with `MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK
  MICRODRAMA_PAID_REQUESTS_ENABLED=false MICRODRAMA_CLOUD_RESOURCES_ENABLED=false
  MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false` and `--basetemp=/tmp/t031r5-basetemp`. Keep each command
  under 10 minutes. **No interactive flags (`--pdb`)** — use `-x` and read the output.
- `make lint` before every commit. `make check` green per commit is the spec's bar — but another
  builder may be running pytest concurrently, so run `make check` at commit points only (not on every
  iteration), under the same CPUQuota scope.
- For red runs, never stash: use `git show <rev>:<path> > <path>` or a WIP commit on a scratch branch.

## Hard limits

- Offline only: no RunPod API calls, no paid/cloud/public anything, no pushes (git **or** docker), no
  merges, no service restarts, no deletion commands (`rm`, `git rm`, `git clean`, `git reset`,
  `find -delete`). Never leave work only in a stash.
- Never print environment variables, `.env` files, keys or tokens.
- Don't run `make pilot`. The orchestrator runs the full gate after the Codex review.

## Pace

At the z.ai limit or a 429: stop at a clean point, commit green work, list anything uncommitted in the
report, update "Resume here".

## Report

Write `/root/AIVORA/drama-box/docs/microdrama-system/T031-fix-round/r5-build-REPORT.md` (separate from
`--out`). It must contain: per-package status and commits; red/green lines per RR test; the local image
rebuild evidence (command, digest, no push); judgement calls; anything stopped at red; "Resume here".
When R5a–R5f are done, put `R5: ALL PACKAGES DONE` at the top. Final message: one line per package,
then the report path.
