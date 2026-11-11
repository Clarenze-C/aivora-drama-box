# Drama Box microdrama handoff — updated 11 November 2026 UTC

## CURRENT — read this first (11 Nov 2026, Opus orchestrator session 21694f19; refreshed before 19:00Z)

Everything below this section is history. This section is the live state.

### T031 / H-2 (benchmark recovery): build DONE, verification running

- **Build:** [h2-build-REPORT.md](T031-fix-round/h2-build-REPORT.md) is marked `H2-BUILD: ALL PACKAGES
  DONE`. Branch `feat/t031-fix3`, tip **`0e34630`** (P5), in worktree `.scratch/t031-fix3-worktree`.
- **Full offline gate:**
  - **First run at `0e34630`: FAILED at lint.** `ruff format --check` flagged 2 files.
  - Orchestrator fix: **`4e28514`**, formatting only; the new branch tip.
  - **Rerun at `4e28514`: GREEN**: 3,038 unit / 462 contract / 275 integration, `make pilot` OK
    ([receipt](T031-fix-round/gate-4e28514.md)). This is the pre-HCF baseline, not acceptance.
  - `.scratch/t031-gate-h2` (at `0e34630`) is the checkout Codex reviews.
- **Codex review** of `45e4f2a...0e34630`: [result](T031-fix-round/codex-review-h2-p4p5.md) =
  **FIX-REQUIRED**.
  - HC-1..HC-10 BLOCKING, HC-11/12 SHOULD-FIX.
  - HB-1..4 and HB-14 CLOSED; HB-5..13 PARTIAL.
  - The orchestrator verified HC-4, HC-7 and the out-of-spec canonical edits (HC-2).
- **The operator approved a fix round plus one final Codex review** (a 3rd round for the HB items).
- **Fix round HCF** ([brief](T031-fix-round/h2-hcf-brief.md), report `T031-fix-round/h2-hcf-REPORT.md`):
  - **F1 `6db5fe8`** (out-of-spec canonical billing edits reverted) and **F2 `9b736da`** are committed.
  - **It stopped at the z.ai 5 h limit (429) during F3.** Its F3 code edits are in stash
    `1f9bc18eb17e…` ("t031-hcf-f3-wip"), **pinned on branch `wip/t031-hcf-f3-stash`**. The F3 test file
    is untracked in the worktree.
  - **Resume:** systemd timer **`t031-hcf-resume-loop` at 16:30Z**. It runs
    `scratchpad/keep/t031-hcf-resume-loop.sh` (session 21694f19) with
    [h2-hcf-resume-brief.md](T031-fix-round/h2-hcf-resume-brief.md) (apply the stash by SHA, then
    F3 → F5), tag `dramabox:t031-h2-hcf-r2`.
  - The loop stops at the marker `H2-HCF: ALL FIXES DONE`, after 3 runs, or after a run with no commit
    progress.
  - Check it with `systemctl status t031-hcf-resume-loop` and `journalctl -u t031-hcf-resume-loop`.
  - **After F3 the stash entry should be dropped by SHA. Delete the branch `wip/t031-hcf-f3-stash`
    after HCF is accepted.**
  - Then: the full gate, then the final Codex review. **If that review still finds BLOCKING issues, the
    orchestrator recommends parking T031** and building V3's generic recovery (phase A3) instead.
- **After both pass:**
  - fast-forward `feat/t031-pika-flex-native` to the accepted tip (local only, never pushed);
  - A0-D then branches from that tip.
  - **The paid T031 run still needs the operator:** the $8 sign-off, the image, the weights, reference
    assets, and Botnoi voices for 2 test characters.

### v3 series workflow: specs DONE, builds started

| Doc | State |
|-----|-------|
| [SPEC-v3.md](v3-workflow/SPEC-v3.md) master | **v0.4.4 BINDING** (Codex ×2 + Goldfish applied; v0.4.2 LLM-call wording, v0.4.3 Botnoi catalogue, v0.4.4 jobs-schema ownership) |
| [phase-A0-spec.md](v3-workflow/phase-A0-spec.md) (LLM gateway) | **v0.4 READY FOR BUILD**: Codex ×3; the 3rd round was operator-approved and scoped. The build review must verify A0S-1/2 |
| [phase-A-spec.md](v3-workflow/phase-A-spec.md) (Foundations) | **v0.3**: Codex ×2. The operator chose no 3rd round; the A1, A2, A3 and A6b design notes are Codex-critiqued **before code** |

**Build order:**
1. **A0-R1**, the ai-route `dramabox-llm` role: **BUILD DONE.**
   - Worktree `/root/.claude/.claude/worktrees/a0r1-airoute`, branch `worktree-a0r1-airoute`.
   - 5 commits: `9776fb3`, `a6cf997`, `b0ce72e`, `646e42e`, `02af779`.
   - [report](v3-workflow/a0r1-build-REPORT.md).
   - **Orchestrator verification:** 62 new tests passed; `test_guards` and `test_goldfish` ALL PASS.
     `test_observability.py` fails 3 checks **identically on `main` `02b361a`**: an existing,
     load-sensitive failure, not a regression.
   - Two policy entries are `UNCONFIRMED` (the remote-settings cache path, the built-in extension
     inventory), so the role **fails closed** until the §7 live qualification.
   - **Codex review round 1 = FIX-REQUIRED:** [RR-1..15](v3-workflow/codex-review-a0r1.md).
     - 6 BLOCKING: dedupe overwrites and races, nonzero exits bypassing the isolation check, error
       results classed `SUCCEEDED`, unbounded waits, executable credential helpers allowed in policy.
     - 9 SHOULD-FIX.
   - **Fix round 1** ([brief](v3-workflow/a0r1-fix1-brief.md), every RR accepted, with rulings):
     - scheduled as systemd timer **`a0r1-fix1-after-hcf` (16:31Z)**;
     - it waits until the HCF resume loop is no longer active (one Drama Box GLM build at a time), then
       runs once (tag `dramabox:a0r1-fix1`);
     - script `scratchpad/keep/a0r1-fix1-after-hcf.sh` (session 21694f19);
     - marker `A0-R1 FIX1: ALL DONE` in the report.
     - **Then a Codex re-review (round 2 of 2).**
   - After ACCEPT: merge into `/root/.claude` `main`, staging only `scripts/ai_route.py`, `models.json`
     and `scripts/tests/ai_route/`. Never `git add -A` there (auto-logger churn).
2. **A0-D**, the drama-box half (gateway, `LlmStep`, migration 0027):
   - **The brief is written:** [a0d-build-brief.md](v3-workflow/a0d-build-brief.md), packages D1–D3.
   - **Settle its base before launch:** the accepted T031 tip (A0 = 0027), or `feat/microdrama-m0-m4` if
     T031 is parked (A0 = 0026).
   - Launch: `ai-route build <brief> -w a0d-gateway --effort xhigh`.
   - the operator installs the systemd unit, group 64010 and directories;
   - the live qualification (≤5 calls) needs the operator's OK.
3. **Phase A**, packages A1 → A2 → A3 → A4 → A5 → A6a → A6b → A6c.
   - **A1 note** ([A1-design-note.md](v3-workflow/A1-design-note.md)):
     - v1.1 was GLM's draft, with orchestrator rulings in §12.
     - The Codex critique is **REWORK**: [N1-1..18](v3-workflow/codex-a1-note-critique.md), 13 BLOCKING.
     - **GLM revision v1.2 is done** ([brief](v3-workflow/a1-note-r2-brief.md)); §13 maps every N1
       finding.
     - **Next: the Codex re-critique (round 2 of 2), deliberately held until the Codex week resets
       (13 Nov 10:30Z).** The Codex week was at 85% on 11 Nov; it is kept for the HCF final review and the
       A0-R1 review. Use the brief pattern of `a1-note-critique-brief.md`, scoped to N1-1..18 and the new
       defects.
     - Then the A1 build. **A1 can't build before A0-D**
       (migration 0027) exists.

### Operator to-dos

- **Botnoi catalogue:** add only the marketplace/Studio voices the public API lacks (elderly, monk, other
  archetypes) to `v3-workflow/botnoi-v4-voices.csv`.
  - The API voices are auto-imported (snapshot: `v3-workflow/botnoi-api-speakers-2026-11-11.csv`, 443
    voices, 162 Thai).
  - **Confirm the orchestrator's default:** community voices need per-voice approval (DECISIONS "D2
    update").
- Rotate the Dramabox Bot token before go-live.
- ~~DNS for dramabox.aivora.agency~~: **done** (Cloudflare, resolves to proxied A records). The app route
  (Coolify/Traefik) comes with phase A6c.
- ~~Commit the v3 docs~~: **done**, `5d79ae8` on `feat/microdrama-m0-m4` (local; not pushed).

### Routing rules in force

- Opus orchestrates and specs; GLM builds (`ai-route build`); Codex critiques and reviews (`ai-route
  critique|review`).
- At most 2 Codex jobs at once.
- **Two review rounds, then ask the operator.**
- No polling: background watchers only.

---

Read `/root/.claude/CLAUDE.md`, this file, [SPEC.md](SPEC.md),
[task_breakdown.md](task_breakdown.md) and [task_status.csv](task_status.csv)
before work. This handoff records the current checkout; chat history is not a
deployment receipt.

## Current gate result — verified 7 November 2026

Full `make check` has finished with exit2: unit2879passed, contract462passed;
integration258passed,8failed,4setup errors. `make pilot` was NOT_RUN.
Failures include hardcoded migration-tail expectations after adding0026 and actual
missing delete/truncate/non-integer safeguards on new benchmark tables. These are
open failures, not acceptance. Diagnose/fix them narrowly before rerunning affected
checks; do not rent a Pod or treat the image/124-test receipt as live readiness.

## Routing — 9 November 2026 (supersedes the 6 Nov override below)

Operator, 9 Nov: an Opus session orchestrates and routes through `ai-route`. GLM builds;
Codex reviews code it did not write; GLM reviews the Codex-written native harness. The
native harness's 81 files are now committed as WIP `048cc05` on
`feat/t031-pika-flex-native` (local only). [Fix round 1](T031-fix-round/fix1-REPORT.md)
DONE `c6e19e0`+`2ceb341` (the 12 integration failures; focused files green, full gate
not yet rerun). [Codex review of `13da3e2..0851374`](T031-fix-round/codex-review-canary-night.md)
= FIX-REQUIRED, 3 BLOCKING (billing rounding, duplicate pod create, unredacted
diagnostics) + 3 SHOULD-FIX; [rulings](T031-fix-round/rulings-canary-night.md).
[Fix round 2](T031-fix-round/fix2-REPORT.md) DONE `9197c52..d971435` (CN-1..CN-6,
focused suites green). Full `make check`+`make pilot` at `d971435` still running (unit `t031-fix2-offline-gates`, receipts in worktree `.scratch/gates-fix2/`). [Codex re-review round 2](T031-fix-round/codex-rereview-fix2.md) = FIX-REQUIRED (CN2-1/2 BLOCKING, CN2-3/4 SHOULD-FIX); [GLM harness review](T031-fix-round/glm-review-harness-REPORT.md) = FIX-REQUIRED (H-1 live-path bind crash, H-2 no UNKNOWN reconciler; 4 SHOULD-FIX, 3 NIT). Full gate at `d971435`: [2,924 unit / 462 contract / 274 of 275 integration](T031-fix-round/gate-d971435.md); the one failure is the repair-media-chain ffmpeg test timing out under host load (passes in 304 s alone), not a regression. Operator approved a bundled round 3 (10 Nov): [fix3](T031-fix-round/fix3-brief.md) in worktree `.scratch/t031-fix3-worktree` (branch `feat/t031-fix3` from `d971435`; fast-forward `feat/t031-pika-flex-native` to it after acceptance). GLM committed CN2-1..4, H-1, H-2 (`726a56e..628fe5b`); at z.ai 81% it was stopped and [Luna](T031-fix-round/fix3-luna-brief.md) took H-3..H-9. Review split: Codex round 3 on the GLM commits, GLM review on the Luna commits. Then one full gate at the fix3 tip, run while the host is quiet. **10 Nov update:** [Codex round 3](T031-fix-round/codex-rereview-r3.md) CLOSED CN2-1..4 and H-1; H-2 PARTIAL with 3 BLOCKING (CN3-1..3, verified; CN3-3 can release protection for an existing pod). Luna's H-3..H-9 are committed by the orchestrator as WIP `82135d4` (UNVERIFIED: no red baselines; its sandbox could not commit or open DB sockets). **Operator decision: full H-2 spec first** (Opus spec, then Codex critique, then GLM build, then Codex review) before any paid run. Code map done ([h2-codemap.md](T031-fix-round/h2-codemap.md)); **spec drafted: [T031-H2-recovery-spec.md](T031-H2-recovery-spec.md)** (RECOVERY world mode, one unresolved-items gate, recover-before-destroy, single-transaction create resolution, replayable sample resolution, AT-1..AT-12). Codex critique of v1 = [REWORK](T031-fix-round/codex-h2-spec-critique.md) (SC-1..SC-14, all accepted); **spec v2 written** (canonical-derived U1–U6, durable recovery deadline, shared lock order incl. billing wrapper, storage released only at sweep finality, contradiction incident path, fail-fast kept, AT-0..AT-26). Codex re-critique of v2 (round 2 of 2) = [REWORK with exact wording](T031-fix-round/codex-h2-spec-recritique.md) (R1–R8, SC2-1..3); operator chose: fold wording into **v3 and build** (no 3rd critique; Codex reviews the build vs v3). **H-2 build (10 Nov 16:40Z): P1 `0bad31b`, P2 `67500b6`, P3 `2ec18f8`+`3a5710d`+`45e4f2a` committed; orchestrator re-ran P1–P3 part 1 = 151 passed. r3 loop (systemd `t031-h2-resume-loop`) now on P4. In parallel: [Codex review of P1–P3](T031-fix-round/codex-review-h2-p1p3-brief.md) (pinned checkout `.scratch/t031-verify-h2b` @ `45e4f2a`) and [GLM review of Luna `82135d4`](T031-fix-round/glm-review-luna-brief.md). Orchestrator = session aivora-69; aivora-cf is holding.** Original: [GLM xhigh H-2 build](T031-fix-round/h2-build-brief.md) in `.scratch/t031-fix3-worktree`, packages P1–P5, progress + "Resume here" in `T031-fix-round/h2-build-REPORT.md`. Deferred: GLM review of Luna `82135d4` (z.ai budget). Queued for the z.ai reset at 05:14Z: [GLM review of Luna `82135d4`](T031-fix-round/glm-review-luna-brief.md). Luna probe: 215 passed (green only).
Codex's own 9 Nov summary of what is still needed before a paid run: a pullable image,
about 42 GB of weights, verified reference assets, an approved configuration and cap,
then the controller runs three screening clips before the remaining 21.

## Operator routing override — 6 November 2026 (historical)

Use native Codex for all T031 Goldfish/build/review work, no ai-route. Native EGM
review completed; R1/R2 code fixes were independently accepted. Runtime image and
native binding/runner code are built in `.scratch/t031-native-worktree`, branch
`feat/t031-pika-flex-native`, base0851374; uncommitted/unmerged and **NEEDS REVIEW**.
Latest focused group:124passed. Full offline checks/pilot are running under the
CPU-limited durable unit documented in [resume](T031-STEPS-1-3-RESUME.md).
Native reviewer/world/runner workers hit a usage limit; interrupted review is NOT
acceptance. Paid provider effects, model downloads, pushes and publishing remain
unauthorized. Old GLM routing below is historical for this work.


**11 Nov ~04:45Z, operator: "Run goldfish before the H2."** The H-2 resume loop (systemd `t031-h2-resume-loop`) was **stopped**. Its P5 work-in-progress is left uncommitted in `.scratch/t031-fix3-worktree`, and the resume brief handles it. Goldfish on SPEC v0.2.x auto-starts at the z.ai reset (06:22Z). After Goldfish, aivora-69 relaunches the H-2 resume (tag `dramabox:t031-h2-build-r3`, brief `T031-fix-round/h2-build-resume-brief.md`).


**11 Nov, 07:30Z: v3 MASTER SPEC v0.4 is BINDING** ([SPEC-v3.md](v3-workflow/SPEC-v3.md); v0.3 archived). Goldfish findings are applied (reuse of JobService/ProviderOperation/UsageReceipt instead of new systems; a single obligation ledger; all 68 R-IDs and AT-1..34 assigned once, verified by script). Next: phase specs A0 + A (Opus), then a critique each, then GLM builds after H-2. H-2 resumes by systemd timer `t031-h2-resume-loop2` at 11:25Z (operator: start at the z.ai reset).

## Drama Box v3 workflow spec — started 11 Nov 2026

The operator defined a 10-step series workflow (Script Maker → LOCK → bible → all-episode builder → STORY LOCK → character bible with picks, voices, props, locations and wardrobe → CAST LOCK → shotcaller directing → Pika H3 Flex render with the voice reference → edit with background music, SFX and transitions → metadata drafts → Gate 2 → teaser), with a UI at dramabox.aivora.agency. Decisions and the source of truth: [v3-workflow/DECISIONS.md](v3-workflow/DECISIONS.md). Fact-gathering is running (Codex): `v3-workflow/factmap.md` and `v3-workflow/joey-digest.md`. Requirements + operator answers done ([REQUIREMENTS.md](v3-workflow/REQUIREMENTS.md)); **spec drafted: [SPEC-v3.md](v3-workflow/SPEC-v3.md)** (phases A–G, V3-AT-1..17, LLM subscription-first pilot P0–P2). Codex critique of v0.1 = [REWORK, 34 findings, all accepted](v3-workflow/codex-spec-critique.md); **SPEC v0.2** (master spec + per-phase specs A0, A–G; §19 maps every finding). Queued: Goldfish review of v0.2 (auto-starts when z.ai < 45%; reports in `v3-workflow/goldfish/`), then Codex re-critique (round 2 of 2). Operator purchases pending: a paid ElevenLabs plan (free tier now), a Dramabox Bot token (BotFather). Joey's skills (markdown only, no licence stated) are kept at the orchestrator scratchpad `keep/joey-skills/`.

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

- Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`, HEAD
  `0851374`. At this inspection it is 24 commits ahead of the locally recorded
  remote ref and zero behind. No remote fetch or push was performed.
- Existing untracked `.scratch/` and `microdrama/evidence/provider-qualification/`
  are preserved. The live qualification JSONs are not tracked; pushing code alone
  does not back them up. Contract package remains **2.15.0**; contract/generated
  artifacts are guardian-owned.
- A real RunPod lifecycle canary completed on 5 November using a **stub sampler**.
  Its invoice was recorded MATCHED and its lease BILLED. This is not real model,
  Thai-quality, actual-episode or publication qualification. Last recorded pod
  cleanup was successful; this inspection did not query the current provider fleet.
- T046 staging remains OFFLINE_MOCK only. T032–T035 have not been qualified.
- Current preparation is docs/research only; no paid calls, pod creation, production
  database writes, publishing or pushes are authorized by the benchmark draft.

## Board state and verification

T001–T030 accepted; T036–T048 recorded DONE. T045's 4 November independent
acceptance remains valid for its reviewed scope. **T031 is IN_PROGRESS:** lifecycle
canary complete; real Pika H3 Flex/Thai/rights/cost qualification remains open.
T032–T035 are TODO. The later canary-night code delta needs a separate independent
review receipt; do not extend the earlier ACCEPT to cover it.

The latest inspected historical full-check log `.scratch/makecheck-final3.log`
ends **all offline checks passed**, EXIT=0: **2,781 unit / 462 contract / 270
integration**, lint/format passed. This predates `9b133f1`'s invoice-window fix;
no later full-suite receipt was located. No test suite was rerun during the
6 November documentation preparation. The last recorded `make pilot` is the
4 November T045 receipt below (synthetic only). The reported order-sensitive
repair-media-chain test remains a separate follow-up.

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

## T031 canary close-out

Run 14 completed 5 November: reserve → owned pod → endpoint → schema MATCH →
two stub test videos fetched/checksummed → verified termination. The later
console invoice matched and the final sweep settled the lease BILLED at 15:45 UTC.
Run-14 pod cost: **35,753 micro-USD = 35,174 GPU + 579 disk**; the lease settlement
is 35,174 micro-USD. All-night spend is still approximately $0.9 in the narrative,
not an exact reconciled total. Do not rerun completed billing steps or rewrite the
original pending-billing completion JSON.

[Close-out and review coverage](T031-canary-closeout.md) records source hashes,
limits, the prior test receipt and the later review gap. The older
[T031-preparation.md](../../microdrama/evidence/T031-preparation.md) contains the
historical attempt log. Its earlier preparation/open-defect paragraphs are
superseded by the dated close-out, not current blockers.

## Steps1–3 native implementation status

[Resume and exact next work](T031-STEPS-1-3-RESUME.md) is the current execution
front door. [Receipt](t031-benchmark/native-build/current-receipt.json) records
81-file snapshot, image ID,124-test result and running full-gate unit.

The code-only image exposes16 real native CPU node schemas without weights.
Contract package is2.16.0 in the isolated worktree; main checkout remains2.15.0.
The24-sample connected offline fixture uses canonical jobs/holds/leases/recovery,
not real H3 quality. Native binding/world/runner/CLI review and full gates remain
outstanding; no new milestone or live qualification has been accepted.

## What remains, in order

1. **Pika H3 Flex native-audio preparation:** operator-selected model on
   6 November; no default external TTS or model substitution. The
   [benchmark packet](T031-benchmark-packet.md) contains official source/workflow
   pins, eight Thai shot scripts × three seeds, proposed quality criteria and an
   **unsigned $8 new-exposure envelope** for one Ref2VA 480p configuration.
2. Close the preparation gaps before requesting paid-run approval: independent
   review of `13da3e2..0851374`, compatible real-model image/binder, A40 fit,
   rights/access and reference/voice evidence, evaluator coverage and a durable
   shared-budget execution path for 24 samples. The existing canary permits only
   three attempts globally and is not that execution path.
3. Reconcile prior spend and remaining account allowance, refresh the actual quote,
   pin runtime image/schema/prompts/references and hard stops, then request approval
   of the exact executable run. The historical $5 canary approval does not authorize
   the benchmark. Pika Flex uses the H3 community weight license; intended global
   release rights remain unresolved and must be recorded honestly.
4. T032 controlled real account tests → T033 first actual episode through existing
   Gate 1/Gate 2 → T034 ten qualifying episodes plus seven-day windows → T035 final
   operational handoff. These remain separate live gates.
5. Optional operator-decided domain setup: `deployment/staging/DOMAIN-RUNBOOK.md`.

The earlier T045 push through `13da3e2` is complete. Later canary-night changes are
local according to the stored remote ref; no new push is performed or approved here.
A benchmark preparation packet, source pins and a stub canary are not live quality
or production acceptance.
