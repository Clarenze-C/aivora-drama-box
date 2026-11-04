# Scoped review round 3: the CR-3-residual and CR-9 fixes (Codex, read-only)

You are the same independent reviewer lane that produced `codex-review-t045fix5.md` and
`rereview-t045fix6.md`. The GLM build session 7 claims the two remaining BLOCKING findings
are fixed. Operator-approved third round, scoped to ONLY these two fixes. READ-ONLY: no
edits, no commits, no destructive git, no provider/paid/public command.

## Scope

Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`, diff `e56c952..HEAD`
(HEAD `1ce71cb`): `d7f59a6` (CR-3 residual), `d10e1cb` (CR-9), `1ce71cb` (evidence only).

## Read first

1. `docs/microdrama-system/T045-fix-round/rereview-t045fix6.md` — your round-2 findings and
   the orchestrator rulings at the end (binding).
2. `docs/microdrama-system/T045-fix-round/brief-t045-fix7.md` — what the session was told.
3. `docs/microdrama-system/T045-fix-round/T045-FIX7-REPORT.md` — the session's claims and
   its two honest notes (the seeded storage-ownership row; the basetemp-cleaner incident).

## Verify (only this)

1. **CR-3 residual:** `_sweep_billing_ingestion`'s `has_unverified_terminal_lease`
   (`rendering/janitor.py:924-934`) now excludes superseded leases with the same
   `NOT EXISTS` predicate the terminate selections use. The green line the ruling demanded:
   a test pinning successful ingestion and finality progress (buckets stored, readiness
   advancing) through an A→B→C history with C verified and the Pod present — check that
   test exists and actually asserts that (not just zero-provider-call stability).
2. **CR-9:** both terminate selections — the F-1 tail (`janitor.py:643-666`) and the
   absence-completion pass (`janitor.py:779-801`) — match the manager's configured
   `provider_account_ref` on the durable lease row; an unconfigured label selects nothing.
   Check the tests pin: an empty scan of account A leaves a same-tag foreign-account
   terminal lease untouched (no terminate stamp, no storage-ownership closure), and the
   F-1 tail ignores a foreign-account lease for a present Pod.
3. No new defects introduced by these two commits; no assertion quietly weakened.

In-memory/offline probes are allowed if your sandbox permits; `systemd-run` may fail for
you — record that honestly. Do not run `canary execute` or `make canary-db` outside pytest.

## Output — sandbox constraint

Do NOT attempt to write a report file. Put the COMPLETE report in your final message
(stdout), compactly: verdict line first (`VERDICT: ACCEPT` or `VERDICT: FIX-REQUIRED`),
then per-finding verdicts (SATISFIES-RULING / VIOLATES with file:line and one line why),
then any new findings (CR-10, ... with severity).
