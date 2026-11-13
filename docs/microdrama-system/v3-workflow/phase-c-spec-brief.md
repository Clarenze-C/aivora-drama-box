# Phase C spec draft (GLM, docs only): character bible → picks → wardrobe → voices → CAST LOCK

Orchestrator: Opus, 13 Nov 2026. **Write one file:** `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-C-spec.md`,
**v0.1 DRAFT**. No code, no other file. It will go through Goldfish and then a Codex critique, so make every claim
checkable. If `phase-C-spec.md` already exists, you are resuming: continue it.

## Binding inputs (read fully)

- `SPEC-v3.md` **v0.4.6**: §4.4 (step 4), §5 (continuity), §6 (reference selection; voice and emotion, v0.4.5), §7
  (audio providers), §10.0, §15.1 phase C row (V3-AT-5, 6, 7, 15, 22, 23, 28, 33 and their definitions), §15.2 (the
  R-IDs phase C owns).
- `DECISIONS.md`:
  - Q8 (Nano Banana; one process at a time, shared with ARISA SFW);
  - "D2 revised", "D2 update", **"D2 revised again"** (one neutral Botnoi reference per speaker; the prompt carries
    emotion);
  - O-11 (Botnoi `OPERATOR_ATTESTED`);
  - the community-voice rule;
  - the Botnoi Studio archetypes.
- `c-factmap.md` (today's code; it is your source of facts, cite it as `FM §n`). Spot-check any fact you rely on in
  the code (`microdrama/src/microdrama/`, read-only).
- Contracts you build on, and must not contradict:
  - `phase-A-spec.md` v0.3 (gates, decision transaction, budgets, fence, command table);
  - `A1-design-note.md` v1.2;
  - `phase-A0-spec.md` v0.4 (`LlmStep`);
  - `phase-B-spec.md` **v0.3** (§4 `SeasonDemandListV3`, the hand-off into C; §2 records).
- Style and structure model: `phase-B-spec.md`. Use the same section order (scope, binding decisions, records, steps,
  jobs/fence/waits, UI, build packages, acceptance, open questions, requirement trace).

## What the spec must decide

1. **Records:**
   - pick candidates, votes, re-roll and lock;
   - the season-scoped CAST LOCK binding;
   - outfit, appearance state, prop and location coverage;
   - the voice reference: one neutral reference per speaker;
   - `ProvenanceRecord` (V3-AT-33);
   - the dependency edges for invalidation (V3-AT-22).

   Use symbolic migration names `C-1…` (numbers come later, after A and B).
2. **The R-12.1 fix:** a lock attaches to every episode, including those created later (V3-AT-6). Cite where
   attachment is missing today (FM §1).
3. **Pick flow:**
   - 2–3 candidates per item;
   - votes start no work;
   - Re-roll requeues one item;
   - Lock is refused until every required item is picked;
   - the lock hash covers every picked version (V3-AT-5).
4. **Wardrobe per story day,** including timed changes across episode boundaries (V3-AT-7, V3-AT-23). Use the unwired
   helpers FM §5/§10 found.
5. **Nano Banana:** an adapter seam, fake by default and live behind a per-provider switch.
   - **The cross-system single-process lock** interoperates with ARISA's lock (FM §8), crash-safe (V3-AT-15, V3-AT-28).
   - Cost metering and budget admission go through phase A's accounts. Nano Banana is a paid provider; the model on
     the shared Vertex project is `gemini-nano-banana-2.1`.
6. **Voices:**
   - a Botnoi catalogue from both sources (API importer and operator additions CSV);
   - shortlist and audition;
   - the operator's manual upload of one neutral clip per speaker;
   - normalisation;
   - the rights record;
   - quarantine of uploads (V3R-1).

   No per-emotion variants.
7. **Demand list → work:** how B's demand list becomes pick items, generation jobs and budget forecasts. Which
   `NOT_AVAILABLE` panels from B §4.3 C fills.
8. **Gate:** CAST LOCK through phase A's decision transaction. Stale hash refused; Revise regenerates only the noted
   units.
9. **Build packages** `C1…` in order, each with its acceptance rows. Name which ones need a design note critiqued before
   code (money, locks or migrations: yes).
10. **Open questions**, each with a recommendation.

## Rules

- **Never contradict `SPEC-v3.md` or `DECISIONS.md`.** If they conflict with the code or with each other, record it as
  an open question; don't resolve it silently.
- **Facts carry `file:line` or `FM §n`.** Mark anything unverified as `UNVERIFIED`.
- Target about 450–650 lines.
- No deletion commands. Never print env vars, keys or tokens.
- **Final message:** at most 15 lines summarising the decisions and listing the open questions, then the file path.
