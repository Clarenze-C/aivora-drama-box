# Fact map — Drama Box end-to-end automation for a full microdrama series (read-only)

The operator asked: "What is our step-by-step automation right now for a full microdrama
series?" Produce a **factual** map of the pipeline as it exists in code today, not as
intended. Report facts only; no design advice.

## Sources

- Main checkout `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4`. Python lives
  under `microdrama/src/microdrama/`.
- `/root/AIVORA/drama-box/docs/microdrama-system/SPEC.md`
- `/root/AIVORA/drama-box/docs/microdrama-system/task_breakdown.md`
- `/root/AIVORA/drama-box/docs/microdrama-system/task_status.csv`
- `/root/AIVORA/drama-box/docs/microdrama-system/HANDOFF.md`
- The T031 worktree `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree`, only for the
  render/benchmark stage.

## Produce

1. **The ordered stage list**, from series idea to published episodes and
   post-publication management. For each stage give:
   - its name;
   - the module/entry point (`file:function`, or the CLI command/worker);
   - its inputs and outputs (durable records or files);
   - who acts:
     - **AUTO** (worker/scheduler);
     - **HUMAN GATE** (an operator approval step, e.g. Gate 1/Gate 2: name it);
     - **HUMAN WORK** (the operator must make or upload something);
   - which model/provider it calls, if any, and whether that call is **live-qualified**
     or **OFFLINE_MOCK/stub only** today;
   - its task IDs from `task_status.csv` and their status.
2. **The character bible / casting stage specifically:**
   - how characters, outfits, sets and reference images are created, stored and
     approved;
   - whether any **voice/audio identity** step exists today. Quote it, or say plainly
     that none exists. Include the `VOICE` reference role, `ShotReferenceBinding`,
     and how T031 expects voice anchors.
3. **Script, shot planning and directing:**
   - how scripts, shot lists and prompts are produced;
   - which LLM is used, and where the prompt templates live (`file`);
   - any directing/cinematography rules (shot types, pacing, camera, lens) that exist in
     code or templates. Quote their location.
4. **Render → edit → captions → export → publish → analytics/management:** the actual
   automation and gates at each step, plus which steps are live today vs mock.
5. **What is NOT automated or NOT live yet,** as a short list, linked to T031–T035.

## Constraints and output

- Read-only. No writes, no network, no test suites.
- Put the full map in your final message, at most about 220 lines.
- Use tables where they fit. Cite `file:line` or `file:function` for every stage.
