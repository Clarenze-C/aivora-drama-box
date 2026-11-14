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
| Q1 | **A0-D** | Fix1 built at `6974d5a` (all 13 addressed; GLM re-ran `tests/unit/llm` 62 passed). **Round 2 = FIX-REQUIRED** (`codex-review-a0d-r2.md`: 6 closed, AD-1 regressed, AD5-1..10). **Stopped per rule 7 → OPERATOR QUEUE.** Gate at `6974d5a` finishing for evidence; no merge, no round 3 this weekend | Monday (Opus): re-read the round-2 report + gate receipts; decide fix round 2 vs re-scope; A0-R1 dependency noted | operator/Opus |
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
- 13 Nov 20:47Z (GLM): **A6b note round 1 ruled** (N6-1..6 BLOCKING, N6-7..11 SHOULD-FIX —
  **all 11 ACCEPTED**; try-lock approach confirmed sound; per-action ownership checks, INTENTS recovery
  identities, V1 key/eligibility preservation, integer-only payloads, the missing two-minute LLM
  reconciler trigger added). `a6b-critique-rulings.md` + `a6b-note-rev1-brief.md` written. **Q4 fully
  ruled** (A2/A3/A6b round 1 all done; revisions queued). Docs queue: a3-note-rev1 → a2-note-rev2
  → c-spec-v04 → a6b-note-rev1. Running: a0d-fix1 + f-spec-v03; Codex free.
- 13 Nov 20:52Z (GLM): **A0-D fix1 build DONE** (2h39m): all 13 findings closed at tip `6974d5a`
  (three commits on `ea1cc10`; report `a0d-fix1-REPORT.md`; two full-unit sweeps killed at the background
  time limit — chunked coverage recorded; six documented deviations). Acceptance started: GLM re-running
  `tests/unit/llm` itself; **Codex round-2 review launched** (`a0d-review-r2`, scoped to AD-1..13,
  `--base ea1cc10`). Next: on my green line → full gate in a new pinned checkout at `6974d5a` + R5 build
  launch (code slot free; z.ai check first). Running: f-spec-v03 + a0d-review-r2 + my verify run.
- 13 Nov 20:55Z (GLM): **phase F v0.3 committed** (17/17 applied; round-2 critique launched —
  `phase-f-recritique`, Codex slot 2/2). **Acceptance step 1 GREEN by GLM's own run**: `tests/unit/llm`
  62 passed (matches builder); second suite (integration, 53) re-runs after the gate to avoid CPU
  contention. **Gate running** at pinned `6974d5a` (`a0d-gate2` checkout, unit `dramabox-a0d2-gates`,
  receipts `.scratch/a0d-gate2/.scratch/gate/`). **z.ai 5h 69% ≥ 50%: all GLM jobs held** (docs queue
  a3-note-rev1 → a2-note-rev2 → c-spec-v04 → a6b-note-rev1, R5 build) until the 23:43Z reset.
  Running: a0d-review-r2 + phase-f-recritique (Codex 2/2) + the gate.
- 13 Nov 21:05Z (GLM): **A0-D round 2 = FIX-REQUIRED** (6 CLOSED: AD-2/3/4/5/12/13; AD-1 REGRESSED;
  AD5-1..10: 7 BLOCKING + 1 partial-set + AD5-8/9 SHOULD-FIX; every finding has a Fix line).
  **Rule 7: two rounds done → A0-D STOPS for the weekend** → OPERATOR QUEUE. The gate at `6974d5a`
  still runs (evidence for Monday). Codex slot free (1/2). z.ai still ≥ 50% — GLM queue held.
- 13 Nov 21:02Z (GLM): **phase F round 2 = REWORK** (9/17 closed; PF5-1..4 BLOCKING, PF5-5..7
  SHOULD-FIX). Rule 7 → all 7 ACCEPTED, applied as **v0.4** (brief `phase-f-v04-brief.md`, queued),
  **no round 3**; Opus decides Monday (queued). Codex now idle. GLM queue still held (z.ai ≥ 50%);
  docs queue on release: a3-note-rev1 → a2-note-rev2 → c-spec-v04 → a6b-note-rev1 → f-spec-v04.
  Running: the gate only. **All Codex round-2 results are now in and ruled.**
- 13 Nov 21:43Z (GLM): **Gate at `6974d5a` GREEN**: make check all offline checks passed (462
  contract / 337 integration in the tails; unit earlier in log), `make pilot` OK (mock, 303,000 µUSD
  fake). Receipts `.scratch/a0d-gate2/.scratch/gate/`. A0-D remains **stopped** (round-2 FIX-REQUIRED,
  rule 7): gate green + Codex ACCEPT was the bar — Monday's decision now has both halves on the table.
  Second GLM verification suite (`tests/integration/llm_gateway`) running. GLM docs queue still held
  (z.ai ≥ 50%, reset 23:43Z).
- 13 Nov 21:45Z (GLM): **Acceptance step 1 complete** — both builder suites re-run by GLM:
  `tests/unit/llm` 62 passed, `tests/integration/llm_gateway` 53 passed (exact match to claims).
  z.ai 77% — docs queue held until 23:43Z; nothing else runnable. Next actions: at reset → resume
  docs queue (a3-note-rev1 → a2-note-rev2 → c-spec-v04 → a6b-note-rev1 → f-spec-v04) + launch the
  R5 build (code slot; brief ready) if z.ai < 50%.
- 13 Nov 23:46Z (GLM): z.ai reset (1%). One GLM slot was taken by the SFW session (`sfw-v4:p5-fix2`);
  the free slot went to the **R5 build** (`dramabox:r5-build`, R5a–R5f, cwd `.scratch/t031-r5`, base
  `104b26b`). Docs queue (a3-note-rev1 → a2-note-rev2 → c-spec-v04 → a6b-note-rev1 → f-spec-v04)
  waits for the next free slot. Codex idle (5h 63%, resets 00:39Z; nothing review-ready until R5 or a
  revision lands).
- 14 Nov 01:08Z (GLM): SFW's p5-fix2 ended → slot went to **a3-note-rev1** (docs queue resumes).
  Running: r5-build (81m, R5a) + a3-note-rev1. Docs queue next: a2-note-rev2 → c-spec-v04 →
  a6b-note-rev1 → f-spec-v04. Codex idle (week 23%, nothing review-ready).
- 14 Nov 01:20Z (GLM): **A3 note v1.1 committed** (10/10 round-1 rulings applied; integration
  points cross-checked against the A0-D fix tree; A-T8/A-T12a/A-T18 strengthened). Launched:
  `a2-note-rev2` (docs) and **A3 Codex round 2** (`a3-note-r2`, final A3 round). Running: r5-build +
  a2-note-rev2 + a3-note-r2. Docs queue next: c-spec-v04 → a6b-note-rev1 → f-spec-v04.
- 14 Nov 01:28Z (GLM): **A3 round 2 = REWORK** (N3R2-1..4 BLOCKING — recovery reachability and the
  paid-op lock order among them; N3R2-5..7 SHOULD-FIX). Rule 7 → all 7 ACCEPTED, applied as **v1.2**
  (brief `a3-note-rev2-brief.md`, queued), **no round 3**; Opus decides Monday (queued). Running:
  r5-build + a2-note-rev2; Codex idle. Docs queue: c-spec-v04 → a6b-note-rev1 → f-spec-v04 → a3-note-rev2.
- 14 Nov 01:33Z (GLM): **A2 note v1.2 committed** (`8bb2089`; all 10 round-2 rulings applied, none
  BLOCKED — barrier tests now rendezvous-safe, per-category delta validation, unfinished-residual
  arithmetic pinned). Launched `c-spec-v04` (docs). Running: r5-build + c-spec-v04. Docs queue next:
  a6b-note-rev1 → f-spec-v04 → a3-note-rev2. Codex idle.
- 14 Nov 01:52Z (GLM): **phase C v0.4 committed** (`deb850c`, 871 lines, 7/7 round-2 rulings,
  none BLOCKED — C's spec chain complete pending Monday's Opus call). Launched `a6b-note-rev1` (docs).
  Running: r5-build + a6b-note-rev1. Docs queue next: f-spec-v04 → a3-note-rev2. Codex idle.
- 14 Nov 01:55Z (GLM): **A6b note v1.1 committed** (`8cd4453`, 589 lines, none BLOCKED). The job
  flagged that the critique carried a 12th finding (N6-12, pure A-T14 test-plan expansion) with no
  ruling row — it applied it as the direct test obligation of the accepted findings; **GLM ratifies
  that application** (strengthens only; Opus can strike §9's additions Monday with a two-line revert).
  Launched `f-spec-v04` (docs). Running: r5-build + f-spec-v04. Docs queue next: a3-note-rev2 (last).
- 14 Nov 02:07Z (GLM): **A6b round 2 = REWORK** (7/12 closed; N6R2-1/2 BLOCKING recovery gaps,
  N6R2-3..5 SHOULD-FIX). Rule 7 → all 5 ACCEPTED, applied as **v1.2** (brief `a6b-note-rev2-brief.md`,
  queued last), **no round 3**; Opus decides Monday (queued). Running: r5-build + f-spec-v04; Codex
  idle. Docs queue: a3-note-rev2 → a6b-note-rev2.
- 14 Nov 02:12Z (GLM): **phase F v0.4 committed** (`2a0b01c`, 1100 lines, 7/7 round-2 rulings,
  none BLOCKED — F's spec chain complete pending Monday's Opus call). Launched `a3-note-rev2` (docs).
  Running: r5-build + a3-note-rev2. Docs queue last: a6b-note-rev2. Codex idle.
- 14 Nov 07:40Z (GLM, operator-observed gap): both 02:19Z exit-75s (r5-build quota-hit at 2h33m,
  a3-note-rev2 at 8m) went unhandled — the session was dormant and the retry at the ~05:14Z z.ai reset
  never fired. **~2h20m of open quota lost; cause noted, fix: every tick now always re-arms a wakeup,
  and exit-75 handling schedules the retry explicitly.** Recovery done: A3 v1.2 edit was complete
  (killed between edit and commit) → committed by orchestrator `43806c8`; **r5-build relaunched**
  (resumes: R5b+R5c committed at `b6d3b48`; R5a image rebuild was disk-blocked, 6G free now);
  **a6b-note-rev2 launched** (last docs job). z.ai 1%, Codex 0%/25%.
- 14 Nov 08:1?Z (GLM): **A6b v1.2 committed** (`9f21c8b`, 664 lines — the docs queue is EMPTY;
  all six two-round chains at final weekend state: B v0.6, C v0.4, F v0.4, A2 v1.2, A3 v1.2, A6b v1.2).
  **Phase E fact-map swarm launched** (`e-factmap`; Q7 order C→F→**E**→G→D). Running: r5-build +
  e-factmap (swarm). E spec draft follows the fact map; G after; D waits on R5's real run.
- 14 Nov 07:55Z (GLM, operator directives): (1) **O-8 APPROVED as recommended** (YT caption tracks
  post-publish; TT/FB Thai-only; per-destination flip after T032) — binding text to be written into
  phase-F-spec §1.9, F5 unblocked. (2) **Rule-7 waiver granted by operator**: round-3 verifications
  approved for C, B (running), then A6b, A3, A2 as Codex slots free; F stays deferred per plan.
  (3) **A-track fixes approved** (A0-D fix round 2, A0-R1 fix round, A1 note revision) — queued.
  (4) **NEW OPERATOR QUOTA RULE (overrides rule 3's 2-job allowance): one GLM-5.3 build at a time**
  — no second GLM-5.3 build until the current one ends (avoid mid-build quota kills like R5's 2h33m
  cut). Swarms (1/3 cost) and Codex jobs unaffected. Launched: phase-c-r3 + phase-b-r3 (Codex 2/2);
  r5-build holds the single GLM build slot; e-factmap swarm running.
- 14 Nov 07:56Z (GLM): **ROUND-3 RESULTS**: **phase B APPROVE** (5/5 closed, no new findings)
  → B spec v0.6 ACCEPTED; B1/B5 design notes become ready work. **phase C APPROVE-WITH-CHANGES**
  (6/7 closed, PC5-2 partial resolved by PC6-1 clarification — applied by orchestrator as v0.4.1)
  → C spec ACCEPTED. `a6b-note-r3` launched (Codex 1/2). Running: r5-build (GLM, sole build slot)
  + e-factmap (swarm). Queued: A3 r3, A2 r3 (Codex as slots free); a0d-fix2 (brief ready, launches
  when r5-build ends — one-build rule); then A1 note revision, A0-R1 fix.
- 14 Nov 07:59Z (GLM): **A6b r3 = APPROVE** (both blocking recovery gaps closed) ↓ A6b note
  v1.2 ACCEPTED. `a3-note-r3` launched (Codex 1/2). Accepted so far: **B v0.6, C v0.4.1, A6b v1.2**.
  Pending: A3 r3 (running), A2 r3 (queued); a0d-fix2 waits for r5-build (one-build rule).
- 14 Nov 08:03Z (GLM): **e-factmap done and verified** (128 lines, 63 citations, 9 NOT FOUNDs —
  incl. loudness/cue-sharing/derivative gaps the spec will define). Phase E spec brief written
  (`phase-e-spec-brief.md`) — **launch held** per the one-GLM-job rule (r5-build holds the slot);
  it queues behind a0d-fix2 / between builds. Running: r5-build + a3-note-r3.
- 14 Nov 08:06Z (GLM): **A3 r3 = REWORK** (2 blockers; "rulings only partly integrated" — confirms
  the quota-killed round-2 apply was incomplete; the orchestrator's rescue-commit of an unverified
  edit is the root cause, noted for Monday). **A3 PARKED for Opus** per the agreed rule.
  `a2-note-r3` launched (last r3). Accepted: B, C, A6b. Running: r5-build + a2-note-r3.
- 14 Nov 08:09Z (GLM): **A2 r3 = REWORK** (5/10 closed; lock-cycle items persist as predicted).
  **A2 PARKED for Opus.** ROUND-3 SWEEP COMPLETE — final: **B APPROVED, C APPROVED (v0.4.1),
  A6b APPROVED; A2 + A3 parked for Opus; F deferred** (per operator-approved plan). Codex queue empty.
  GLM runway: r5-build (running) → a0d-fix2 → A1 note revision → A0-R1 fix → E spec draft.
- 14 Nov 08:15Z (GLM, operator-approved): **A2/A3 fix + one R4 each** authorized; queue reordered:
  on r5-build exit → a3-note-rev3 (docs) → a2-note-rev3 (docs) → a0d-fix2 (code; both R4 critiques
  run on Codex in parallel) → A1 revision → A0-R1 fix → E spec draft → G fact map/draft → F1/F2/F4/
  F7/F8 notes. D stays last (needs E/G + R5 real results). Briefs `a3-note-rev3-brief.md` +
  `a2-note-rev3-brief.md` written, ready to fire.
- 14 Nov 08:22Z (GLM, operator): **A1-note R3 waiver logged** (revision brief
  `a1-note-rev3-brief.md` written — folds the never-applied round-2 findings N1R-1..12; A1's R3
  verification follows, then its build can start once A0-D is accepted). Phase A day-plan on record:
  r5 → A3/A2 docs → a0d-fix2 → A0-D R3+gate → A1 build (evening). Running: r5-build.
- 14 Nov 08:24Z (GLM, operator directive — fill the z.ai window): 2-job allowance restored until
  the 10:14Z reset; **no new GLM job after ~09:30** (mid-build kill guard). Launched: a3-note-rev3
  (docs, beside r5-build) + g-factmap swarm. Queue in the window: A2-rev3 on A3's exit, A1-rev3 if it
  fits before ~09:30; A3/A2 R4 critiques go to Codex as they land. E-spec draft opens the NEXT window
  (10:14Z) first, G-spec draft behind it.
- 14 Nov 08:33Z (GLM): **A3 v1.3 committed by its own job** (`68f906b` — the completion pass closed
  both round-3 blockers, verified lock rows against the real provider_ops sites; no BLOCKED items).
  Launched: `a2-note-rev3` (GLM slot) + **A3 R4** (`a3-note-r4`, Codex). Running: r5-build +
  a2-note-rev3 + g-factmap (swarm) + a3-note-r4. A1-rev3 next if a slot frees before ~09:30.
- 14 Nov 08:42Z (GLM): **A3 R4 = REWORK by ONE blocker + 1 SF** ("lock-order correction complete;
  recovery discovery needs one correction"). Both applied by the orchestrator (independent discovery
  + separate completion predicates; paid rearm NOT_FOUND-only). A3 now **corrected, awaiting final
  verify** — a 5th Codex round needs the operator's nod (the authorization was "one last R4").
  Running: r5-build + a2-note-rev3 + g-factmap.
- 14 Nov 08:48Z (GLM): **A2 v1.3 committed** (`9d0af9c`, all five round-3 residuals closed, none
  BLOCKED). Launched: **A2 R4** (Codex) + **a1-note-rev3** (GLM slot, fits before the 09:30 cutoff).
  Running: r5-build + a1-note-rev3 + g-factmap (swarm) + a2-note-r4. Window nearly fully used;
  no further GLM launches this window.
- 14 Nov 08:48Z (GLM): **g-factmap done** (142 lines, 12 NOT FOUNDs — live scaffolding gaps the G spec will define). Q7 status: C accepted, F final,
  E fact map done (draft queued for next window), G fact map done (spec draft behind E's).
  Running: r5-build + a1-note-rev3 + a2-note-r4.
- 14 Nov 08:55Z (GLM): **A2 R4 = REWORK** (4/5 residuals closed, but the revised lock table
  introduced N2R4-1/2 BLOCKING + N2R4-3 SF — each fold regresses elsewhere). **A2 PARKED for Opus**
  — no 5th round requested; this is the design-judgment loop predicted. Running: r5-build +
  a1-note-rev3. Codex idle (nothing review-ready until a1-rev3 or r5 lands).
- 14 Nov 08:59Z (GLM, operator): **A3 5th verify authorized and launched** (`a3-note-r5`, scoped to
  the two R4 applications only). Running: r5-build + a1-note-rev3 (finishing) + a3-note-r5 (Codex).
- 14 Nov 09:04Z (GLM): **A3 R5 = APPROVE** → **A3 note ACCEPTED** (v1.3 + R4 applies).
  **A1 v1.3 committed** (`b894bbe`) and its **R3 verification launched** (`a1-note-r3`, Codex 2/2).
  Accepted so far: **B, C, A6b, A3**. Pending: A1 R3 (running), A2 (Opus), r5-build (R5e/R5f).
  Running: r5-build + a1-note-r3 + a3-note-r5-done.
- 14 Nov 09:12Z (GLM): **A1 R3 = REWORK** (N1R3-1/2 BLOCKING — approval-identity NULL partition;
  Comfy submit ordering vs the real commit-before-HTTP code — + 4 SF; all with replacements; looks
  like integration slips, not the A2 loop). **Operator asked: one more A1 cycle (apply → R4)
  recommended** — it gates today's A1 build. Accepted: B, C, A6b, A3. Running: r5-build (R5e/R5f).
- 14 Nov 10:36Z (GLM): z.ai reset (1%, window to 15:14Z). r5-build still in its own full make check
  (integration phase; real processes verified — healthy, not stuck). **phase-e-spec draft launched**
  (docs, beside the one build). a0d-fix2 waits for r5's exit per the one-build rule. A1 one-more-cycle
  ask still open with the operator.
- 14 Nov 10:51Z (GLM): **phase E spec v0.1 drafted** (546 lines; committed by orchestrator — the
  docs-job pattern has no self-commit for first drafts). **E Goldfish launched** (cwd `phase-e-review/`,
  ~40 min). Running: r5-build (make check) + phase-e-goldfish. Q7 drafting order C→F→**E**✓→G→D.
- 14 Nov 11:1?Z (GLM): **R5 BUILD COMPLETE** — `R5: ALL PACKAGES DONE` at `6bcdbfa` (R5a–R5f;
  base repairs red-first; make check green 275). **RR-T3 image rebuild disk-blocked** (needs ≥12GiB,
  5.5G free; refused safely, no push). Launched: **R5 Codex review** (`r5-review`, full range
  `104b26b..6bcdbfa`) + **a0d-fix2** (build slot) + GLM's own two verification suites (chained).
  Full gate in a pinned checkout follows the verification. Running: a0d-fix2 + phase-e-goldfish +
  r5-review (Codex 1/2).
- 14 Nov 11:14Z (GLM): first verification attempt used wrong suite paths (`tests/*/t031` —
  "no tests ran"); corrected to the real files (`tests/unit/pipeline/test_t031_r5a_flag.py`,
  `rendering/test_t031_r5b_boot.py`, `pipeline/test_t031_r5d_prepare_run.py`,
  `pipeline/test_t031_r5f_billing_verify.py`) and re-running.
- 14 Nov 11:09Z (GLM): **R5 acceptance step 1 GREEN by GLM's own runs** (15 + 8 passed across
  r5a-flag/r5b-boot + r5d-prepare/r5f-billing — matches claims). **Full gate running** at pinned
  `6bcdbfa` (`t031-gate-r5` checkout, unit `dramabox-t031r5-gate`). R5 now waits on the Codex review
  (running) + gate. Running: a0d-fix2 + phase-e-goldfish + r5-review + the gate.
- 14 Nov 11:2?Z (GLM): **R5 review round 1 = FIX-REQUIRED** (R5V-1..4 BLOCKING — resume boot
  timing, +3 per report; R5V-5..10 SF). All 10 ACCEPTED (`r5-review-rulings.md`); fix brief
  `r5-fix1-brief.md` written — **launches when a GLM build slot frees** (a0d-fix2 holds it; one-build
  rule). Running: a0d-fix2 + phase-e-goldfish + the t031 gate.
- 14 Nov 11:2?Z (GLM): **E Goldfish done and ruled** (1 Blocker / 21 Major / 43 Nit — all ACCEPTED;
  B-1 takes the Stage-8 second-key arm: mix digest as replay key, EDL hash pure). `e-spec-v02`
  apply job launched (docs, beside the one build). Running: a0d-fix2 + e-spec-v02 + the t031 gate.
- 14 Nov 12:02Z (GLM): **t031 gate run 1 at `6bcdbfa` = RED on resources, not code**: 264 passed
  + 11 setup errors, all one session-scoped pilot fixture — `edit.variants_and_hooks: ffmpeg failed:`
  with EMPTY detail while disk=4.3G / mem=1.2GB free and a0d-fix2's scopes ran concurrently. The
  builder's identical make check passed 275 green solo. **Gate reruns SOLO after a0d-fix2 exits**
  (receipts kept). Disk trend noted: 6.0G→4.3G today — the RR-T3 image rebuild (12G) is further away,
  not closer.
- 14 Nov 12:08Z (GLM): **phase E v0.2 committed** (`c04366f`, 653 lines, 65/65 applied, none
  BLOCKED). **E Codex critique round 1 launched** (`phase-e-critique`). Running: a0d-fix2 (build) +
  phase-e-critique (Codex 1/2). Queue: t031 solo gate rerun + r5-fix1 after a0d-fix2; A1 one-more-cycle
  ask still open.
- 14 Nov 12:2?Z (GLM): **E critique round 1 = REWORK** (7 BLOCKING + 6 SF; second-key design
  blessed in principle, persistence/job contracts insufficient). All 13 ACCEPTED
  (`phase-e-critique-rulings.md`); **e-spec-v03 apply running** (docs, beside the one build).
  Running: a0d-fix2 + e-spec-v03.
- 14 Nov 12:25Z (GLM): **phase E v0.3 committed** (`8746297`, 784 lines, 13/13 applied, none
  BLOCKED). **E round-2 critique launched** (`phase-e-recritique`, scoped to PE-1..13). Running:
  a0d-fix2 + phase-e-recritique.
- 14 Nov 12:36Z (GLM): **E round 2 = REWORK (close)**: 9/13 closed; PE5-1/2 BLOCKING + PE5-3/4 SF.
  All 4 ACCEPTED → **e-spec-v04 apply running**; R3 verify follows under the standing waiver pattern
  (veto-able). Running: a0d-fix2 (regression sweep) + e-spec-v04.
- 14 Nov 12:39Z (GLM): **phase E v0.4 committed** (`3be36af`, 827 lines, 4/4 round-2 rulings, none
  BLOCKED). **E R3 verification launched** (`phase-e-r3`, scoped to PE5-1..4). Running: a0d-fix2 +
  phase-e-r3.
- 14 Nov 12:4?Z (GLM): **E R3 = APPROVE** → **phase E spec v0.4 ACCEPTED**. Phase-family specs
  now: **B, C, E, A6b, A3 accepted** · A2 parked (Opus lock-table) · A1 awaiting the operator's
  one-more-cycle call · F deferred · G fact map done (spec draft next, docs slot) · D last.
  Running: a0d-fix2 (regression sweep). Next: G spec draft beside the build; on a0d-fix2 exit → solo
  t031 gate + a0d-fix2 R3 + gate; r5-fix1 after.
- 14 Nov 12:52Z (GLM): **A0-D FIX2 DONE** — all ten AD5 findings addressed at `b84a397` (4 commits;
  AD5-1's producer-vs-admission test included). **R3 review launched** (`a0d-review-r3`) + GLM
  verification suites running. Gate at `b84a397` runs SOLO after verification (lesson from the
  resource-starved t031 gate run); **r5-fix1 held until the a0d gate finishes** to avoid gate+build
  contention. E R3 APPROVE recorded earlier (5 chains accepted).
- 14 Nov 12:43Z (GLM): **phase G spec draft launched** (`phase-g-spec`, docs slot — Q7's last
  draft before D). Running: a0d-review-r3 (Codex) + phase-g-spec + GLM fix2 verification (suites).
  The a0d gate at `b84a397` launches when the verification returns; r5-fix1 held behind the gate.
- 14 Nov 12:44Z (GLM): **A0-D fix2 acceptance step 1 GREEN** — both suites by GLM's own run:
  161 passed (fix round added ~46 tests). **Full gate running SOLO at `b84a397`** (`a0d-gate3`
  checkout, unit `dramabox-a0d3-gate`; no build running beside it — r5-fix1 held). Running:
  a0d-review-r3 + phase-g-spec + the gate.
- 14 Nov 12:49Z (GLM): **A0-D R3 = FIX-REQUIRED, converging** (new findings 13→10→7; AD6-1..7:
  5 BLOCKING + 2 SF, all with Fix lines; AD6-1 = persist the frozen identity once). Fix3 brief
  written (`a0d-fix3-brief.md`) — **launches when the solo gate finishes** (no build beside a gate).
  Running: the a0d3 gate + phase-g-spec. r5-fix1 re-queues behind fix3 (A0-D is the critical path).
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
- A0-D: round-2 review FIX-REQUIRED after a full fix round (6/13 closed at `6974d5a`; AD-1 regressed
  — the gateway now demands `policy_identity` the step never sends, so normal calls fail admission;
  plus 6 more BLOCKING: exited-unit evidence, twin-validator divergence, cancellation adoption bypass,
  A0-R1 quota mapping, conflicting replays, requalification clearance). Rule 7 stopped it — no round 3
  this weekend. Monday: Opus re-reads `codex-review-a0d-r2.md` + the gate receipts and decides a fix
  round 2 (would be review round 3) vs re-scoping. The A0-R1 dependency in AD5-1/AD5-5 ties into the
  also-stopped A0-R1 item.
- Phase F spec: round 2 REWORK after 9/17 closed (4 BLOCKING remain: routed V3 lifecycle, carrier
  binding, reschedule/binding atomicity, rebinding vs SQL immutability). GLM applied all round-2
  rulings as v0.4, no round 3 (rule 7). Monday: Opus re-checks `phase-f-recritique-rulings.md`;
  accept v0.4 vs round 3.
- A3 note: round 2 REWORK (4 BLOCKING remain: recovery-path reachability vs the real jobs/states
  code, the paid-operation lock order, + 2 more per the report). GLM applied all round-2 rulings as
  v1.2, no round 3 (rule 7). Monday: Opus re-checks `a3-recritique-rulings.md`; accept v1.2 vs round 3.
- A6b note: round 2 REWORK after 7/12 closed (2 BLOCKING recovery gaps remain). GLM applied all
  round-2 rulings as v1.2, no round 3 (rule 7). Monday: Opus re-checks `a6b-recritique-rulings.md`.
- A3 note (Mon): round-3 REWORK confirmed the round-2 apply (quota-killed, orchestrator-committed)
  was partial. The note needs one careful completion pass over `codex-a3-note-recritique.md`
  N3R2-1..7 + the two round-3 blockers in `codex-a3-r3.md`, then verification. GLM did NOT rerun a
  4th review (rule: park after a failed r3).
- A2 note (Mon): round-3 REWORK, 5/10 closed — the billing lock-order design (N2R2-4's cycle) needs
  Opus's judgment, not another wording fold. Reports: `codex-a2-r3.md` + `codex-a2-note-recritique.md`.
- A2 note (Mon, updated): R4 closed 4/5 residuals but each lock-table fold introduces new blockers
  (R4: baseline capture rejects SEASON amendments; invoice verification omits 451047; Stage-2 order
  reversed). Needs Opus to design the lock table once, properly — not another wording round.
  Reports: `codex-a2-r4.md` (+ lineage).
- Disk for T031's image rebuild (RR-T3): the builder needs ≥12GiB free and the volume has 5.5G.
  GLM cannot delete anything (rule 1). Free ≥12GiB (or name what may go) and the rebuild + local
  verification resumes; the push + paid run remain yours regardless.
- Disk (updated): 4.3G free and falling (gate checkouts + basetemps today). Besides RR-T3's
  ≥12GiB, the solo gate rerun and further builds would benefit from a cleanup pass — operator call
  (GLM may not delete).
