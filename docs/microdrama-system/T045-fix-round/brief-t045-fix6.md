# Build T045-FIX session 6: the Codex review findings CR-1..CR-8

You continue the T045 fix round in `/root/AIVORA/drama-box` on `feat/microdrama-m0-m4`. This
session fixes the findings of the scoped Codex review of the post-round-2 commits. Everything
is offline: fixture transports, loopback PostgreSQL only, no provider call, no live key, no
pod, nothing leaves this machine. Commit, never push.

## Read first, in this order

1. `docs/microdrama-system/T045-fix-round/codex-review-t045fix5.md` — the review **and the
   orchestrator rulings at the end**. The rulings are binding; where the review and a ruling
   differ, the ruling wins.
2. `docs/microdrama-system/T045-fix-round/brief-t045-fix4.md` — the standing rules (hard
   limits, ordering, no deletion verbs, report path). Still binding.
3. `docs/microdrama-system/T045-fix-round/T045-FIX-REPORT.md` — what sessions 1–5 did.

## Where the tree is

HEAD `c51c709` (evidence-complete commit of session 5) plus this session's docs commits (the
review record, this brief). `git log --oneline 7faef9e..HEAD` shows the reviewed work. The
tree is clean; `make check` (unit 2765 / contract 462 / integration 263) and `make pilot`
(2 gates, 16 exports, 303,000 micro-USD) are green at HEAD, re-confirmed by the orchestrator
under CPUQuota=45% on 4 Nov.

## The work, in this order (tests-first red→green per finding)

1. **CR-1 (BLOCKING, O-2):** `_prepare_durable_root` in `microdrama/tools/canary_db.py`
   includes the existing data root itself in `node_chain` and requires `0o055` on it, so a
   real kept-data restart (root 0700, owned by `postgres` after a real `up`) refuses exit 2.
   The ruling: the traversal check ends at the data root's **parent**; the data root itself is
   never checked when it already exists (the server user owns it; 0700 is its correct state).
   Pin the real restart shape with a test that does not fake the server user or patch
   `geteuid` — the up/down/up sequence against a root left 0700 by "the server" must restart.
2. **CR-2 (BLOCKING, F-1):** an ambiguous terminate (DELETE takes effect at Runpod, returns
   503) strands the lease: the Pod is absent from `find_owned()` next sweep, so the retry tail
   never runs, ingest does not defer, and `durable_pod_ownership_probe` refuses forever. Build
   the verify-by-absence completion: a terminal lease whose Pod is gone gets
   `terminate_verified_at` written and storage ownership closed **without** a provider DELETE
   that could double-bill. Keep it Runpod-scoped like the rest of the tail. Red line: the
   ambiguous-success-then-absent scenario leaves the lease pending before the fix.
3. **CR-3 (BLOCKING, F-1):** the F-1 selection at `janitor.py:643-649` picks up warm-transfer
   historical leases (RELEASED, `terminate_verified_at` NULL **by design**, see
   `leases.py:1334-1347`). Exclude leases superseded by a later lease on the same Pod — the
   final holder owns the terminate. A third sweep must add nothing (idempotency across
   transfers, at least a two-transfer test).
4. **CR-4 (BLOCKING, F-4):** a `settle_open_prompt_hold()` exception at
   `canary.py:1028-1037` logs-and-continues; the hold stays ACTIVE past run end with nothing
   to recover it. Make the failure non-stranding: bounded retry inside the shutdown window,
   and if it still fails, escalate so the hold cannot remain ACTIVE unobserved (fail the run's
   outcome — do not swallow it into `blocked_or_uncertain` alone).
5. **CR-5 (F-4):** persist the settle reason and include it in the `prompt_hold_settled`
   record step (currently only reservation id + amount).
6. **CR-6 (F-5):** `PGSERVICE` set to **any** value — including empty — refuses:
   `PGSERVICE in os.environ`. Test the empty-string case.
7. **CR-7 (F-2):** `restore_handlers()` must run on every path, including a
   `_write_canary_record()` exception (currently outside the inner `finally`). Test: a record
   write failure leaves the original handlers installed.
8. **CR-8 (runbook):** document `--observed-at` in the canary runbook's invoice section,
   spelled exactly as argparse spells it.

Then: evidence (append the CR section to `microdrama/evidence/T045.md` — every CR with a red
line and a green line; label honestly anything you could not record), the full gates
(`make check`, `make pilot`, ruff, `git diff --check`) under `systemd-run -p CPUQuota=45%`,
and the report: write `docs/microdrama-system/T045-fix-round/T045-FIX6-REPORT.md` and leave it
uncommitted (the orchestrator checks and commits it).

## Hard limits (unchanged from fix4/fix5)

- No `rm`, `git rm`, `git clean`, `git reset`, `find -delete`, or any deletion verb anywhere,
  including tests and probes. A hook holds the job 10 minutes on any of these, then refuses.
- Never print env vars, `.env` contents, `Authorization` headers or keys. Never read
  `~/.claude/.env` or `/root/.secrets`.
- Never push. No provider/paid/public action. `canary execute` and `make canary-db` only
  inside pytest.
- The two `_prepare_durable_root`-related tests keep the basetemp discipline from fix4 — if a
  durable-root test needs a scratchpad basetemp, use one, and never chmod `/tmp/claude-0` or
  its ancestors.
- Commit per finding group: `fix(microdrama): T045-FIX CR-n - ...`. Evidence and report last.
- If you hit a usage limit: stop cleanly, commit only work whose tests pass, and write what is
  done and what is left to the REPORT path.
