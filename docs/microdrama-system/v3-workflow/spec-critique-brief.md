# Codex critique — Drama Box v3 SPEC (before any build)

Attack this spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md`.

Binding inputs (the spec must satisfy them):
- `DECISIONS.md`: the operator's own decisions;
- `REQUIREMENTS.md`: R-IDs.

Facts:
- `factmap.md`: the current code, WIRED/CALLABLE/ABSENT;
- `joey-digest.md`;
- `../T031-fix-round/pipeline-map.md`.

All are in the same folder. Code: `/root/AIVORA/drama-box` (branch `feat/microdrama-m0-m4`), plus the
T031 worktree `/root/AIVORA/drama-box/.scratch/t031-fix3-worktree` for the render path.

The operator's explicit fear is **"speccing the wrong thing"**. Completeness and fidelity to their
decisions come first.

## Answer

1. **Fidelity.** Does any spec item contradict DECISIONS.md, or silently drop or reinterpret an operator
   decision? Quote both texts. Check especially:
   - the 10 steps and their order;
   - the STORY LOCK and CAST LOCK;
   - the picks (2–3 variants, SFW style);
   - voices: ElevenLabs/Chatterbox sample → Pika voice reference;
   - metadata drafted before Gate 2;
   - the stepper;
   - dramabox.aivora.agency;
   - 2-minute episodes, 20–30 of them, daily, extendable;
   - TH/EN/ZH captions;
   - YouTube Shorts, TikTok and Facebook;
   - the dedicated bot;
   - Nano Banana Pro;
   - YuE2 + ElevenLabs SFX v2;
   - the $10 cap;
   - recap + CTA;
   - **subscription-first LLM measurement**.
2. **Completeness.**
   - Is every R-ID covered with enough precision for a builder?
   - What does a real 20–30 episode Thai microdrama production need that is missing?
   - Think through one full season, day by day, from idea to episode 30 published and extended. Name
     every gap: data, UI, failure handling, operator action, provider behaviour.
3. **Feasibility against the code.** For each "wire up" and "change" item in §14, is the spec's claim
   about the current code correct (check factmap and the code)? Is anything much harder than it
   implies? Look in particular at:
   - unifying `EpisodePackV3` (V1 + V2);
   - removing the T039 map rule;
   - the shot resolver multi-view + timed outfit;
   - `plan_master` native audio;
   - CAST LOCK replacing the episode-1 identity lock;
   - the scheduler in compose.
4. **Provider and cost realism.**
   - The `dramabox-llm` ai-route role with `claude -p` JSON usage / `total_cost_usd` and quota deltas:
     is the measurement method sound?
   - Can a server pipeline call it safely? Concurrency, latency, pace refusal.
   - ElevenLabs Voice Design + voice slots + Thai.
   - The Nano Banana shared-quota lock with ARISA.
   - On-pod clip QA (Whisper + face embedding) cost and feasibility on the A40 alongside the render.
   - YuE2 on RunPod.
   - Is the per-episode cost meter enough for the operator's decision (subscription vs Max vs API vs a
     cheaper model)?
5. **Failure modes:** partial step-4 failures; quota refusal mid-episode; NB/ElevenLabs outage; a
   rejected Gate 2 near its air date; the buffer running dry; extension after cast changes; amend
   cascades.
6. **Tests:** are V3-AT-1..17 sufficient? Name the missing tests that prove an invariant.
7. **UI:** does §3 actually give the operator the checkout stepper, per-step progress bars, and clear
   Next/Approve per step? What screens or states are missing?

## Output

- Read-only; no writes. Put the full report in your final message, at most about 300 lines.
- Issues use IDs `V3C-1`…, with severity **BLOCKING** (the spec must change before the build) /
  **SHOULD-FIX** / **NIT**, the section, the problem and **replacement wording**.
- End with a verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
