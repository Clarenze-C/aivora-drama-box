# Drama Box microdrama handoff — updated 4 November 2026 UTC

Read `/root/.claude/CLAUDE.md`, this file, [SPEC.md](SPEC.md),
[task_breakdown.md](task_breakdown.md) and [task_status.csv](task_status.csv)
before work. This handoff records the current checkout; chat history is not a
deployment receipt.

## Who orchestrates (from 3 November 2026)

**GLM-5.3 is the orchestrator.** The Opus weekly limit stays under the 8%/day
pace rule, so a GLM session owns this workstream: GLM writes the specs, briefs
and rulings on review findings; builds go through `ai-route build`. These rules
apply:

- One GLM build at a time; the orchestrator and its builds share one z.ai 5h
  window with every other session's builds. Before every launch, check
  `ai-route --status --all` and `ai-route --quota`. Exit 75 = retry at the
  reset time, never swap models.
- Reviews go through `ai-route review` (Codex). Codex never reviews code it
  wrote; GLM wrote all of T045. A review cycle is capped at two rounds
  (review + re-review); a third round needs the operator's explicit approval
  (the T045 close-out used all three, 4 Nov).
- Headless briefs must not contain deletion verbs (`rm`, `git rm`,
  `git clean`, `git reset`, `find -delete`). A hook holds them for 10 minutes,
  then refuses. Long reports go to a separate report file, because ai-route
  overwrites `--out` with the job's final message — and a Codex reviewer's
  sandbox refuses file writes, so tell it to put the full report in its final
  message.
- The Codex reviewer cannot run `systemd-run` (`Operation not permitted` in its
  sandbox): it reviews from code, AST diffs and in-memory probes. The
  orchestrator re-verifies BLOCKING claims in code and runs the gates itself.

## Checkout and safety

- Repo: `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`, **pushed level
  with the remote** (operator-approved 2026-11-04; local and remote both at
  `d8604ea`).
- The working tree is clean. Contract package **2.15.0** (V2 payload schema
  version 2.0; V1 payloads remain readable). Migrations 0019–0025 are present;
  0025 (T045) was edited in place during the fix round — no persistent database
  has it. Contract source and generated artifacts are guardian-owned.
- No real Runpod Pod, paid model request, platform post, account test or
  public action has been performed. OFFLINE_MOCK remains the only composed
  mode; the staging deployment refuses all others. T031–T035 are not
  qualified by local tests.
- `/tmp/claude-0`, `/tmp/claude-0/-root-AIVORA` and `/tmp/pytest-of-root` are
  all 0700; nothing currently widens them (O-2 + CR-1 landed).

## Board state

**All offline software is COMPLETE.** T001–T030 accepted; T036–T048 DONE
(evidence under `microdrama/evidence/`, receipts in the ledger). **T045 moved
to DONE on 2026-11-04** after its fix round closed. T031–T035 are the live
qualification gates and have not started.

The **last full green** receipt is the orchestrator's own run at final T045
HEAD `1ce71cb` (4 Nov, under CPUQuota=45%): `make check` — **all offline
checks passed**, unit **2,770** / contract **462** / integration **268**; ruff
clean; `git diff --check` clean; `make pilot` exit 0 — W01–W12, exactly two
HUMAN gates, 16 exports, 303,000 **synthetic** micro-USD.

## T045 close-out record (2026-11-04)

The full record (reviews, rulings, briefs, reports) is
[T045-fix-round/](T045-fix-round/README.md). In short:

- Sessions 1–7 (`488ba9e..1ce71cb`, 45 commits) fixed every A/B review ruling
  and every later finding, tests-first red→green, evidence per ID in
  `microdrama/evidence/T045.md`.
- The post-round-2 fixes were verified by an operator-approved **three-round
  Codex cycle** on 4 Nov: round 1 found CR-1..CR-8 (4 BLOCKING; fixed in
  session 6), round 2 found a CR-3 residual + CR-9 (both BLOCKING; fixed in
  session 7), round 3 (operator-approved past the two-round cap) **ACCEPTED**
  with zero new findings and all pre-existing tests AST-identical
  ([rereview-t045fix7.md](T045-fix-round/rereview-t045fix7.md)).
- The orchestrator re-verified every BLOCKING claim in code before ruling,
  confirmed both session reports' check-out (commits, clean tree, secrets
  scans of the transcripts, tmp perms, no canary-objects), and re-ran the full
  gates itself at each session HEAD.
- The canary runbook is at the final CLI
  ([T045-live-provider-runbook.md](T045-live-provider-runbook.md)); the T031
  packet §1/§5 now carries the exact command lines.

## Open operator decisions

1. ~~Push the T045 commits~~ **DONE 2026-11-04**: the operator approved and the
   branch is pushed (`f7f135b..d8604ea` → aivora-drama-box
   `feat/microdrama-m0-m4`). Remote and local are level.
2. **T031 authorization, when ready.** The canary packet
   ([T031-authorization-packet.md](T031-authorization-packet.md)) is final in
   shape: preconditions in §1 (key rotation first, rights route, pins, quote,
   spend cap), the exact runner commands in §5. It is NOT a draft anymore, but
   it is also not executable until the operator fills §8's sign-off. **Do not
   run T031.** The RunPod key must be rotated first (the old one was printed
   into a GLM session on 2026-11-02), and the operator sets the spend cap.

## What remains, in order

1. **T045 acceptance: DONE 2026-11-04** (see the close-out record above). The
   branch push is the open piece of it.
2. **T031 real-provider qualification.** Needs explicit operator
   authorization: rights route, credentials (rotated), current quote, and
   time/storage/spend caps. Do not launch a canary without the signed packet.
   T047's asset/rights gates are the dispatch-boundary suppliers that T045's
   live path consumes. The official Runpod billing endpoint returns time
   buckets, not per-second lease receipts; never relabel estimates as billed
   cost.
3. T032 controlled real account tests, T033 first actual episode, T034 ten
   episodes + seven-day management windows, T035 final handoff — separate
   live gates, unchanged.
4. Optional, operator-decided: the domain runbook for
   `dramabox.aivora.agency` (`deployment/staging/DOMAIN-RUNBOOK.md`).

Do not treat a local mock, schema, adapter fixture, staging drill or manual
Pod sample as real provider, publishing, domain or ten-episode qualification.
