VERDICT: FIX-REQUIRED

> **Provenance (GLM orchestrator, 2026-11-04):** Codex ran this review (488 s, 169,577 tokens,
> `ai-route review --base 7faef9e --effort xhigh`, tag `dramabox-t045fix5-review`) but its
> read-only sandbox rejected the report write. The content below is recovered verbatim from the
> Codex session rollout (`~/.codex/sessions/2026/11/04/rollout-2026-11-04T06-58-58-*.jsonl`,
> the rejected `apply_patch` payload). The four BLOCKING claims were independently re-verified
> against the code by the orchestrator before rulings (see the rulings section at the end).

# T045-FIX post-round-2 scoped review

Scope: `git diff 7faef9e...HEAD` on `feat/microdrama-m0-m4`. The review is read-only with respect to code, commits, and provider state. Findings below concern the binding rulings in `brief-t045-fix4.md` and the changed paths. No live provider, canary, or paid command was run.

## Findings

### CR-1 — BLOCKING — `microdrama/tools/canary_db.py:78-93`

**Failure scenario:** After a real `canary_db up`, `EphemeralPostgres.start()` makes the data root itself 0700 and owned by `postgres` (`microdrama/src/microdrama/testing/services.py:108-116`). `down` keeps that root. On the next `up`, `_prepare_durable_root` includes the existing **root itself** in `node_chain` and requires group and other execute bits (`0o055`), so it exits 2 even though `postgres` owns and can traverse the 0700 root. The `up/down/up` test uses a fake server and patches `geteuid` to 1000, so it cannot catch the real restart failure. The real durable test starts only once.

**Ruling violated:** O-2 says to check every ancestor “from `/` down to the data root's **parent**,” while “the data dir stays 0700, owned by the server user.” This also regresses RR-S3's kept-data restart requirement. The changed-tests list accurately names the re-parented and patched tests, but its stated coverage does not verify this required root-user restart.

### CR-2 — BLOCKING — `microdrama/src/microdrama/rendering/janitor.py:613-633,843-861`

**Failure scenario:** A DELETE may take effect at Runpod and return 503. The first sweep then records no `terminate_verified_at`. On the next sweep the Pod is absent from `find_owned()`, so the retry tail is never entered. Ingestion does not defer because `_present_owned_pod_ids` is empty; `billing_history()` then refuses the absent Pod because `durable_pod_ownership_probe` requires a verified terminate (`rendering/runpod_billing.py:58-75`). No later phase writes the missing timestamp or closes storage ownership. The lease remains pending with open ownership indefinitely. The F-1 fixture forces the Pod back to RUNNING after 503, so it does not cover the ambiguous-success case.

**Ruling violated:** F-1 requires the failed terminate tail to retry through stop → terminate → verify → `close_storage_ownership`, with readiness then able to advance to invoice match; it applies to every terminal lease, not only adopted ones.

### CR-3 — BLOCKING — `microdrama/src/microdrama/rendering/janitor.py:643-665,809-849`

**Failure scenario:** A warm transfer intentionally makes the old lease RELEASED with `terminate_verified_at = NULL` while a new lease holds the same Pod (`rendering/leases.py:1334-1378`). After the new lease terminates and verifies, Runpod can still list the Pod as TERMINATED. The F-1 query selects the old transferred lease as an “unverified” termination, issues another DELETE, and the billing query defers while that old row remains NULL. A 503 on that unnecessary DELETE can block ingest and invoice finality despite the final holder's verified termination. With multiple transfers, the scan can repeat this across historical leases. The F-1 idempotency test has only one lease.

**Ruling violated:** F-1's retry is for an owned Pod **held by** a terminal lease whose terminate failed. A transferred-away historical lease is no longer the holder; its NULL terminate timestamp is intentional under the warm-transfer contract. The ruling also requires a third sweep to add nothing.

### CR-4 — BLOCKING — `microdrama/src/microdrama/pipeline/canary.py:1023-1039`

**Failure scenario:** If `settle_open_prompt_hold()` raises a `MicrodramaError` during final settlement, the loop logs the error and continues shutdown. No later prompt-hold recovery is scheduled: the janitor's unbound-hold pass does not settle `comfy.queue_prompt` holds. The reservation can therefore remain ACTIVE after the run, including past expiry. A database or budget error at exactly this point reproduces the path; the F-4 test covers only a successful zero settlement.

**Ruling violated:** F-4 says that when a prompt ends without success, its open hold “must not stay reserved” and must settle at 0 with a reason.

### CR-5 — NON-BLOCKING — `microdrama/src/microdrama/rendering/comfy_jobs.py:1072-1116`

**Failure scenario:** The new settlement method accepts `reason` but never reads or stores it. The caller's `prompt_hold_settled` record step contains only reservation ID and amount, so a reviewer cannot tell whether the zero settlement followed an attempt cap, deadline, interruption, or other stop. The successful F-4 test checks only the reservation state and amount.

**Ruling violated:** F-4 requires settling the hold “at 0 **with a reason**.”

### CR-6 — NON-BLOCKING — `microdrama/src/microdrama/pipeline/canary.py:450-457`

**Failure scenario:** The guard uses `if os.environ.get("PGSERVICE")`, which accepts an explicitly set empty `PGSERVICE`. A local no-network probe with `PGSERVICE=''` and `host=localhost dbname=canary` returned normally. The F-5 test covers nonempty service names only.

**Ruling violated:** F-5 says “`PGSERVICE` set (**any value**) → refuse, always.” This is a literal guard gap; an empty value may be inert in libpq, but the binding rule does not exempt it.

### CR-7 — NON-BLOCKING — `microdrama/src/microdrama/pipeline/canary.py:1080-1099`

**Failure scenario:** If `_write_canary_record()` raises (for example, evidence storage becomes unwritable), control skips `restore_handlers()` because it is outside the inner `finally`. The process that catches that write error retains the shutdown handler that silently ignores future SIGTERM/SIGINT. The F-2 tests cover successful record writes.

**Ruling violated:** F-2 requires original handlers to be restored after the shutdown/record path and repeat signals to be ignored only while shutdown runs.

### CR-8 — NIT — `docs/microdrama-system/T045-live-provider-runbook.md:221-224`

**Failure scenario:** The runbook lists the invoice options but omits `--observed-at`, which `canary.py:1394,1540` parses and forwards. An operator relying on the documented flag inventory cannot discover that option.

**Ruling violated:** `brief-t045-fix4.md` requires the canary runbook to cover “every flag, exactly as argparse spells it.”

## Per-ruling disposition

| Ruling | Result | Why |
|---|---|---|
| F-1, including `0161120` | VIOLATES | The Runpod-only follow-up prevents the non-Runpod re-stop loop, but an ambiguous successful DELETE can strand an absent Pod's lease, and transferred-away leases are mistaken for failed terminations (CR-2, CR-3). |
| F-4 | VIOLATES | The normal failed-final-attempt and production FAILED paths are correctly separated, but settlement failure leaves a hold ACTIVE and no reason is recorded (CR-4, CR-5). |
| O-1 | SATISFIES-RULING | Effectful CLI commands require an explicit absolute root before provider/resolver construction; preflight creates none; tests use temporary roots; the stray JSON is untracked and `.gitignore` covers the directory. |
| F-5 | VIOLATES | Named-host `PGHOSTADDR` probes pass, but an explicitly set empty `PGSERVICE` is accepted (CR-6). |
| F-2 | VIOLATES | Repeat SIGTERM/SIGINT and refusal tests pin the normal path, but a record-write exception leaks the ignore handlers (CR-7). |
| F-3 | SATISFIES-RULING | Sweep and execute use the extracted durable lease guard; the ghost-Pod test pins zero stop/DELETE effects and owned-Pod tests still exercise cleanup. |
| O-2 | VIOLATES | Existing 0700 ancestors are refused without chmod, but the check incorrectly includes the server-owned 0700 data root and blocks a real kept-data restart (CR-1). |
| B-S1-rest | SATISFIES-RULING | `lstat` rejects key-file symlinks and the effective-UID check rejects foreign owners; the accepted check/read gap is documented. |
| F-6 | SATISFIES-RULING | The module-wide DB mark is gone; only the two DB-using tests are marked, and dead monkeypatch lines were removed without assertion changes. |

## Test and evidence audit

- `T045-FIX-REPORT.md` correctly identifies the O-2 rewrite, two non-root pins, durable-test re-parenting, O-1 environment additions, and formatting-only migration-test change. `git diff -U0 7faef9e...HEAD -- microdrama/tests` shows no deleted assertion. The O-2 changes leave the real restart case untested (CR-1); this is a coverage failure, not an unlisted assertion deletion.
- `microdrama/evidence/T045.md` explicitly labels A-N6, A-B1/N3/N4, A-S1/S4, B-S2/N3, B-S3/S9, B-S5, and B-S6/S7/S8 plus B-N1/N2/N5/N6 as lacking recorded red lines. It cites passing HEAD gates rather than fabricating red results. The F-2 SIGINT row also candidly says its red test passed on the parent. The close-out report claims `make check` and `make pilot` green at HEAD; those runs were not independently repeated here.
- `git diff --check 7faef9e...HEAD` passed. A lightweight local F-5 probe confirmed CR-6. The CPU-scoped focused pytest attempt could not start: `systemd-run` returned `Failed to connect to bus: Operation not permitted`. No suite result is claimed from this review.

---

## Orchestrator rulings (GLM-5.3, 2026-11-04)

All eight findings are **accepted as BINDING**, including the three NON-BLOCKING and the NIT:
each names a concrete deviation from binding ruling text (O-2, F-1, F-4, F-5, F-2, and the
fix4 runbook requirement), so "non-blocking" sets fix-order priority, not an exemption.

Re-verification by the orchestrator before these rulings:

- **CR-1** confirmed at `tools/canary_db.py:83-101`: `node_chain` starts at the deepest
  existing node — the data root itself when it exists — and line 91 requires `0o055` on every
  member. A postgres-owned 0700 root from a real `up` refuses the restart with exit 2.
- **CR-2** confirmed at `rendering/janitor.py:633-651` (tail runs only over `find_owned()`
  results) and `:844-848` (deferral requires the Pod in `_present_owned_pod_ids`); the
  absent-pod path requires the verified-terminate timestamp nothing will ever write.
- **CR-3** confirmed at `rendering/leases.py:1334-1347`: the warm transfer deliberately leaves
  the old lease without a verified stop ("a lease that transferred away has no verified stop of
  its own"), which the F-1 selection at `janitor.py:643-649` treats as a failed terminate.
- **CR-4** confirmed at `pipeline/canary.py:1028-1037`: settle failure → `continue`; no later
  phase re-attempts the settle.

Fix requirements (session 6, brief `brief-t045-fix6.md`):

- **CR-1:** the traversal check ends at the data root's **parent**; the data root itself is
  never in `node_chain` when it already exists. The real kept-data restart (root 0700,
  server-owned) must be pinned by a test that does not fake the server user.
- **CR-2:** the F-1 tail must be completable for a Pod the scan no longer sees — a
  verify-by-absence path that writes `terminate_verified_at` and closes storage ownership for
  a terminal lease whose Pod is gone, without a provider DELETE that could double-bill.
- **CR-3:** the F-1 selection must exclude leases superseded by a warm transfer (a later lease
  on the same Pod holds the terminate responsibility); a third sweep must add nothing.
- **CR-4:** a settle failure must not silently strand the hold past run end — retry or
  escalate into the record so the hold cannot remain ACTIVE unobserved.
- **CR-5:** the settle reason is persisted and shown in the `prompt_hold_settled` step.
- **CR-6:** `PGSERVICE in os.environ` (any value, including empty) refuses.
- **CR-7:** handler restoration happens on all paths, including a record-write exception.
- **CR-8:** the runbook documents `--observed-at` exactly as argparse spells it.

Standing rules from brief-t045-fix4/fix5 apply unchanged: tests-first red→green per finding,
no assertion weakening beyond the ruling, no deletion verbs in the brief, commit never push.
