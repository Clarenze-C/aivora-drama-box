# Drama Box v3: weekend orchestration runbook for a GLM session (Fri 13 – Sun 15 Nov 2026)

Written by the Opus orchestrator (session e4e3c05c) on Fri 13 Nov 03:30Z. The operator drives all day Saturday and
Sunday, and Opus is out of weekly quota until Mon 00:00 SGT (Sun 15:59Z). **A `cms glm` session orchestrates
from this file.** It updates the **STATE** section after every step. On Monday, Opus reads STATE and re-checks every
GLM ruling.

## Start (operator, once)

```bash
cms glm
```

`cms` sets the provider for **new** terminals, so open a new terminal and run:

```bash
cd /root/AIVORA/drama-box && claude
```

Check that the session really runs on GLM (the banner can be stale): `/proc/<pid>/environ` must show the z.ai
`ANTHROPIC_BASE_URL`. Then type:

```text
/loop Follow docs/microdrama-system/v3-workflow/WEEKEND-GLM-RUNBOOK.md: re-read its STATE, do the next ready queue item, update STATE, then schedule the next wakeup.
```

## Hard rules (stop rather than break one)

1. **Offline only.** The following are all forbidden this weekend:
   - RunPod, Vertex/Nano Banana, Botnoi, ElevenLabs or any paid or provider call;
   - publishing or Telegram sends;
   - `git push` and any merge, including into `/root/.claude` main;
   - deletion commands;
   - service restarts.

   Never print env vars, `.env` files, keys or tokens.
2. **Cross-provider work goes only through `ai-route`:**
   - builds: `ai-route build`, with a briefs-and-`-REPORT.md` pattern;
   - Codex: `ai-route critique|review`, at most 2 jobs at once, never `--approve-for-me`;
   - you never call `ai-route plan` (Opus).
   - `--out` keeps only the job's **final message**. Briefs therefore name a separate `-REPORT.md`. For swarm jobs,
     recover the full text from `~/.claude/projects/<cwd-key>/<session>.jsonl` (the longest assistant text).
3. **Quota (operator, 13 Nov: SFW and ICT are idle this weekend, so Drama Box gets all of GLM and Codex):**
   - **GLM:** at most **2 GLM-5.3 jobs at once**, each started only when z.ai 5h < 50%, and only when independent
     (different worktrees, or one code and one docs-only), plus at most **1 GLM-5.3-Flash swarm** (1/3 quota).
   - **Codex:** at most 2 jobs at once (hard limit). Launch no new Codex job once Codex week ≥ **75%**; the rest is
     for Mon–Thu.
   - **CPU:** at most **one full gate** (`make check` + `make pilot`) at a time. Builders' focused pytest runs are fine.
   - On exit 75, retry after the reset. Never swap models.
4. **No polling.**
   - Long jobs run as `systemd-run` units or `run_in_background` with a `tail --pid` /
     `journalctl -f … | grep -m1` watcher.
   - Idle `ScheduleWakeup` ≥ 1200 s.
5. **Every build:**
   - tests first, red recorded;
   - `make lint` before each commit;
   - pytest under `systemd-run --scope -p CPUQuota=45%`, with `env PATH="/usr/sbin:$PATH"` (the PG fixture needs
     `runuser`), the four offline env vars and a `--basetemp` containing `basetemp`;
   - no stash-only WIP;
   - no new migration numbers beyond those a spec allocates (0027 = A0-D; 0028–0031 = A1; A2 from 0032).
6. **Acceptance:**
   1. Re-run at least two of the builder's red/green lines yourself.
   2. Run the full gate (`make check` then `make pilot`) in a **new pinned detached checkout**. Copy
      `.scratch/a0d-gate/.scratch/gate/run.sh` and change the paths; the unit PATH must include `/usr/sbin`.
   3. Have Codex review the diff.

   Accept only on gate green **and** Codex ACCEPT.
7. **Reviews: two rounds, then stop the item.** Write it under OPERATOR QUEUE and move to the next item.
8. **Rulings:**
   - You may rule on Codex/Goldfish findings for notes and package specs, in `<item>-rulings.md`, each with its
     reason and marked "GLM ruling, Opus re-check Mon".
   - **Never** change `SPEC-v3.md`, `DECISIONS.md` or an operator decision, and never weaken an acceptance test.
     If a finding needs that, stop the item and queue it for the operator/Opus.

## Scheduling: fill every free slot at each wakeup

Four tracks run side by side. At each wakeup, in this order:

1. **Collect results:**
   - read finished jobs;
   - update STATE;
   - write rulings or fix briefs for anything that came back.
2. **Codex slot free?** Launch the highest-priority ready Codex job: code reviews first, then note critiques, then
   spec critiques.
3. **No code build running and z.ai < 50%?** Launch the next ready code build. Track A (critical path) comes
   before Track T.
4. **One code build running, z.ai < 50%, and a docs job ready?** Launch one docs job in parallel (Track S).
5. **A swarm slot free and a fact map needed?** Launch it with `ai-route swarm`.
6. `ScheduleWakeup`: about 1200–1800 s while jobs run; just after the reset time when everything waits on quota.

| Track | Kind | Items |
|-------|------|-------|
| **A**: phase A code (critical path, sequential) | code | Q1 A0-D → Q3 A1 → A2 → A3 → A4 → A5 → A6a → A6b → A6c. Each needs its note/spec critiqued and accepted, the previous package accepted, then build → review → gate. A4/A5/A6a/A6c have no design note: build briefs come straight from `phase-A-spec.md` §10, reviewed "with the diff" |
| **T**: T031 run-readiness | code, other tree | Q2. Independent of Track A: may build while an A build runs |
| **S**: specs and notes | docs only | Q4 note revisions; Q5 phase B; **Q7 phases C, D, E, F, G spec drafts** |
| **R**: Codex | reviews | serves A, T and S by priority |

Doc jobs never edit code, `SPEC-v3.md` or `DECISIONS.md`, so they can run beside any build.

## Queue (priority order; skip an item whose "waits for" isn't met)

| # | Item | Now | Next step(s) | Waits for |
|---|------|-----|--------------|-----------|
| Q1 | **A0-D** (gateway, `LlmStep`, migration 0027) | Gate **green at `ea1cc10`** (3,137/462/314). Codex round 1 = **FIX-REQUIRED** (`codex-review-a0d.md`: AD-1..10 BLOCKING, AD-11..13 SHOULD-FIX). Fix brief `a0d-fix1-brief.md` written; GLM build `dramabox:a0d-fix1` running in `.scratch/a0d-gateway` from 17:57Z | (1) read `a0d-fix1-REPORT.md` + `a0d-fix1-final.md`; re-run ≥2 red/green lines; (2) round-2 Codex **review** scoped to AD-1..13 (range `ea1cc10`..fix tip); (3) full gate in a **new pinned detached checkout** at the fix tip; ACCEPT only on gate green **and** Codex ACCEPT → STATE "accepted" (no merge) | fix build done |
| Q2 | **T031 run-readiness (R5)** | Codex critique round 1 = **REWORK** (`T031-fix-round/codex-r5-critique.md`: R5C-1..9 BLOCKING, R5C-10..12 SHOULD-FIX; **P accepted** with live comparison mandatory). All 12 ACCEPTED in `r5-critique-rulings.md` (placement (a)); docs job `dramabox:r5-spec-v03` → spec v0.3 running from 18:06Z | (1) read `r5-spec-v03-final.md` + the v0.3 diff; (2) write the R5a–R5e build brief from v0.3 §6; (3) GLM build in worktree `.scratch/t031-r5` from `feat/t031-fix3` tip; (4) Codex review; (5) gate. **Image rebuild local only. No push, no paid run** — both wait for the operator | v0.3 job done |
| Q3 | **A1** (discriminator, gates, decision transaction; migrations 0028–0031) | Note `A1-design-note.md` v1.2. Codex round 2 = **REWORK** (`codex-a1-note-recritique.md`: N1R-1..3 BLOCKING, N1R-4..12 SHOULD-FIX, build readiness no). **Stopped per rule 7 (two rounds) → OPERATOR QUEUE** | Operator/Opus Monday: re-check the rulings, decide round 3 vs reduced note. No build this weekend | operator/Opus |
| Q4 | **A2, A3, A6b design notes** | Drafted 12 Nov (`A2-`, `A3-`, `A6b-design-note.md`); never critiqued | Codex critique round 1 each (pattern `a1-note-critique-brief.md`) → rulings → GLM revises the note → round 2. Builds follow A1 in table order: A2 → A3 → A4/A5/A6a (no note) → A6b → A6c | Codex reset |
| Q5 | **Phase B spec** v0.3 | Draft (`phase-B-spec.md`; operator answered O-B1..6; one neutral voice per speaker). **Goldfish started 03:22Z by Opus** (unit `phase-b-goldfish`; reports in `phase-b-review/goldfish/`; final `phase-b-goldfish-final.md`) | Goldfish done → rulings → Codex critique round 1 (pattern `spec-critique-brief.md`) → B1 and B5 design notes | z.ai < 50% |
| Q6 | **A0-R1** (`dramabox-llm` ai-route role, `/root/.claude`) | Fix round 1 done. Codex round 2 = **FIX-REQUIRED** (`codex-review-a0r1-r2.md`: RR2-1..3 BLOCKING, RR2-4..7 SHOULD-FIX; 8/15 originals CLOSED). **Stopped per rule 7 (two rounds) → OPERATOR QUEUE** | Operator/Opus Monday: decide a fix round 3 vs shipping as-is; merge into `/root/.claude` main stays operator-gated either way | operator/Opus |
| Q7 | **Phase C–G spec drafts** (Track S, in parallel with builds) | Not started. Master `SPEC-v3.md` v0.4.6 §4.4–§4.10, §5–§13, the §15.1 phase/AT table, §15.2 R-ID ownership | Per phase, in order **C, F, E, G, D**. D last: it depends on T031's real Pika results. (1) a swarm fact map (copy `b-factmap-brief.md`, retargeted to that phase's code); (2) `ai-route build` of a docs-only spec brief producing `phase-<X>-spec.md` v0.1, modelled on `phase-B-spec.md`: requirements, design, packages, acceptance rows mapped to that phase's V3-AT ids, open questions with recommendations; (3) Goldfish; (4) Codex critique only once A/B critiques are done. **No build of C–G this weekend** | z.ai < 50% |

**Codex queue unit (set up by Opus): `dramabox-codex-queue`.** Timer at 10:31Z; script `codex-queue.sh` (copy beside this file).
- It runs 7 items in order, 2 at a time: A0-D review, R5 critique (waits until `T031-fix-round/codex-r5-critique-brief.md`
  exists), A1 round 2, A2/A3/A6b round 1, A0-R1 round 2. Each writes its `--out` file next to its brief.
- It retries exit 75 and holds at Codex week ≥ 75%. Log: `journalctl -u dramabox-codex-queue -o cat`; state:
  `scratchpad/keep/codex-queue.state` in the Opus session.
- **Never edit the script while the unit runs.** For further Codex jobs (fix-round re-reviews, build reviews, spec critiques),
  run `ai-route review|critique` directly. ai-route refuses a third concurrent Codex job with exit 75, so retry after one ends.

**Codex order:** Q1 review and Q2 critique first (2 slots); then Q3 round 2 and the Q4 notes; then build reviews as A1/R5
land; then Q6, Q5, Q7 critiques. A code review always jumps ahead of a critique.

## STATE (GLM: append one dated line per step; newest last)

- 13 Nov 03:30Z (Opus): queue written.
- 13 Nov 03:50Z (Opus): operator gives Drama Box all of GLM and Codex for the weekend. Rule 3 widened (2 GLM jobs +
  1 swarm, Codex ≤ 75%); four-track scheduling added; Q7 widened to C–G spec drafts.
  - A0-D gate running.
  - R5 Goldfish at 03:40Z.
  - Codex week 99% until 10:30Z.
  - z.ai 5h 26% (reset 03:41Z).
  - Opus week 88%.

- 13 Nov 03:15Z (operator): **Opus orchestrates until the operator starts the GLM run (~Fri 16:00Z = Sat 00:00 SGT)**;
  the GLM session owns everything after that. Opus leaves STATE current at handover.
- 13 Nov 03:25Z (Opus): running now:
  - R5 Goldfish (`t031-r5-goldfish`, from 03:12Z);
  - phase B Goldfish (`phase-b-goldfish`, cwd `phase-b-review/`);
  - phase C fact-map swarm (`c-factmap`, out `c-factmap.md`);
  - A0-D gate (`a0d-offline-gates`).

  Codex queue timer at 10:31Z (6 of 7 briefs written; the R5 critique brief follows the Goldfish resolution).
- 13 Nov 04:25Z (Opus): R5 Goldfish done (1 Blocker, 17 Majors, 20 Nits; reports `T031-fix-round/r5-goldfish/`).
  - Opus ruled every finding in `T031-fix-round/r5-goldfish-rulings.md`; **Q1 = P** (predicted schema).
  - GLM applies the rulings → spec v0.2 (unit `r5-spec-v02`, after the phase B Goldfish ends). On success it publishes
    `codex-r5-critique-brief.md`, which the Codex queue then picks up.
  - Phase C fact map done (`c-factmap.md`); phase C spec draft queued (unit `phase-c-spec`).
- 13 Nov 04:45Z (Opus): A0-D gate run 1 at `c25b527` was RED. Unit 3,137 and contract 462 passed; integration had
  2 failed + 4 errors, all hard-coded migration tails missing 0027. Opus fixed it in `ea1cc10` (same pattern as
  `2ceb341`; 12 passed).
  - Gate run 2 at `ea1cc10` is running (unit `a0d-offline-gates2`).
  - The Codex review brief is re-scoped to `0cda424..ea1cc10`.
- 13 Nov 06:25Z (Opus): **A0-D gate run 2 at `ea1cc10` GREEN**: 3,137 unit / 462 contract / 314 integration passed,
  `make check: all offline checks passed`, `make pilot` 0. Receipts in `.scratch/a0d-gate/.scratch/gate/`; run 1's log is kept.
  A0-D now waits only for the Codex review (queue item 1).
- 13 Nov 06:50Z (Opus):
  - **R5 spec v0.2 done** (GLM, see git log); its Codex brief is published, so queue item 2 is ready.
  - **Phase C spec v0.1 drafted** (490 lines). Its Goldfish is queued at the 08:41Z window (unit `phase-c-goldfish`,
    cwd `phase-c-review/`).
  - **Phase B Goldfish done** (1 Blocker / 22 Major / 22 Nit; reports in `phase-b-review/`). Opus ruled every finding
    (`phase-b-goldfish-rulings.md`).
  - Unit `phase-b-v04` applies the rulings → v0.4 at 08:41Z, **then launches the Codex critique round 1 itself**
    (out `codex-phase-b-critique.md`).
  - GLM after handover: read the results; write the rulings or round-2 inputs.

- 13 Nov 17:55Z (GLM): handover tick. The Codex queue ran clean overnight (all 7 items exit 0) and the
  phase B v0.4 unit launched its critique. Verdicts read:
  - **Q1 A0-D: FIX-REQUIRED** (AD-1..10 BLOCKING, AD-11..13 SHOULD-FIX; `codex-review-a0d.md`).
  - **Q3 A1 note: REWORK** (N1R-1..12; build readiness no) → stopped, rule 7.
  - **Q6 A0-R1: FIX-REQUIRED** (RR2-1..7; 8/15 originals closed) → stopped, rule 7.
  - Launched: A0-D fix build `dramabox:a0d-fix1` (brief `a0d-fix1-brief.md`, GLM-5.3,
    cwd `.scratch/a0d-gateway`, base `ea1cc10`) and phase F fact-map swarm `dramabox:f-factmap`
    (brief `f-factmap-brief.md`).
  - Still to process (next wakeup): T031 R5 critique (`T031-fix-round/codex-r5-critique.md`),
    Q4 A2/A3/A6b round-1 critiques, phase B critique round 1, phase C Goldfish → v0.2.
  - Housekeeping: two Nov-12 scopes in the a0d worktree hold only idle orphaned PG fixtures (left
    in place); `t031-ghcr-push.service` failure dates from Wed 4 Nov and the push was denied —
    nothing pushed, no weekend violation.
  - Quota at tick: z.ai 5h 19% (reset 18:43Z); Codex 5h 0%, week 13%.

- 13 Nov 18:07Z (GLM): Q2 R5 critique ruled — all 12 findings ACCEPTED (R5C-10 takes placement (a),
  the only conforming option); Codex accepts P with live comparison mandatory. `r5-critique-rulings.md`
  written; docs job `dramabox:r5-spec-v03` launched (spec v0.3). Running now: a0d-fix1 (build),
  r5-spec-v03 (docs), f-factmap (swarm) = at the rule-3 limit; z.ai 5h 23%.
  Next tick: R5 build brief from v0.3; Q4 A2/A3/A6b rulings; phase B critique rulings; phase C → v0.2.
- 13 Nov 18:14Z (GLM): **f-factmap done and verified** (107 lines, 45 citations, 6 honest NOT FOUNDs
  incl. teaser and thumbnail pick). Phase F spec brief `phase-f-spec-brief.md` written — **launch held**:
  both GLM-5.3 slots busy (a0d-fix1 10m in and healthy; r5-spec-v03 running). Launch phase-F-spec the
  moment r5-spec-v03 exits (docs slot, main checkout). Goldfish for phase F goes to a fresh cwd
  `phase-f-review/` after the draft lands.
- 13 Nov 18:21Z (GLM): **R5 spec v0.3 committed** (`980eb19`, 560 lines; 12/12 applied, nothing
  BLOCKED; new package R5f = per-pod billing verification, no migration). Worktree `.scratch/t031-r5`
  created (branch `feat/t031-r5` at `104b26b`, venv symlinked); build brief `T031-fix-round/r5-build-brief.md`
  written — **launches when a0d-fix1 frees the code slot**. Phase F spec draft running (`phase-f-spec`).
  Running: a0d-fix1 (code) + phase-f-spec (docs); z.ai 5h 29%.
- 13 Nov 18:28Z (GLM): **phase F spec v0.1 drafted and committed** (`d480aec`, 567 lines; F1–F10
  packages, acceptance F-T1…F-T13, 10 open questions with recommendations; O-8 stays the operator's).
  Its O-F8 flags that **N43 is cited in SPEC-v3 §2.2 but defined nowhere** — master-spec gap for
  Opus Monday, GLM cannot fix SPEC-v3. Goldfish launched (`phase-f-goldfish`, cwd `phase-f-review/`).
  Running: a0d-fix1 (code) + phase-f-goldfish; z.ai 5h 35%.
- 13 Nov 18:40Z (GLM): **phase C Goldfish ruled** (75 findings: 2 Blocker / 27 Major / 46 Nit —
  **all ACCEPTED**, none rejected; BLK-1 = initial-generation batch at setup-budget approval, 3
  candidates/root item, one job per candidate; BLK-2 = C-B1-pattern kind mapping + CHECK growth; C-3
  dropped; C8 routed note-first). `phase-c-goldfish-rulings.md` + apply brief `phase-c-v02-brief.md`
  written — **c-spec-v02 launches when a GLM slot frees** (running: a0d-fix1 + phase-f-goldfish).
  Two operator items extracted from the Nits (O-C1 neutral-source intake; V1 lock carve-out N34) →
  OPERATOR QUEUE. After v0.2: Codex critique round 1 (A/B critiques done, so C's critique is unblocked).
- 13 Nov 19:05Z (GLM): **phase B critique round 1 ruled** (16 findings: PB-1..9 BLOCKING,
  PB-10..16 SHOULD-FIX — **all ACCEPTED**; PB-11 takes option 1; PB-15 strengthens B-T5; main choices
  blessed by Codex). `phase-b-critique-rulings.md` + apply brief `phase-b-v05-brief.md` written.
  Docs-job queue: c-spec-v02 first, then b-spec-v05 (both launch as GLM slots free; a0d-fix1 step 3/5
  and phase-f-goldfish still running). z.ai 5h reset → 5%.
- 13 Nov 19:15Z (GLM): **phase F Goldfish ruled** (73 findings: 4 Blocker / 33 Major / 36 Nit —
  all ACCEPTED; CON-B1 = in-place date UPDATE, CON-B2 = option (a) synthetic carrier episode,
  CON-B3 = F5 conditionally blocked on **O-8 (operator)**, CON-B4 = gate re-map; CON-M6 extends C's
  picks engine). `phase-f-goldfish-rulings.md` + apply brief `phase-f-v02-brief.md` written.
  **O-8 added to OPERATOR QUEUE** (blocks F5 only). Launched `c-spec-v02` (docs slot freed by the
  goldfish exit). Docs queue: b-spec-v05, then f-spec-v02. Running: a0d-fix1 + c-spec-v02.
- 13 Nov 19:30Z (GLM): **A2 note round 1 ruled** (N2-1..9 BLOCKING, N2-10..15 SHOULD-FIX —
  **all 15 ACCEPTED**, all technical; arithmetic + migration allocation were confirmed correct;
  N2-15 strengthens the race tests). `a2-critique-rulings.md` + revision brief `a2-note-rev1-brief.md`
  written. Docs queue now: b-spec-v05 → f-spec-v02 → a2-note-rev1. A3/A6b rulings next ticks.
  Running: a0d-fix1 (step 3/5, debugging AD-10 fake-attempt semantics) + c-spec-v02.
- 13 Nov 19:40Z (GLM): **phase C spec v0.2 committed** (`ee2ac72`, 734 lines, nothing BLOCKED;
  both Blockers applied with steering, all 27 Majors, all nit buckets; O-C1/O-C9 left OPEN (OPERATOR)).
  Launched: `b-spec-v05` (docs slot) and **Codex critique round 1 for phase C** (`phase-c-critique`,
  brief `codex-phase-c-critique-brief.md` — first Codex job of the GLM weekend). Running:
  a0d-fix1 + b-spec-v05 + phase-c-critique. Docs queue: f-spec-v02 → a2-note-rev1.
- 13 Nov 19:52Z (GLM): **phase C Codex round 1 ruled** (PC-1..7 BLOCKING, PC-8..16 SHOULD-FIX —
  **all 16 ACCEPTED**; former Blockers called partially resolved, packages/tests improved; entry
  helper fires after setup approval AND STORY LOCK; typed lock contracts grow; candidate parent
  stamps immutable; voice preimage exact; flock safety model rewritten). `phase-c-critique-rulings.md`
  + apply brief `phase-c-v03-brief.md` written. Docs queue: f-spec-v02 → a2-note-rev1 → c-spec-v03
  (round-2 critique last). Running: a0d-fix1 + b-spec-v05; Codex free again.
- 13 Nov 20:05Z (GLM): **phase B v0.5 committed** (`cb8f8b5`, 838 lines, 16/16 applied, none
  BLOCKED). Launched: `f-spec-v02` (docs) and **phase B Codex round 2** (`phase-b-recritique`,
  scoped to PB-1..16, final B round). Running: a0d-fix1 + f-spec-v02 + phase-b-recritique.
  Docs queue: a2-note-rev1 → c-spec-v03.
- 13 Nov 20:12Z (GLM): **phase B round 2 = REWORK (close)**: 11/16 CLOSED, PB-14 REGRESSED;
  PB5-1 BLOCKING + PB5-2..5 SHOULD-FIX, all with replacements. Rule 7: no round 3 — all 5 ACCEPTED
  and applied as **v0.6** (brief `phase-b-v06-brief.md`, queued); **Opus re-checks Monday: accept v0.6
  vs round 3** (queued). B1/B5 design notes wait for that call. Running: a0d-fix1 + f-spec-v02;
  Codex free. Docs queue: a2-note-rev1 → c-spec-v03 → b-spec-v06.
- 13 Nov 20:20Z (GLM): **phase F v0.2 committed** (`ef63e65`, 786 lines, 73/73 applied, none
  BLOCKED; F5 conditionally blocked on O-8 as ruled). Launched: `a2-note-rev1` (docs) and **phase F
  Codex critique round 1** (`phase-f-critique`). Running: a0d-fix1 + a2-note-rev1 + phase-f-critique
  (Codex 1/2). Docs queue: c-spec-v03 → b-spec-v06.
- 13 Nov 20:32Z (GLM): **phase F Codex round 1 ruled** (PF-1..11 BLOCKING, PF-12..17 SHOULD-FIX
  — **all 17 ACCEPTED**; version-selected adapters, admission comparator fix, carrier as explicit
  crossing, season DAG, submit re-fencing, guarded rebinding, extension carry-forward; O-8/F5 and the
  E-contract kept as declared dependencies). `phase-f-critique-rulings.md` + apply brief
  `phase-f-v03-brief.md` written. Docs queue: c-spec-v03 → b-spec-v06 → f-spec-v03 (round-2 critique
  after, F's last). Running: a0d-fix1 + a2-note-rev1; Codex free.
- 13 Nov 20:21Z (GLM): **A3 note round 1 ruled** (6 BLOCKING + 4 SHOULD-FIX — **all 10 ACCEPTED**;
  0035 allocation + resolver confirmed correct; CANCELLED recovery path made reachable; lock audit
  widened to the real provider-op chains; A-T12a corrected not weakened). `a3-critique-rulings.md` +
  `a3-note-rev1-brief.md` written. Docs queue: c-spec-v03 → b-spec-v06 → f-spec-v03 → a3-note-rev1.
  A6b rulings remain (last Q4 item). Running: a0d-fix1 (unit sweep phase) + a2-note-rev1.
- 13 Nov 20:27Z (GLM): **A2 note v1.1 committed** (`b454832`, 954 lines, 15/15 applied, none
  BLOCKED). Launched: `c-spec-v03` (docs) and **A2 Codex round 2** (`a2-note-r2`, scoped to N2-1..15,
  final A2 round). Running: a0d-fix1 + c-spec-v03 + a2-note-r2 (Codex 1/2). Docs queue: b-spec-v06
  → f-spec-v03 → a3-note-rev1. A6b rulings still pending on GLM's desk.
- 13 Nov 20:35Z (GLM): **A2 round 2 = REWORK** (5/15 closed, N2-8 regressed; N2R2-1..7 BLOCKING,
  N2R2-8..10 SHOULD-FIX). Rule 7 → all 10 ACCEPTED, applied as **v1.2** (brief `a2-note-rev2-brief.md`,
  queued), **no round 3**; Opus decides Monday (queued). Running: a0d-fix1 + c-spec-v03; Codex free.
  Docs queue: b-spec-v06 → f-spec-v03 → a3-note-rev1 → a2-note-rev2. A6b rulings still pending.
- 13 Nov 20:44Z (GLM): **phase C v0.3 committed** (`6ce01a4`, 846 lines, 16/16 applied, none
  BLOCKED). Launched: `b-spec-v06` (docs) and **phase C Codex round 2** (`phase-c-recritique`, final C
  round). Running: a0d-fix1 + b-spec-v06 + phase-c-recritique. Docs queue: f-spec-v03 → a3-note-rev1
  → a2-note-rev2. A6b rulings still pending on GLM's desk.
- 13 Nov 20:53Z (GLM): **phase C round 2 = REWORK** (9/16 closed, PC-16 regressed; PC5-1/2 BLOCKING,
  PC5-3..7 SHOULD-FIX). Rule 7 → all 7 ACCEPTED, applied as **v0.4** (brief `phase-c-v04-brief.md`,
  queued), **no round 3**; Opus decides Monday (queued). Running: a0d-fix1 + b-spec-v06; Codex free.
  Docs queue: f-spec-v03 → a3-note-rev1 → a2-note-rev2 → c-spec-v04. A6b rulings still pending.
- 13 Nov 21:00Z (GLM): **phase B v0.6 committed** (`5d7f9c3`; all 5 round-2 rulings applied, none
  BLOCKED; B-T3/B-T7/B-T11 only gained clauses; B1/B5 notes wait on Monday's Opus call, as ruled).
  Launched `f-spec-v03` (docs). Running: a0d-fix1 + f-spec-v03; Codex free. Docs queue: a3-note-rev1
  → a2-note-rev2 → c-spec-v04. A6b rulings still pending on GLM's desk.
## OPERATOR QUEUE (things only the operator can do; GLM appends)

- T031 R5, once accepted: push the rebuilt image; write the Comfy gateway token file (`read -rs`, 0600); capture an
  A40 quote; sign the authorization; run `benchmark execute --phase screen`. The orchestrator prepares all of it.
- A0-R1, on Codex ACCEPT: approve the merge into `/root/.claude` main (staging only `scripts/ai_route.py`,
  `models.json`, `scripts/tests/ai_route/`).
- A0-D, once accepted:
  - install the gateway's systemd unit, group 64010 and directories;
  - OK the live qualification (≤ 5 calls).
- Before go-live: rotate the Dramabox Bot token.
- A1 design note: Codex round 2 = REWORK, 3 BLOCKING remain (N1R-1 the recursive view cannot compile;
  N1R-2 the V1 schema pin breaks frozen bytes; N1R-3 extension approvals collide with season history).
  Stopped after two review rounds. Opus re-checks Monday; decide round 3 vs a reduced note.
- A0-R1: Codex round 2 = FIX-REQUIRED, 3 BLOCKING remain (RR2-1 a duplicate observer can overwrite the
  owner's terminal output; RR2-2 malformed terminal fields hide known isolation violations; RR2-3 the
  shared deadline still does not bound the whole operation). Stopped after two review rounds. Decide
  Monday whether one more fix round is worth it; the merge into `/root/.claude` main stays yours.
- Phase C pre-build decisions (from Goldfish N27/N34, needed before C6/C7 build):
  (1) O-C1 neutral-source voice intake — a DECISIONS "decide before phase C" item still open;
  (2) V1 `create_episode` keeps no identity lock (permanent carve-out) — needs your nod.
- Phase F: O-8 ruling (EN/ZH caption delivery) — needed before F5 builds. Recommendation on record:
  YouTube caption tracks now (post-publish `upload_captions`); TikTok/Facebook TH-only until T032
  qualifies caption files; flip per destination. F1–F4 proceed without it.
- Phase B spec: round 2 came back REWORK by one BLOCKING (PB5-1 re-entry lifecycle guards) after
  11/16 closed. GLM applied all round-2 rulings as v0.6 but ran no round 3 (rule 7). Monday: Opus
  re-checks `phase-b-recritique-rulings.md` and either accepts v0.6 or orders the round-3 critique;
  B1/B5 design notes wait on that decision.
- A2 note: round 2 REWORK after 5/15 closed (7 BLOCKING remain, incl. the outer billing lock cycle).
  GLM applied all round-2 rulings as v1.2, no round 3 (rule 7). Monday: Opus re-checks
  `a2-recritique-rulings.md`; accept v1.2 vs round 3. A2's build waits behind A1 regardless.
- Phase C spec: round 2 REWORK after 9/16 closed (2 BLOCKING remain: reroll-generation freshness,
  cross-system recovery admission). GLM applied all round-2 rulings as v0.4, no round 3 (rule 7).
  Monday: Opus re-checks `phase-c-recritique-rulings.md`; accept v0.4 vs round 3.
