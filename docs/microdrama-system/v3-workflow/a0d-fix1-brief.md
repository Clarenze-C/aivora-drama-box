# A0-D fix round 1: the 13 Codex findings AD-1..AD-13 (GLM build; drama-box repo)

Orchestrator: GLM (weekend runbook), 13 Nov 2026. The A0-D build (D1–D3) is committed and the full gate is
green at `ea1cc10`, but the Codex review round 1 returned **FIX-REQUIRED**: 10 BLOCKING + 3 SHOULD-FIX.
You fix all 13 on top of `ea1cc10`. Nothing merges and nothing ships this weekend; a round-2 review follows.

## Read first (absolute paths)

- `codex-review-a0d.md` — the findings, each with file:line and a Fix direction. **This file is your
  requirement list.** Where this brief and that file disagree, the review file wins; say so in your report.
- `a0d-build-REPORT.md` — what was built, the transaction inventory and the recovery-table matrix so far.
- `phase-A0-spec.md` v0.4 §4–§5 — the binding spec (§4.3 recovery table, §5.1 step table, §5.3 reconciler).
- A0-R1's actual validator interface (read-only reference for AD-1):
  `/root/.claude/.claude/worktrees/a0r1-airoute/scripts/ai_route.py`. The authoritative contract is
  `phase-A0-spec.md` §3; the worktree shows how the real CLI validates invocations. **Never modify anything
  under `/root/.claude`.**

## Where you work

- Worktree `/root/AIVORA/drama-box/.scratch/a0d-gateway`, branch `feat/a0d-gateway`, currently at `ea1cc10`.
  Commit on top; never amend; never rebase.
- `microdrama/.venv` is a symlink: never stage it.
- **If `a0d-fix1-REPORT.md` already exists, you are resuming:** read it, continue from its "Resume here".

## Fix clusters (suggested commit order; one cluster per commit is fine)

1. **Gateway invocation + ledger safety** — AD-1, AD-2, AD-8.
   - AD-1: propagate the complete frozen request (model, deadline, prompt, schema, budget — everything the
     real A0-R1 CLI validates) through the launcher; bind the expected policy identity; make the test shim
     enforce the same interface instead of silently re-reading `request.json`.
   - AD-2: require canonical UUIDs (not just length) before every ledger lookup; enforce path containment
     so no client-supplied ID can escape the root-owned store (`/etc` must be refused, not written).
   - AD-8: a failed or timed-out `systemd-run`/`systemctl show` is an **inspection failure**, not proof of
     absence; reconcile ambiguous launches by deterministic unit name; unresolved work stays blocking.
2. **Reconciler recovery + fencing** — AD-3, AD-4, AD-5, AD-12, AD-13.
   - AD-3: real pending-submit crashes have a null external ID. Recover the invocation ID through
     `llm_invocations.operation_id` for reconciliation **and** cancellation. Fix the tests that
     artificially retain an external ID — model the real condition (lost POST ack, unreachable GET).
   - AD-4: settled recovery (NOT_FOUND/DONE/REFUSED/CANCELLED) must resume or finish the handler under the
     reconciler's lease — no waiting for lease expiry, no janitor FAILED/LEASE_EXPIRED on completed work;
     refusal recovery keeps the quota deferral timing; attempt accounting preserved.
   - AD-5: fence every reconciler mutation by its lease: guard each mutation, reload state in the same
     transaction, take the job lock before the operation lock. Add a two-connection reconciler/janitor
     race test (real PostgreSQL).
   - AD-12: the shipped reconciler CLI must actually run (open the pool — context manager).
   - AD-13: `PENDING_SUBMIT + UNKNOWN` goes straight to operator reconciliation (UNKNOWN precedence over
     the "existing record" row).
3. **Health, isolation, adoption, evidence** — AD-6, AD-7, AD-9, AD-10, AD-11.
   - AD-6: red gateway health must still let existing operations be polled and settled (required FAILED
     settlement then LlmBlocked; transport-deferral path for outages) while refusing new admissions.
   - AD-7: persist the qualification-bound isolation quarantine, restore it before serving, and enforce it
     at launch (`pump()` stops launching queued work while latched).
   - AD-9: one shared result-envelope + integrity + frozen-schema validation used by normal adoption,
     recovery and the gateway result reader. `{}` against a schema requiring `line` must never be
     SUCCEEDED/DONE.
   - AD-10: persist **every** settled attempt and its `quota_observations` row in production paths
     (refusal/cancellation mirror attempts too); reject conflicting attempt replays instead of silently
     ignoring them.
   - AD-11: cancellation vs completion race — reconcile all authoritative terminal answers, keep job
     cancellation, discard content output, no operation left in flight forever.

## Test rules

- **Tests first per finding:** one red line per AD id (named `test_ad1_…` … `test_ad13_…` or in the matching
  existing suites), recorded red in the report, then green. A finding you believe is wrong: stop at the red
  test and explain — never silently deviate, never weaken an acceptance row.
- Real PostgreSQL for transitions, leases and the AD-5 race. Real transient systemd units where gateway
  launch/recovery is exercised (prefix `dramabox-llm-test-`, fake ai-route shim, `setsid` grandchildren,
  SIGKILL tests, clean up your own units afterwards).
- **No interactive pytest flags (`--pdb`, `-i`):** a hung debug session wastes the build. Use `-x` and read
  the output.
- **No new migrations.** 0027 already allocates every table this fix touches; AD-10 writes rows, not
  schema. (0028–0031 are reserved for A1.)

## Hard limits (same as the A0-D build)

- Offline only: OFFLINE_MOCK with paid/cloud/public off. No model, quota or network calls. No real
  `claude`, never real credentials. Never print environment variables, `.env` files, keys or tokens.
- No pushes, no merges, no service restarts other than your own test units.
- pytest under `systemd-run --scope -p CPUQuota=45% --quiet`, `--basetemp=/tmp/a0d-basetemp`, each command
  < 10 min. **`env PATH="/usr/sbin:$PATH" …`** (the PG fixture needs `runuser`).
- Export `MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK MICRODRAMA_PAID_REQUESTS_ENABLED=false
  MICRODRAMA_CLOUD_RESOURCES_ENABLED=false MICRODRAMA_PUBLIC_ACTIONS_ENABLED=false`.
- No deletion commands (`rm`, `git rm`, `git clean`, `git reset`, `find -delete`). No stash-only WIP: red
  runs use `git show <rev>:<path> > <path>` or a WIP commit on a scratch branch.
- `make lint` before every commit.
- Don't run the full `make check` or `make pilot` — the orchestrator runs them after review round 2.

## Pace

At the z.ai limit or a 429: stop at a clean point, commit green work, list anything uncommitted in the
report, update "Resume here".

## Report

Write `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/a0d-fix1-REPORT.md` (separate from
`--out`). It must contain: per-AD-id status and commits; red/green lines per finding; any deviation with
its reason; anything stopped at red; "Resume here". When all 13 are done, put `A0-D FIX1: ALL FINDINGS
ADDRESSED` at the top. Final message: one line per AD id (CLOSED / red-stopped + why), then the report path.
