# Scoped re-review: the CR-1..CR-8 fixes (Codex, read-only)

You are the same independent reviewer lane that produced
`docs/microdrama-system/T045-fix-round/codex-review-t045fix5.md` (FIX-REQUIRED, CR-1..CR-8).
The GLM build session 6 claims all eight are fixed. This re-review covers ONLY the fixed
findings and the two test adjustments the session recorded. READ-ONLY: no edits, no commits,
no destructive git. No provider/paid/public command; nothing leaves this machine.

## Scope

Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`, diff `72c54fc..HEAD`
(HEAD `2adf453`): commits `ea6a48f` (CR-1), `f1e7b24` (CR-2/CR-3), `c37a836` (CR-4),
`461c0b3` (CR-5), `e94be9d` (CR-6), `0aceb29` (CR-7), `0a7b499` (CR-8), `00f3903` (format),
`2adf453` (evidence).

## Read first

1. `docs/microdrama-system/T045-fix-round/codex-review-t045fix5.md` — your findings and the
   orchestrator rulings appended at the end (binding).
2. `docs/microdrama-system/T045-fix-round/brief-t045-fix6.md` — what the session was told.
3. `docs/microdrama-system/T045-fix-round/T045-FIX6-REPORT.md` — the session's claims,
   including its two test adjustments.

## Verify

1. Each of CR-1..CR-8: does the fix satisfy the finding's ruling (not merely look
   reasonable)? Key shapes to check:
   - CR-1: the traversal chain ends at the data root's parent when the root exists; a real
     up/down/up restart on a 0700 server-owned root passes (no `geteuid` patch).
   - CR-2: absent-Pod terminal leases complete by absence with no provider DELETE; a failed
     scan skips the pass; present Pods stay with the F-1 tail.
   - CR-3: both terminate selections exclude superseded leases; a two-transfer history draws
     zero provider calls; a third sweep adds nothing.
   - CR-4: settle failure → bounded retries → NOT_CLEAN + `CanaryRunNotClean`, never a silent
     COMPLETE over a possibly-ACTIVE hold.
   - CR-5: the reason is persisted transactionally and named in the record step.
   - CR-6: `PGSERVICE in os.environ` (empty string refuses).
   - CR-7: `restore_handlers()` on every path including a failed record write.
   - CR-8: the runbook documents `--observed-at` exactly as argparse spells it.
2. The two test adjustments in T045-FIX6-REPORT.md are not quiet weakenings: the re-seeded
   refused-read test still pins the ownership refusal; the account-counter invoice assertion
   still proves billing equivalence for its seed.
3. No new defects in the changed code.

You may run focused offline suites (e.g. `tests/unit/rendering tests/unit/pipeline`) if your
sandbox permits; do not run `canary execute` or `make canary-db` outside pytest. If the
sandbox blocks a command, record that limit honestly — code-trace review is acceptable.

## Output — IMPORTANT (sandbox constraint)

File writes were refused in your last run. Do NOT attempt to write a report file. Put the
COMPLETE report in your final message (stdout), compactly: verdict line first
(`VERDICT: ACCEPT` or `VERDICT: FIX-REQUIRED`), then per-CR verdicts
(SATISFIES-RULING / VIOLATES with file:line and a one-line why), then the two test
adjustments (LEGITIMATE / WEAKENED with why), then any new findings
(CR-9, ... with severity BLOCKING / NON-BLOCKING / NIT).
