# Stage 5 — Initial Zoom Out Review

- **Target:** /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md (v0.3, full file, lines 1–857)
- **Reviewer:** egm-zoom-out (Skeptical Architect), standard: zoom-out-standard.md
- **Mode:** REVIEW, headless (uninterrupted preset)
- **Date:** 2026-11-11

---

# Zoom-Out Review: /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3.md (v0.3, lines 1-857)

Context sufficiency (Standard §0) passes: objective, non-goals, hard rules, input precedence, and the path-and-hash-pinned v0.1 baseline are present; I confirmed /root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/SPEC-v3-v0.1.md exists at the pinned path (sha256 not verifiable read-only, presence confirmed). Cross-references verified: §19 maps all V3C-1..34 and V3R-1..12 to sections that genuinely contain the promised content; the AT-1..17 ownership table in §15 is complete (AT-14/17 owned by G, closing V3R-8); §12.3 matches DECISIONS Q10 exactly; §6 implements the operator's recorded V3R-3 decision verbatim. No blockers.

## Findings

1. Major — §10.1 (LlmService), §4.4 (generation-unit contract), §15 phase A0 — new durable queue beside an existing one. The codebase already has a durable job queue: /root/AIVORA/drama-box/microdrama/src/microdrama/core/jobs.py (JobService: idempotent semantic-key enqueue, leased claims, typed outcomes Succeeded/WaitExternal/RetryLater/Failed/NeedsReconciliation, "Ambiguous external work is never blindly requeued"). The proposed LlmService durable queue and the GenerationUnit status set (queued/running/succeeded/retryable/unknown/failed, reconcile-before-resubmit, bounded retries, resume without regenerating successes) restate guarantees that table already provides almost name-for-name. The spec is explicit about reuse where it likes (contracts.providers.LLMProvider at providers.py:152, review/api.py gate rules, T031 primitives for the render adapter) but silent here, so A0 can build a parallel queue with its own recovery semantics. Fix: one master-level sentence binding LlmService/GenerationUnit persistence to the existing jobs table and its reconcile contract.

2. Major — §11 and §13 (UsageRecord) — second cost ledger beside the existing one. UsageReceipt already exists (/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/cost.py:194) and the receipt/cost ledger behind budget/reports.py already delivers per-episode receipt/category/amount/basis reporting and the hold-effect-record discipline of hard rule 1. §11 defines a new UsageRecord and phase A builds a Costs page over it without stating whether it extends the existing receipt ledger or sits beside it. Two accounting records for the same paid calls is exactly the double-counting hazard the spec itself warns against ("allocated, never double-counted"). Pin UsageRecord to the existing ledger as the single source, adding the new quota/exposure dimensions to it.

3. Major — §10.3, §4.4, §4.6 — new provider protocol names not mapped to existing protocols. GenerationProvider already models image and voice generation with submit/status/reconcile/fetch_output and a built-in reservation_id (/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/providers.py:188); ASRProvider and MediaReviewProvider exist in the same file. The spec introduces ImageGenProvider, SfxProvider, MusicProvider and ClipQaProvider as new surfaces without saying they implement the existing protocols. If intent (possibly loose naming), say so; otherwise phase C/D specs will duplicate submit/status/reconcile semantics a second time. One sentence at §10.3 fixes it.

4. Nit (YAGNI) — §10.1, §15 phase A0 — three LLM adapters built up front. A0 includes subscription/API/OpenAI-compatible adapters while O-5 says "Subscription for the pilot only" and §11's route comparison is conditional ("where LLM routes are compared"). The API and OpenAI-compatible adapters serve a post-pilot operator decision not yet made. Simpler sequencing: subscription adapter in A0; others when the post-PILOT-REPORT.md decision or a scheduled frozen-workload comparison needs them.

5. Nit (weeds) — §3.3 and §4.4 steps 3-4 — runbook/schema detail at master altitude: bot file paths, 0600, rotation instruction, chat-id file, "test message delivered"; zip naming convention (<character_id>__<expression>.wav); V4 tag example mappings. These belong in the phase A/C specs or the deployment runbook. The rest of the document holds altitude.

6. Nit — §14 — reuse/change map is a pointer to a stale table. v0.1 §14 predates the v0.3 changes (Botnoi manual intake replaced ElevenLabs voice design; SFX moved to resellers; LLM plumbing moved B→A0; two-track states). A master spec whose only reuse artifact points at a superseded table is how findings 1-3 happen. Also note F's "viewership windows with freshness and unknowns" can reuse the existing 24h/72h/7d analytics windows (/root/AIVORA/drama-box/microdrama/src/microdrama/analytics/snapshots.py) rather than a new window model.

## Verified clean (for trace)

- Explicit reuse claims accurate: LLMProvider (providers.py:152), review/api.py approval rules, assign_scene_wardrobes setting mismatch and outfit_for_scene_time (references/v2_planning.py:1043,1289), plan_reference_demands (1088), ReleaseSlotPlan requiring a schedule (contracts/release.py:79), identity-lock-at-episode-1, and the V1/V2 record split (EpisodePlan, EpisodePack, SeasonScope) all exist as described.
- OutboxEvent is genuinely new (no outbox anywhere in microdrama/); its deduplicated-creation/honest-duplicate-delivery contract is minimal and correct.
- No premature optimization: the durable queue is correctness-driven, A40 benchmarking and GPU metering are cost-driven qualifications, the scheduler singleton is a deployment necessity. EXTENDING as an activity flag is a simplification (V3R-5), not added machinery.
- Season-2 reuse, extension scope, teaser contract, five-gate structure are operator-mandated (R-12.5, R-3.7, R-10, DECISIONS D1), not speculative.

## Overall altitude assessment

This is a disciplined master spec that mostly earns its altitude: it fixes contracts, invariants and phase boundaries while genuinely delegating schemas, command tables and numeric limits to the phase specs, and every operator decision and both critique rounds are traceably resolved rather than argued away. Its one systematic weakness is asymmetric reuse discipline: for the story, review and render layers it names the exact existing components to reuse, but for its own new infrastructure layer — the LLM queue, the usage meter, the provider adapter surfaces — it invents names and contracts without checking them against the durable jobs table, the cost-receipt ledger and the provider protocols that already satisfy most of the stated requirements, which is the classic path to parallel infrastructure and the double accounting the spec elsewhere forbids. A short reuse paragraph covering findings 1-3, plus trimming the two runbook-flavored detail pockets, would bring the whole document up to the bar its own §1 hard rules set.
