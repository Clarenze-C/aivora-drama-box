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
| Q1 | **A0-D** (gateway, `LlmStep`, migration 0027) | Built: D1 `365bff9`, D2 `2352e73`, D3 `c25b527`, `A0-D: ALL PACKAGES DONE` (`a0d-build-REPORT.md`); worktree `.scratch/a0d-gateway`, branch `feat/a0d-gateway` from `0cda424`. **Full gate running** (unit `a0d-offline-gates`, receipts `.scratch/a0d-gate/.scratch/gate/`, started 02:45Z) | (1) read the gate receipts; (2) Codex **review** of `0cda424..c25b527` at xhigh. Brief: copy `codex-review-a0r1-brief.md` and adapt it to `phase-A0-spec.md` v0.4 §4–§5. It **must** verify A0S-1/A0S-2 (the auto-reconciler) explicitly. (3) FIX-REQUIRED → a GLM fix brief from the findings, then round 2. ACCEPT → STATE "accepted" (no merge) | Codex reset 10:30Z |
| Q2 | **T031 run-readiness (R5)** | Spec `../T031-run-readiness-spec.md` v0.1; Goldfish **started 03:12Z** at the operator's request (unit `t031-r5-goldfish`, ~40 min). Its reports land in its cwd, `.scratch/t031-fix3-worktree/goldfish/` (untracked: copy them to `docs/microdrama-system/T031-fix-round/r5-goldfish/`); the final message goes to `../T031-fix-round/r5-goldfish-final.md` | (1) resolve the Goldfish findings into v0.2 (skip if Opus did); (2) Codex **critique** (pattern `spec-critique-brief.md`; ask it to rule on §8 Q1, predicted schema vs a capture pod); (3) resolve, then GLM build R5a→R5e in worktree `.scratch/t031-r5` from `feat/t031-fix3` (tip `104b26b` or later); (4) Codex review; (5) gate. **The image rebuild is local only. No push, no paid run:** both wait for the operator | Goldfish; then Codex |
| Q3 | **A1** (discriminator, gates, decision transaction; migrations 0028–0031) | Note `A1-design-note.md` v1.2. Round 1 = `codex-a1-note-critique.md`. **Round 2 not yet run** | (1) Codex re-critique, round 2 (pattern `a1-note-critique-brief.md`, scoped to the round-1 findings); (2) ACCEPT/minor → write the A1 build brief from `phase-A-spec.md` §10 + the note, then GLM build on `feat/a0d-gateway` **after Q1 is accepted**, then review and gate; BLOCKING → OPERATOR QUEUE | Codex reset; Q1 accepted (for the build) |
| Q4 | **A2, A3, A6b design notes** | Drafted 12 Nov (`A2-`, `A3-`, `A6b-design-note.md`); never critiqued | Codex critique round 1 each (pattern `a1-note-critique-brief.md`) → rulings → GLM revises the note → round 2. Builds follow A1 in table order: A2 → A3 → A4/A5/A6a (no note) → A6b → A6c | Codex reset |
| Q5 | **Phase B spec** v0.3 | Draft (`phase-B-spec.md`; operator answered O-B1..6; one neutral voice per speaker). **Goldfish started 03:22Z by Opus** (unit `phase-b-goldfish`; reports in `phase-b-review/goldfish/`; final `phase-b-goldfish-final.md`) | Goldfish done → rulings → Codex critique round 1 (pattern `spec-critique-brief.md`) → B1 and B5 design notes | z.ai < 50% |
| Q6 | **A0-R1** (`dramabox-llm` ai-route role, `/root/.claude`) | Fix round 1 done (`a0r1-fix1-final.md`) | Codex re-review, round 2 (pattern `codex-review-a0r1-brief.md`, scoped to RR-1..15). **The merge into `/root/.claude` main waits for the operator**: a broken `ai-route` would stop every session | Codex reset |
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

## OPERATOR QUEUE (things only the operator can do; GLM appends)

- T031 R5, once accepted: push the rebuilt image; write the Comfy gateway token file (`read -rs`, 0600); capture an
  A40 quote; sign the authorization; run `benchmark execute --phase screen`. The orchestrator prepares all of it.
- A0-R1, on Codex ACCEPT: approve the merge into `/root/.claude` main (staging only `scripts/ai_route.py`,
  `models.json`, `scripts/tests/ai_route/`).
- A0-D, once accepted:
  - install the gateway's systemd unit, group 64010 and directories;
  - OK the live qualification (≤ 5 calls).
- Before go-live: rotate the Dramabox Bot token.
