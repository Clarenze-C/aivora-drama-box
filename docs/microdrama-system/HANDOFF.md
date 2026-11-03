# Drama Box microdrama handoff — updated 3 November 2026 UTC

Read `/root/.claude/CLAUDE.md`, this file, [SPEC.md](SPEC.md),
[task_breakdown.md](task_breakdown.md) and [task_status.csv](task_status.csv)
before work. This handoff records the current checkout; chat history is not a
deployment receipt.

## Who orchestrates (from 3 November 2026)

**GLM-5.3 is the orchestrator from this week on.** The Opus weekly limit is
nearly spent: 63% used with 5.3 days left on 3 Nov, under the 8%/day pace
rule. Start sessions with `cms glm`. A GLM session never calls Opus, so these
rules apply:

- GLM writes the specs and briefs and rules on review findings, which Opus did
  until 3 Nov.
- Builds go through `ai-route build`. Only one GLM build runs at a time, and
  the orchestrator stays thin. The orchestrator and its builds share one z.ai
  5h window with every other session's builds; on 3 Nov, two T045 sessions were
  cut short by other sessions' builds. Before every launch, check
  `ai-route --status --all` and `ai-route --quota`.
- The Sonnet stand-in reviewer was only reachable from an Opus session, so it
  is gone. Codex returns when its week resets on **2026-11-04 06:57Z**.
  Reviews go through `ai-route review`; Codex never reviews code it wrote, and
  GLM wrote all of T045.
- Headless briefs must not contain deletion verbs (`rm`, `git rm`,
  `git clean`, `git reset`, `find -delete`). A hook holds them for 10 minutes,
  then refuses. Long reports go to a separate report file, because ai-route
  overwrites `--out` with the job's final message.

## Checkout and safety

- Repo: `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`. Remote head
  `f7f135b`: everything through the 2026-11-02 DB review cycle is pushed.
- **The 41 T045 commits on top (`65fae0b..b05b66a`) are NOT pushed.** Pushing
  needs the operator's approval.
- **The working tree holds uncommitted GLM work: the F-1 fix** in
  `microdrama/src/microdrama/rendering/janitor.py` and
  `microdrama/tests/unit/rendering/test_t045_billing_ingestion.py`. Don't
  discard it; session 5 commits it. Also untracked: a stray test render at
  `microdrama/canary-objects/` (O-1 removes it).
- A pre-review snapshot of the formerly dirty tree exists at
  `/root/drama-box-dirty-snapshot-20261101.tar.gz`.
- Current contract package: **2.15.0** (V2 payload schema version 2.0; V1
  payloads remain readable). Migrations 0019–0025 are present. 0025 (T045) is
  unpushed and is edited in place during the fix round; no persistent database
  has it. Contract source and generated artifacts are guardian-owned.
- No real Runpod Pod, paid model request, platform post, account test or
  public action has been performed. OFFLINE_MOCK remains the only composed
  mode; the staging deployment refuses all others. T031–T035 are not
  qualified by local tests.
- No build worker is running (checked 3 Nov 09:55Z; the queued session-5
  launcher was stopped so the new orchestrator owns the launch).
- `/tmp/claude-0` and `/tmp/claude-0/-root-AIVORA` must stay 0700. Until O-2
  lands, the T045 durable-root tests set every ancestor of their temp dir to
  0755. That happened on 3 Nov and was reverted. pytest's own
  `/tmp/pytest-of-root` is now 0755; set it back to 0700 once O-2 is
  committed.

## Board state

**M5V2 offline software is COMPLETE.** T001–T030 accepted; T036–T044, T046,
T047 and T048 `DONE` (evidence under `microdrama/evidence/`, receipts in the
ledger). T045 is the one open offline task (`REVIEW`, in its fix round;
see below). T031–T035 are the live qualification gates and have not started.

The **last full green** receipt was at T045-B (`7f857eb`, 2026-11-02, under
CPUQuota45%): `make check` reported **all offline checks passed**, with
**2,705 unit, 462 contract and 232 integration** tests; Ruff clean;
`make pilot` exit 0 (W01–W12, exactly two human gates, 16 local exports,
303,000 **synthetic** micro-USD). No full gate has run since the fix round
started. The round-2 reviewer's focused run at `7faef9e` was 719 passed and
2 deselected; the two deselected tests passed alone.

**Independent reviews:** the pending Codex spot-checks for T044b2 (findings 1
and 3), T046 and T047 were replaced on 2026-11-02 by a stand-in cross-model
review (Claude Sonnet 5.5 read-only reviewer, Opus rulings —
[review](T044b2-T046-T047-claude-review-2026-11-02.md)). All 11 findings
(DB-1..DB-11) were accepted as BINDING and fixed the same day, tests-first
red→green, in commits `15b6cf5`, `03f3e92`, `64b1784`, `73747df`
(+`01379d7` format); evidence is appended to the T044b2/T046/T047 evidence
files and the ledger rows point there. **Re-review 1** (same file, section at
the end) then ACCEPTED that fix round: DB-1, DB-2, DB-4..DB-10 and the
T044b2 F2/F4/F5/F6 spot-check are CLOSED. Its three follow-ups — DBR-1
(create-owner reserved its password file after the owner row committed),
DBR-2 (the reader's overlap check rejected every contract-valid crossfade
EDL), DBR-3 (unbounded `advisory_lock` wait) — are fixed tests-first
red→green in commit `95fef89`, and the required DBR-6 drill re-run after
DB-10 passed 7/7 (loopback compose on 8093, stack left DOWN). **Re-review 2
(final, scoped DBR-1..3 + DBR-6) ACCEPTED** on 2026-11-02: all four items
CLOSED, 4 NITs left as is (same review file, last section). That review
cycle is closed and pushed.

## What 1 November built (all gated, committed, pushed)

- **T044 owner workbench — DONE.** T044a season-owner scope (migration 0024)
  + progress projection; T044b1 Gate 2 owner-metadata form/API invoking
  `ReviewService.prepare_release_approval_manifest`; T044b2 the three-step
  Script Maker intake + workbench. Codex's scoped review found 5 BLOCKING
  issues (selection replay, cross-owner sheet leakage, silent source-lane
  skip, unverified display payloads, unverified scope-as-canon); all fixed
  with pinning tests ([T044b2 evidence](../../microdrama/evidence/T044b2.md),
  [review](T044b2-codex-review.md), [re-review](T044b2-review-fixes.md)).
- **T047 composed acceptance — DONE; T037 CLOSED.** The deferred production
  seams exist with fail-closed semantics and pinned tests
  ([T047 evidence](../../microdrama/evidence/T047.md)):
  `references/v2_dispatch_context.py` (`verify_current_asset` = ACCEPTED row
  + exact version/sha + stored-bytes hash; authoritative registry rights
  resolver; the record loader feeding `V2ReferencePreflightContext`) and
  `qa/continuity_sources.py` (typed expectations reader from current edit
  manifests + hash-verified V2 records). Six composed proofs, including the
  intake-born season reaching the Gate 2 manifest → scheduled posts with no
  transport (T037's closure evidence). The pilot composition is deliberately
  unchanged; live V2 dispatch consumes the gates when T045 lands.
- **T046 private staging — DONE.** `api/serve.py` + `api/worker.py` durable
  entries (SystemClock + UuidIds; refuse non-OFFLINE_MOCK modes), digest-
  pinned Dockerfile + `deployment/compose.staging.yaml` (loopback-only,
  127.0.0.1:8093 — 8091 belongs to arisa-sfw-review). The seven-step drill is
  7/7 PASS ([T046 evidence](../../microdrama/evidence/T046.md)): owner
  login, three-step intake over HTTP, FULL restart including postgres with a
  surviving session and identical rows, worker+janitor drain, backup, and a
  scratch-project restore with login + season readback. The drill caught and
  fixed two real defects: registry seeding was not restart-idempotent
  (pinned by `tests/unit/api/test_serve_entries.py`), and deterministic
  `SequentialIds` made `create-owner` work exactly once per database.
  The staging stack is DOWN (volumes kept); bring it back with the compose
  command in the drill header. `dramabox.aivora.agency` DNS/TLS/exposure is
  operator-only runbook work (`deployment/staging/DOMAIN-RUNBOOK.md`) —
  deliberately not executed.

## T045 — the one open offline task (billing finality, live wiring, canary runner)

**Status: REVIEW, in the fix round.** All three original open items are
built, and the remaining work is review fixes. Everything is offline;
fixture transports only, and no provider has been called.

**What exists.** Spec: [T045-finality-spec.md](T045-finality-spec.md) rev 1,
on top of [T045-billing-integration-spec.md](T045-billing-integration-spec.md).
Evidence: [microdrama/evidence/T045.md](../../microdrama/evidence/T045.md).

- **T045-A (R0–R8, `65fae0b..1a60fc5`): lease billing finality.**
  - Migration 0025.
  - Allocation by lease-window existence, and per-lease reservation links.
  - Storage ownership from activation to verified terminate.
  - Bucket state derived at ingest.
  - Pod-scoped period invoice evidence with idempotent replay
    (`verify_invoice_period`).
  - Five readiness states (PENDING_PROVIDER_FINALITY / AWAITING_INVOICE /
    DISPUTED / RECOVERY_REQUIRED / BILLED; REOPENED derived), the BILLED
    settlement and hold release, and a required finality port.
- **T045-B (R9–R11, `4886331..7f857eb`): the wiring.**
  - `live_world` is wired to the durable `BillingRepository`, with no boolean
    override.
  - Janitor billing ingestion maps to exact micro-USD.
  - Quote attestation.
  - The canary runner: `python -m microdrama.pipeline.canary
    {preflight,execute,sweep,invoice}`, plus `tools/canary_db.py` /
    `make canary-db`.
- **The fix round (`488ba9e..b05b66a`, 24 commits).**
  - Every A and B review ruling is fixed.
  - Two re-review rounds have run; round 2 found 9 FIXED, 1 PARTIAL and no
    BLOCKING.
  - The full record (reviews, rulings, briefs, probes) is in
    [T045-fix-round/](T045-fix-round/README.md).

**What is left** (all ruled and binding; order and tests are in
[brief-t045-fix4.md](T045-fix-round/brief-t045-fix4.md)):

| ID | What |
|----|------|
| F-1 (money) | Retry the stop → terminate → verify tail for a terminal lease's Pod whose terminate failed. **Written, uncommitted.** |
| F-4 (money) | A failed prompt with no retry must not leave its hold ACTIVE: settle it at 0. |
| O-1 | Refuse the run without an absolute `MICRODRAMA_OBJECT_STORE_ROOT`; untrack the test render committed in `dbb29f7`; add `canary-objects/` to `.gitignore`. |
| F-5 | The DSN guard also checks `PGHOSTADDR`, and refuses any set `PGSERVICE`. |
| F-2 | Repeat SIGTERM/SIGINT during shutdown are ignored; handlers are restored only after the record is written. |
| F-3 | `canary sweep` uses the real shared cleanup guard, never a no-op. |
| O-2 | `canary_db` never chmods an existing directory; it refuses a non-traversable ancestor instead. |
| B-S1 rest | The key file resolver refuses symlinks and files with a foreign owner. |
| F-6 | Test marks only (`pytest.mark.db` scope). |
| Docs and evidence | Runbook canary section matches the final CLI; evidence covers every ID with red/green lines. |
| Gates | `make check`, `make pilot`, ruff, `git diff --check`, all under CPUQuota=45%. |

## T045 close-out — steps for the GLM orchestrator

1. **Launch session 5** once the z.ai 5h window has room and no other GLM
   build is running. Run it in the background and end the turn; never poll.

   ```bash
   cd /root/AIVORA/drama-box
   ai-route --status --all; ai-route --quota
   env -u SUPABASE_ACCESS_TOKEN ai-route build docs/microdrama-system/T045-fix-round/brief-t045-fix5.md \
     --cwd /root/AIVORA/drama-box --effort xhigh --tag dramabox-t045fix5 \
     --out <your-scratchpad>/out-t045fix5.md
   ```

   If it hits a 429 again, write `brief-t045-fix6.md` the same way: the state
   from `git log` and `git diff`, then the remaining order. Point it at
   brief-t045-fix4 as binding.
2. **Check each finished session.**
   - New commits exist; the tree is clean apart from the report; nothing is
     pushed.
   - Secrets scan of the session transcript. Find the session id in
     `~/.cache/ai-route/runs.jsonl`; the transcript is
     `~/.claude/projects/-root-AIVORA-drama-box/<id>.jsonl`. Look for reads
     of `~/.claude/.env` or `/root/.secrets`, `printenv`/`env` dumps,
     `/proc/*/environ`, and token-shaped strings. Hits that are only the
     brief's own text are fine.
   - `/tmp/claude-0` is still 0700.
   - `git status --porcelain` lists nothing under `microdrama/canary-objects`.
3. **Verification needs an operator decision.** Both re-review rounds are
   used up (2-round cap). F-1–F-6, O-1, O-2 and the rest of B-S1 were fixed
   after round 2. **Recommendation:** one scoped Codex review after
   2026-11-04 06:57Z, `ai-route review --effort xhigh` over
   `7faef9e..HEAD`. Give it the rulings in brief-t045-fix4.md and the
   round-2 report. GLM rules on its findings. Ask the operator before
   starting it.
4. **Accept.**
   - Confirm the gate tails yourself: `make check` must end with
     `make check: all offline checks passed`, and `make pilot` must show
     W01–W12, two gates, 16 exports and 303,000 micro-USD unchanged.
   - Commit `T045-FIX-REPORT.md` with the evidence.
   - Set the `task_status.csv` T045 row to DONE with the receipt. Use the
     ledger tool from `microdrama/`:

     ```bash
     .venv/bin/python tools/ledger.py T045 status=DONE completed_at=now evidence="..."
     ```
   - Update this file.
   - Commit, and never push without the operator's approval.
5. **Update the T031 packet.**
   [T031-authorization-packet.md](T031-authorization-packet.md) §5 still has
   placeholder command lines; its `--evidence-file` and
   `--source runpod-console` are wrong. Copy the final lines from the runbook
   and session 5's report:
   - `preflight` / `execute` / `sweep` / `invoice`;
   - `--authorization` + `--authorization-sha256`;
   - `--source INVOICE|CONSOLE`;
   - `MICRODRAMA_DATABASE_URL` (loopback only) and
     `MICRODRAMA_OBJECT_STORE_ROOT`;
   - the FILE-only key (mode 0600/0400);
   - `canary_db` at `/var/lib/microdrama/canary-pg`;
   - in the authorization: `episode_id`, the full
     `<registry>/<repo>@sha256:<64hex>` image ref, and `max_attempts` as one
     global cap.

   Also update §1's preconditions. **Do not run T031.**

T047's asset/rights gates are the dispatch-boundary suppliers that T045's
live path consumes. The official Runpod billing endpoint returns time
buckets, not per-second lease receipts; never relabel estimates as billed
cost.

## What remains, in order

1. ~~Review-after-fix~~ **DONE 2026-11-02**: re-review 2 ACCEPTED DBR-1..3 +
   DBR-6 (`ef08674`); the operator approved the push and the branch is pushed.
   An optional Codex spot-check after the 2026-11-04 reset remains.
2. **T045 acceptance:** the close-out steps above, offline only, with no
   provider calls. Two operator decisions:
   - how to verify the post-round-2 fixes (Codex recommended);
   - pushing the 41+ unpushed T045 commits.
3. **T031 real-provider qualification.** It needs T045 accepted PLUS explicit
   operator authorization: rights route, credentials, current quote, and
   time/storage/spend caps.
   - **The RunPod key must be rotated first**, and the operator sets the spend
     cap.
   - The authorization packet ([T031-authorization-packet.md](T031-authorization-packet.md))
     is a draft until step 5 above updates it.
   - Do not launch a canary without it.
4. T032 controlled real account tests, T033 first actual episode, T034 ten
   episodes + seven-day management windows, T035 final handoff — separate
   live gates, unchanged.
5. Optional, operator-decided: the domain runbook for
   `dramabox.aivora.agency`.

Do not treat a local mock, schema, adapter fixture, staging drill or manual
Pod sample as real provider, publishing, domain or ten-episode qualification.
