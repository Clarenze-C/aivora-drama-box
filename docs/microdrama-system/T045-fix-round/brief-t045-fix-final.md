# Finish build T045-FIX: Drama Box billing finality, last fix items, gates and report (money path)

Two earlier sessions of this build stopped on z.ai usage limits (HTTP 429). Their work is committed and the tree
is clean. You finish the build.

**The binding brief is `/root/AIVORA/drama-box/docs/microdrama-system/T045-fix-round/brief-t045-fix.md`.**
Read it in full first. Every ruling, gate, commit rule, hard limit and report requirement in it applies unchanged.

## State

- **Base:** `7f857eb`. **Branch:** `feat/microdrama-m0-m4` in `/root/AIVORA/drama-box`. **HEAD at hand-off:**
  `9720a90`; check `git log --oneline 7f857eb..HEAD` and `git status`.
- **Done and committed (16 commits):**
  - A-B1, A-S1–A-S8, A-N1–A-N4 and A-N6–A-N9;
  - B-B1, B-B2;
  - B-S2–B-S9;
  - B-N1, B-N2, B-N3, B-N5, B-N6.

  Don't redo them. A-N5 and B-N4 were accepted as is.
- **Left for you:**
  1. **B-S1:**
     - a FILE-only credential resolver through `CredentialStore`: ENV/VAULT/NONE refused, and the file mode must
       be 0600 or 0400;
     - the real `time.sleep` default with a poll floor of ≥ 2 s;
     - a `canary sweep --authorization <file> --authorization-sha256 <hex>` subcommand;
     - SIGTERM/SIGINT run the shutdown path.

     Each has the tests the brief lists.
  2. **B-S10:**
     - the full composed flow through `main(argv)`, with a test-only injection seam;
     - account total and charge sum asserted against the invoice, plus the finalization rows;
     - preflight with zero transport calls and zero resolver calls;
     - a retry test (a failed attempt, then success, with the hold reused and the failed attempt charged);
     - a `NeedsReconciliation` during submit: stop, no blind retry, shutdown runs.
  3. **B-N7:** `max_attempts` is a global cap across all prompts. Make the code, the authorization field
     description and the docs say exactly that.
  4. **Re-review findings:** see the section below. Fix them before the gates.
  5. **Docs**, per the brief:
     - the runbook's canary command lines, authorization schema and example file match the final CLI: no
       `--comfy-endpoint`, the `sweep` subcommand, the full image ref, `episode_id`, the FILE-only credential
       rule and the durable canary-DB path;
     - the evidence section "T045-FIX (2 Nov)" in `microdrama/evidence/T045.md` covers **every** ruling ID,
       including those committed by the earlier sessions. Take their red/green lines from their commits and
       tests. Where a red line was never recorded, rerun that test against the parent commit's code to get one,
       or say plainly that it is missing.
  6. **Gates:** after all fixes, run the full `make check` and `make pilot` under CPUQuota=45%. Also run ruff
     and `git diff --check`. Rerun all T045-A, T045-B and T045-FIX tests. List every test changed across
     `7f857eb..HEAD` whose assertions were loosened or removed, with the reason.
  7. **Report** to this run's `--out` file, covering the whole fix round (all three sessions):
     - per ruling ID: commit, test names, red/green lines;
     - what changed in 0025;
     - SPEC-GAPs;
     - the final command lines exactly as the runbook states them;
     - the gate tails and counts;
     - commit hashes;
     - anything not done.

## Re-review findings to fix

A Sonnet re-review of `7f857eb..9720a90` found 29 of 32 IDs FIXED, no regressions and no weakened assertions.
The full text is at `/root/AIVORA/drama-box/docs/microdrama-system/T045-fix-round/rereview-t045fix.md`.
Read each item's section there. Opus ruled; every item below is **binding**. Each needs a red test, then a green
test.

| ID | Defect | Fix + test |
|----|--------|------------|
| RR-S1 (B-S9 partial) | `refuse_non_loopback_dsn` (`pipeline/canary.py` ~259) checks only `postgresql://` URLs. It accepts `postgres://u@prod.example.com/db`, `host=prod.example.com dbname=x`, and `postgresql://127.0.0.1/db?host=prod.example.com`. | Parse every DSN form with `psycopg.conninfo.conninfo_to_dict`; an unparseable DSN is refused. Every `host` entry (comma-separated multi-host included) and every `hostaddr` must be loopback (`127.0.0.1`, `::1`, `localhost`) or an absolute unix-socket directory. Refuse any `service` key. If the DSN names no host or hostaddr, `PGHOST`, `PGHOSTADDR` and `PGSERVICE` must be unset or pass the same rule. Read them by name only; error messages may name the variable and the host, never a password. Tests: the three DSNs above, `postgres://`, a multi-host list with one remote, `service=x`, `PGHOST` set to a remote with a hostless DSN, and the accepted loopback and socket forms. All are refused before any transport call. |
| RR-S2 (B-S8 partial) | The default canary data root `/root/.local/share/microdrama/canary-pg` can't be traversed by the postgres OS user, so `initdb` fails when `canary_db up` runs as root. The tests mock `EphemeralPostgres`, so this never surfaced. | Default data root: `/var/lib/microdrama/canary-pg`. The parent is 0755 root. The data dir is 0700, owned by the OS user the server runs as. Keep the `--data-root` override and apply the same ownership logic to it. Add a **real** (not mocked) integration test that starts the durable cluster under a test-owned root with the same ownership code, then checks `SHOW fsync`, `synchronous_commit` and `full_page_writes` all return `on`. It is a local loopback PG, so the test is allowed. It must not touch ports 8091/8093 or any container. |
| RR-S3 | `canary_db up` after `down` reruns `_seed` on the kept data. The seed's `UPDATE episodes SET id=<fixed canary UUID>` hits a unique violation after the server has started, which leaves a running cluster with no state file. | Make the seed idempotent: on kept data, verify the seeded rows (fixed episode id, rights, preset, account) and skip what exists. Any failure after the server starts stops the server and reports the error; it never leaves a running cluster without a state file. Tests: `up` → `down` → `up` leaves exactly one episode and a valid state file; an injected seed failure leaves no running server. |
| RR-S4 | **Lost charge.** After `resolve_podless_create` the reservation is SETTLED and readiness returns BILLED 0 before any `pod_id` check. The janitor ingests only ACTIVE/EXPIRED reservations. A Pod that later appears for that lease is stopped as an orphan but never attached, never ingested and never charged. | Every owned Pod has a lease row and a client token from before its create was sent. So in `_sweep_provider_orphans` (and wherever an owned Pod is found that no live lease holds), look up the terminal lease with the same client token and `pod_id IS NULL`. If one exists: <br>• attach the Pod to that lease, with an adoption event; <br>• for Runpod, stop, terminate and verify, writing `terminate_verified_at`; <br>• if a podless resolution exists, mark it **contradicted** durably (0025 column on the resolution table); <br>• readiness for the lease is then computed from the Pod's billing (REOPENED / PENDING_PROVIDER_FINALITY until invoice-verified), never BILLED 0 from the resolution; <br>• billing ingestion includes such leases although their reservation is SETTLED, and the cost posts as an **ADJUSTMENT** on the SETTLED reservation, which the ledger allows. <br>This also covers a closed-without-pod lease with a sent create and no resolution. Tests: <br>• resolve podless → owned Pod appears → janitor attaches, stops, terminates and ingests → after invoice match, the account total equals the invoice and the adjustment equals the GPU bucket; <br>• the resolution is marked contradicted; <br>• a second sweep adds nothing. |
| RR-N1 | `resolve_podless_create` commits the resolution row before checking for a budget service, and the window-end UPDATE skips `update_with_revision`. | Check the budget service first, then write the resolution and the SETTLEMENT in one transaction. Do the window-end write through `update_with_revision`. Test: a budget-less repository refuses and leaves no resolution row. |
| RR-N2 | `canary_db down` refuses any data root other than the default. | Record the data root in the state file at `up`. `down` validates that the state file's data dir is under the recorded root, and accepts `--data-root` equal to it. Test: `up --data-root X` → `down --data-root X` works; a tampered state file pointing elsewhere is refused. |
| RR-N3 | The B-S4 end-to-end test never asserts that the early sweep wrote a skip row. | Assert that the skip row exists after the early sweep, and that the invoice still matches afterwards. |
| RR-N4 | The evidence section "T045-FIX" stops at B-B2, and its A-N6, A-B1/N3/N4 and A-S1/S4 rows say NOT RECORDED. | Complete it for every ID, as item 5 above says. Rerun each missing red test on the parent commit's code to get its red line. |
| RR-N5 | The Comfy endpoint is bound once, right after `ensure_pod`, with no wait for the Pod's runtime port. A real Pod that is RUNNING but has no ports yet would end the run NOT CLEAN. | After `ensure_pod`, poll a read-back of the Pod for `endpoint_url` (poll floor ≥ 2 s, bounded by the run deadline), then apply the B-B2 equality check. If the deadline runs out, stop and terminate, and write the record as NOT CLEAN. Test: a fixture Pod reports no ports for two reads, then reports them, and the run proceeds; a Pod that never reports ports stops at the deadline with zero Comfy calls. |
| B-N1 (partial) | Float time math remains in the janitor's hourly rounding (`rendering/janitor.py` ~673-676, `timestamp() % 3600`) and in `budget/billing.py` ~928 (`total_seconds()`). | Use integer microseconds or `Decimal`. Add a property test over boundary instants (exact hour, hour − 1 µs, sub-second): the results match the integer reference. |

**Order:** RR-S4 first (money), then RR-S1, B-S1, RR-N5, B-S10, then the canary-db items (RR-S2/S3/N2), RR-N1,
RR-N3, B-N1 and B-N7, then docs, evidence and gates.

**If you hit a usage limit again:** stop cleanly. Commit only work whose tests pass, and write what is done and
what is left to the `--out` file.
