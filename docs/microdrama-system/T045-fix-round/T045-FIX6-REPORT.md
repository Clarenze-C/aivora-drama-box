# T045-FIX6 build report (session 6: the Codex review findings CR-1..CR-8)

Branch `feat/microdrama-m0-m4`. Base of this session `72c54fc` (session 5's round
record). All work offline: fixture transports, loopback PostgreSQL only, no provider
call, no live key, no pod, nothing left this machine. Commit, never push.

The review (`codex-review-t045fix5.md`) and its orchestrator rulings were read first;
where the review and a ruling differ, the ruling was applied. All eight findings were
fixed, tests-first with a recorded red line per finding.

## Findings by ID (commit, tests, red → green)

| ID | Commit | What was done |
|----|--------|---------------|
| CR-1 (BLOCKING, O-2) | `ea6a48f` | `_prepare_durable_root`'s traversal check now ends at the data root's PARENT — the server-owned 0700 data root itself is never in the checked chain when it exists. Pinned by a NEW real up/down/up test (`test_up_down_up_restarts_on_the_server_owned_0700_root`): real `EphemeralPostgres` chown/chmod (no faked server user, no `geteuid` patch) leaves the root 0700 postgres-owned, `down` keeps it, the second `up` restarts on the kept data. Red: `SystemExit: 2` naming the root itself. |
| CR-2 (BLOCKING, F-1) | `f1e7b24` | New janitor pass `_complete_absent_terminal_terminates`, right after the orphan scan and before billing: a Runpod terminal lease whose Pod this sweep's successful scan no longer sees gets `terminate_verified_at` written and storage ownership closed WITHOUT a provider DELETE (durable row + scan = the evidence; a second DELETE could double-bill). Skips a failed scan (absence unknowable) and present Pods (the F-1 tail owns those). Red: the ambiguous-success-then-absent scenario left the lease pending forever. |
| CR-3 (BLOCKING, F-1) | `f1e7b24` | Both terminate selections (the F-1 tail and the new pass) exclude leases superseded by a later lease on the same Pod (`NOT EXISTS sup.created_at > cur.created_at`): a warm transfer's historical leases keep their by-design NULL terminate; the final holder owns the terminate. Red: the F-1 selection issued stop + DELETE on a historical lease two transfers deep. Green: a two-transfer history draws zero provider calls and later sweeps add nothing. |
| CR-4 (BLOCKING, F-4) | `c37a836` | The final settle of an open prompt hold is retried `PROMPT_HOLD_SETTLE_ATTEMPTS = 3` times inside the shutdown window; a failure that survives every attempt is escalated AFTER the Pod shutdown and sweep complete: `run_error` takes it, the outcome is NOT_CLEAN and `CanaryRunNotClean` re-raises with the record — never a silent COMPLETE over a possibly-ACTIVE hold. Red: transient `assert 1 == 3`; persistent `DID NOT RAISE CanaryRunNotClean`. |
| CR-5 (F-4) | `461c0b3` | The settle reason is persisted — a `prompt_hold.zero_settled` append-only event in the SAME transaction as the zero settlement (policy check + `record_usage_in_transaction` + event gated on `not replayed`, so a CR-4 retry replays the receipt and appends nothing) — and the `prompt_hold_settled` record step names it. Red: `KeyError: 'reason'`. |
| CR-6 (F-5) | `e94be9d` | `PGSERVICE in os.environ` — any set value, including the empty string, refuses (was a truthy `.get()`). Red: `DID NOT RAISE EffectDenied` with `PGSERVICE=''`. |
| CR-7 (F-2) | `0aceb29` | The record write is wrapped in its own try/finally inside the inner finally: `restore_handlers()` runs on every path out of the shutdown, including a `_write_canary_record()` exception (the write error propagates after the restore). Red: the ignore handlers leaked past a failed record write. |
| CR-8 (runbook) | `0a7b499` | The runbook's invoice section documents `--observed-at` exactly as argparse spells it (when to pass it, and the wall-clock default). Flag-inventory check: all 13 canary argparse flags appear in the runbook. Docs-only; the omission was the review's finding. |

Style follow-up `00f3903` (ruff format over the session's new code; no statement or
assertion changes) and the evidence commit `2adf453` close the sequence.

## Test adjustments (recorded honestly; no assertion weakened)

- `test_without_the_ownership_proof_an_absent_pod_billing_read_is_refused` (unit,
  billing ingestion) — its seed lease (same-tag, terminate NULL, Pod absent) is exactly
  the state CR-2 now completes by absence BEFORE the billing phase, so post-CR-2 the
  seed can no longer produce "ingest attempted but refused". The refused read is now
  pinned on a lease carrying a FOREIGN account label (`provider_account_ref` at INSERT
  time; the tag/account columns are immutable): the durable row proves no ATTESTED
  account owns the Pod, so the ownership probe refuses regardless of what the sweep
  completed. The test's assertion set is unchanged. The `_seed_terminated_lease` helper
  gained `owned_tag` / `provider_account_ref` parameters for this.
- The CR-2 test's invoice-equivalence assertion reads the account counters
  (`settled_micro_usd == 500000`, `reserved_outstanding == 0`, reservation `SETTLED`)
  rather than the raw charge-table SUM: this seed keeps an ACTIVE reservation (unlike
  F-1's pre-settled seed), so the raw SUM legitimately counts the accrual and the BILLED
  settlement separately. No production code changed for this.
- No test had assertions deleted this session.

## Operator checks the briefs demanded

- `git status --porcelain` after the suites: nothing under `microdrama/canary-objects/`
  (the directory does not exist).
- `/tmp/pytest-of-root`: **700 before** the full run, **700 after** (nothing widened —
  the CR-1 code, like O-2's, refuses rather than widens; the new restart test builds
  its own traversable parent exactly like the durable test).
- `stat -c '%a %n' /tmp/claude-0 /tmp/claude-0/-root-AIVORA` → both **700** after the
  gates (unchanged).
- The two `_prepare_durable_root`-related tests kept the basetemp discipline: focused
  runs this session used
  `--basetemp=/tmp/claude-0/-root-AIVORA-drama-box/fix6-t045/basetemp-*`; no chmod of
  `/tmp/claude-0` or its ancestors anywhere.

## SPEC-GAPs

None. CR-2's completion-by-absence is the R9 absent-pod ownership proof read from the
other direction (the durable row + a successful scan), and it stays Runpod-scoped like
the rest of the tail; no contract or guardian-owned validator was touched.

## Gates

All under `systemd-run -p CPUQuota=45%`:

```
make check   → last line: "make check: all offline checks passed" (exit 0)
               contracts-check: contracts 2.15.0: 104 schemas ... OK
               ruff check: All checks passed!  ·  ruff format: 580 files already formatted
               unit 2767 passed, 2 warnings (0:49:20)   [was 2765 at session-5 HEAD: +2 = CR-2, CR-3]
               contract 462 passed (0:05:02)            [unchanged]
               integration 268 passed (0:40:06)         [was 263: +5 = CR-1 restart, CR-4 x2, CR-5, CR-7]
               git diff --check: clean
```

```
make pilot   → exit 0; W01–W12 all OK (W07 GREEN_WITH_UNKNOWNS, W08 APPROVED);
               exactly two gates: GATE1 season_approval APPROVED (HUMAN),
               GATE2 (W08 gate2_approval) APPROVED (HUMAN);
               media exported: 16 file(s); settled micro-usd: 303000 (fake providers)
```

Unchanged from the session-5 close-out gates (same counts, same pilot profile; the
unit/integration counts moved only by this session's new tests, as itemized above).

## Not done

Nothing. Every CR-1..CR-8 finding has code + tests + a recorded red/green pair in the
evidence; docs, evidence and gates are complete; the report is left uncommitted for
the orchestrator to check and commit.
