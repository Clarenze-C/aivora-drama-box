**Verdict: REWORK.** The master-spec structure is appropriate, but calendar authority, voice intake, and acceptance ownership still need the edits below. This is the final critique round; the remaining decisions go to the operator.

Reviewed v0.2.4, the complete binding inputs, round-1 report, and relevant code in main `0851374` and T031 `bdf1e2b`. No files changed, tests run, or generation/publication effects initiated.

**1. Round-1 findings**

“CLOSED” means the master now fixes the contract and delegates implementation detail adequately. It does not establish implementation readiness.

| Finding | Status | Assessment / missing obligation |
|---|---|---|
| V3C-1 | CLOSED | §1 explicitly resolves subscription-first pilot precedence. |
| V3C-2 | CLOSED | Step 4 sits inside the season cap; additional allowance requires a decision. |
| V3C-3 | CLOSED | Initial 20–30 episodes, append-only extension, and season-2 reuse are retained. |
| V3C-4 | PARTIAL | Phase B must state: “Initial planning requires approved LOCK scope, never the STORY LOCK that approves its output.” |
| V3C-5 | CLOSED | Phase B owns normative schemas, compatibility, validators, and consumer migration. |
| V3C-6 | CLOSED | Season CAST LOCK and removal of V3 episode-one Gate-2 locking are explicit. |
| V3C-7 | PARTIAL | Phase A must preserve release progress during extension and scope waits to the affected track; V3R-5. |
| V3C-8 | CLOSED | Votes, dependent generation, derived acceptance, and reroll invalidation are distinguished. |
| V3C-9 | CLOSED | Durable units, bounded retries, unknown-outcome reconciliation, and retained exposure are explicit. |
| V3C-10 | CLOSED | Canonical setting, cross-episode wardrobe history, timing, and composition are assigned. |
| V3C-11 | CLOSED | Phase D owns the new binding schema, supported views/cardinalities, and compatible style media. |
| V3C-12 | CLOSED | Mandatory references cannot be dropped; over-budget shots block, split, or use qualified composites. |
| V3C-13 | CLOSED | One compiler, qualified frame counts, dialogue coverage, and total-duration validation are required. |
| V3C-14 | CLOSED | A production adapter distinct from the benchmark controller is explicitly required. |
| V3C-15 | CLOSED | Native audio, alignment, captions, trims, and derivatives are included. |
| V3C-16 | CLOSED | Original QA/assembly defects are addressed; new SUPPORTING coverage gap is V3R-4. |
| V3C-17 | CLOSED | Commercial detector weights, exact-image A40 qualification, deadlines, and metering are required. |
| V3C-18 | CLOSED | Superseded by operator-made Botnoi V4 uploads; new intake defects are V3R-1/2. |
| V3C-19 | CLOSED | Shared ARISA/Drama lock qualification precedes live image jobs. |
| V3C-20 | CLOSED | Drama-owned YuE2 generation, recovery, rights, inspection, and billing are explicit. |
| V3C-21 | CLOSED | A0 owns the durable versioned machine-result interface and accounting distinctions. |
| V3C-22 | CLOSED | §10.1 sufficiently fixes isolation and queue behavior at master level; qualification detail is V3R-10. |
| V3C-23 | CLOSED | Separate economic measures, representative planning, comparable workloads, and uncertainty are required. |
| V3C-24 | CLOSED | One TH post per destination and verified EN/ZH delivery are fixed; delivery mechanics belong to F. |
| V3C-25 | PARTIAL | Phase F must resolve calendar/content circularity and bind both approval dimensions; V3R-6. |
| V3C-26 | PARTIAL | Assign B the extension seam and F the analytics adapter, freshness/unknowns, and extension integration. |
| V3C-27 | PARTIAL | Assign A the shared amendment coordinator/fences and F the complete publication-race acceptance test; V3R-8. |
| V3C-28 | CLOSED | Episode context, navigation versus approval, waits, recovery, and operational screens are fixed. |
| V3C-29 | PARTIAL | E must bind date-bearing CTA dependencies; F must revalidate them at activation/rescheduling; V3R-6. |
| V3C-30 | PARTIAL | G must explicitly own completion and qualification of production composition and composed restore; V3R-8. |
| V3C-31 | CLOSED | Durable event creation and potentially duplicated external delivery are honestly distinguished. |
| V3C-32 | CLOSED | Disabled research is visibly partial acceptance, rather than silently complete. |
| V3C-33 | CLOSED | Rights provenance, generation-time entitlement, and output inspection are required. |
| V3C-34 | PARTIAL | Recover the referenced acceptance baseline and close ownership gaps; V3R-7/8. |

**2. New issues and replacement wording**

**V3R-1 — BLOCKING — §4.4: the manual-upload trust boundary is missing.**

Owner authentication does not make uploaded archives, filenames, or decoder inputs trustworthy. The new ZIP intake has no explicit containment or resource-bound obligation.

**Add:** “Phase C treats uploads as untrusted bytes. Upload commands require owner scope, CSRF, expected revision and idempotency. Files enter private quarantine. Bound request size, archive entries, expanded size, decoded audio and processing time. Reject traversal, absolute paths, links, duplicate slot assignments and unknown character/expression keys. Use server-generated storage paths and isolated bounded decoding. Only validated immutable assets can enter CAST review; failed imports cannot overwrite accepted assets.”

Phase C chooses the numerical limits and tests hostile archives, malformed media, oversized input, and stale/replayed uploads.

**V3R-2 — BLOCKING — §4.4: “WAV” and declared voice names do not establish usable, consistent reference assets.**

T031’s [input validator](/root/AIVORA/drama-box/.scratch/t031-fix3-worktree/microdrama/src/microdrama/rendering/pika_transport.py:114) requires nonempty **uncompressed PCM WAV**. That code does not prescribe an input sample rate or channel count. MP3 intake is compatible after conversion; arbitrary WAV encoding is insufficient.

Technical checks also do not establish Thai speech, the intended transcript/expression, one speaker, or actual V4 provenance. A matching typed name alone cannot establish the same source voice.

**Replace validation/consistency wording with:** “Phase C pins a versioned normalisation profile including PCM subtype, sample rate and channels, compatible with the qualified production binder. Only the resulting PCM WAV is registered for dispatch and must pass its byte validator. Record technical checks and automated or human assessment of Thai speech, transcript, single-speaker suitability, expression and consistency with the selected base voice. V4 origin and source-voice identity are operator attestations, separately labelled from machine validation. Changing the base voice invalidates its expression family. Addition, replacement or re-normalisation after CAST LOCK creates a new immutable version through §12.6. Botnoi rights use the accepted O-11 `OPERATOR_ATTESTED` basis.”

Retain both source and normalised hashes. Missing published Botnoi licence documentation must not reopen the resolved O-11 gate.

**V3R-3 — BLOCKING — §6: “dominant line” introduces an unapproved exception to emotion matching.**

One reference per speaker is compatible with the binder. Selecting one line’s emotion for other differently tagged lines does not preserve the stated per-line selection rule. “Dominant” is also undefined.

**Replace:** “Each speaker has one effective reference expression per shot. When that speaker’s lines require different expressions, directing splits or restructures the coverage at speech-safe boundaries. Resolve each speaker’s expression to exactly one CAST-locked variant and persist the selection. An explicitly unsupported emotion may use the recorded `neutral` fallback; a missing, corrupt or unapproved required variant blocks dispatch rather than silently invoking fallback.”

A dominant-expression exception requires an operator decision.

**V3R-4 — BLOCKING — §§4.2, 4.6, 6: SUPPORTING roles can escape the consistency contract.**

The cap includes SUPPORTING speakers, and the reference-budget rule correctly preserves recognisable SUPPORTING identities. However, face QA names only principals. Unrestricted demotion also conflicts with EXTRA’s “no voice/no continuity” package.

**Add:** “Phase B counts all distinct dialogue speakers, including off-screen speakers, toward five per episode; Phase D enforces two per shot. Tier overrides never waive speaker counting, locked V4 voice requirements or required identity coverage. Revalidate demands after every tier edit before STORY LOCK. Phase C freezes the resulting packages. Phase D applies identity QA to every recognisably framed locked character, including SUPPORTING roles, with explicit applicability and recorded human assessment where automation is unavailable.”

Keep the existing mandatory-reference block/split policy. Five episode speakers do **not** imply five speakers—or all their references—in one shot.

**V3R-5 — SHOULD-FIX — §2.2: EXTENDING is placed on the release track.**

An extension is planning activity. Replacing `RELEASING` with `EXTENDING` can accidentally suspend already approved daily releases.

**Replace:** “An extension has its own planning scope and STORY/CAST lifecycle. `EXTENDING` is an activity flag; the existing season release track remains `RELEASING` or `COMPLETE`. Waits and failures belong to their affected scope and track and do not suspend unrelated approved releases.”

Phase A owns this state contract; F consumes it.

**V3R-6 — BLOCKING — §§4.7, 4.9, 9: calendar approval is circular and lacks a complete authority binding.**

Editing needs an **approved** calendar for CTA content. LAUNCH needs five already approved episodes. Neither can complete first.

There is also a substantial compatibility change: existing [ReleaseSlotPlan](/root/AIVORA/drama-box/microdrama/src/microdrama/contracts/release.py:79) requires a schedule, and Gate-2 approval transitively binds that package. A date-free V3 manifest needs an explicitly owned migration.

**Replace the calendar/approval rule with:** “Propose a versioned calendar before editing and review. Date-bearing content records its dependency on that proposed revision. Gate 2 and TEASER approve content; LAUNCH binds the exact calendar revision, stable slot identities and current content-approval hashes. Initial activation requires the first five consecutive episodes and teaser to have current approvals. Later episodes bind their approved calendar slots at Gate 2. Dispatch requires both current content and calendar authority. Rescheduling rebuilds affected date-bearing content and requires renewed content approval before activation. Phase F defines V3 publication compatibility without reinterpreting historical dated approvals.”

**Also add:** “Episode 1 depends on verified teaser publication per destination. A late or failed teaser holds the affected premiere pending approved recovery/rescheduling.”

**V3R-7 — BLOCKING — repeated references to v0.1 have no resolvable source artifact.**

The master incorporates proposal fields, UI denominators, continuity, metadata, reuse details and **AT-1..17** by references to v0.1. No retained v0.1 artifact exists in the supplied folder, and the spec path has no Git history in the inspected checkout.

This is missing incorporated authority, rather than a demand to put phase schemas into the master.

**Replace those references with:** “Inherited obligations refer to the immutable, path-and-hash-pinned v0.1 baseline retained beside this master. Its acceptance definitions remain binding except where explicitly superseded here.”

Restore that artifact, or replace every incorporation with explicit current obligations—including AT-1..17—before phase builds.

**V3R-8 — BLOCKING — §§15–17: acceptance and cross-phase ownership remain incomplete.**

AT-20 is absent; AT-30 is assigned only “packs”; AT-14/17 have no owner. AT-25’s derivative coverage extends beyond D, while AT-32’s composed restore requires the completed production system. The unnumbered end-to-end acceptance also lacks an owner.

**Add:** “Each acceptance obligation has one accountable phase; contributing phases supply component evidence. A owns shared amendment coordination and revision fencing. F owns full amendment-versus-publication integration and analytics-backed extension. G completes and qualifies the production composition, composed restore and all-gate end-to-end acceptance. Apply the test ownership corrections below.”

Also resolve the foundation ordering:

**Add:** “A0 owns the shared GenerationUnit and UsageRecord backend contracts/persistence needed by LlmService; A extends their workers, enforcement and operator views.”

Otherwise A0 consumes foundations assigned to A while A depends on A0.

**V3R-9 — SHOULD-FIX — §§7, 18: define eligibility before choosing the cheaper reseller.**

Fal documents the requested v2 endpoint, a commercial-use label and a listed **$0.002/s** price. An equivalent OpenRouter SFX-v2 endpoint and price were not established in this review. That does not prove the route is unavailable. [Fal model and price](https://fal.ai/models/fal-ai/elevenlabs/sound-effects/v2), [API contract](https://fal.ai/models/fal-ai/elevenlabs/sound-effects/v2/api).

**Add:** “Phase C qualifies each reseller’s exact SFX model/endpoint, commercial basis, settings and billing units. Compare equivalent requests using current all-in bounded prices and reserve the maximum authorised charge. Unknown capability, terms or price makes a route ineligible, never zero-priced. Use the cheapest eligible route; block if none qualify. Persist the selected route and reconcile ambiguous submissions before switching resellers.”

No direct ElevenLabs paid plan is required by this design.

**V3R-10 — SHOULD-FIX — §10.1: require evidence that ai-route isolation is effective.**

The master’s isolation intent is sufficient. Current routing still [inherits most environment variables and installs a progress MCP](/root/.claude/scripts/ai_route.py:204); a separate working directory alone does not implement the promised boundary.

**Add to A0 acceptance:** “Inspect and test effective argv, environment and settings. Prove that inherited tools, MCP servers, plugins and hooks cannot execute; credentials follow an allowlist; unreadable quota refuses admission; cancellation/deadlines terminate descendants. Failure to establish the isolation profile disables the subscription adapter.”

These are phase-spec/test obligations, not a requirement that the adapter already exist.

**V3R-11 — SHOULD-FIX — §4.4: base-voice candidates became optional without an explicit waiver.**

The original workflow and R-4.6 require 2–3 voice candidates and a pick. The later decision changes their source and adds expression variants; it does not expressly waive candidate selection.

**Replace:** “Upload 2–3 V4 base-voice candidates reading the neutral script, pick one, then supply its required expression variants.”

Alternatively, the operator can record a dated decision allowing one supplied base voice. Expression variants should not silently substitute for candidate choice.

**V3R-12 — NIT — §1: the gate count is inconsistent.**

**Replace “Five operator gates” with:** “Five content gates, plus LAUNCH calendar approval.”

**3. Fidelity**

The latest decisions are otherwise reflected faithfully: manual Botnoi Web Studio V4 intake, no API expression dependency, one source voice per character, three character tiers, five episode speakers/two shot speakers, reseller SFX, connected Dramabox Bot with FILE credentials, and operator-attested Botnoi commercial basis.

The substantive fidelity exceptions are the **dominant-line emotion override** and the **optional base-voice candidate selection**. Tier overrides also need V3R-4’s protection against bypassing voice and continuity obligations.

The earlier ElevenLabs purchase requirement and API voice-source descriptions are historical, superseded inputs; they must not become implementation gates.

**4. Phase assignment**

**No: §15 does not yet give every obligation exactly one accountable phase.** Deferring detailed traces is appropriate; the omissions and misplaced acceptance ownership below still need correction.

| Acceptance obligation | Current assignment | Accountable owner after correction |
|---|---|---|
| AT-18: full planning before assets | B | B |
| AT-19: historical compatibility | B | B |
| AT-20: acceptance/persistence crash recovery | Missing | **A** |
| AT-21: concurrent caps/accounting | A | A |
| AT-22: parent reroll invalidation | C | C |
| AT-23: wardrobe history/boundaries | C | C |
| AT-24: mandatory references/media | D | D |
| AT-25: native binding **and all derivatives** | D | **E**, with D supplying binding evidence |
| AT-26: continuity findings/unknown coverage | D | D |
| AT-27: subscription adapter outcomes | A0 | A0, including V3R-10 |
| AT-28: shared image lock | C | C |
| AT-29: release simulation/recovery | F | F |
| AT-30: amendment/job/publication race | B, packs only | **F**, using A’s coordinator and other phases’ consumers |
| AT-31: extension during/after release | F | F |
| AT-32: composed restore and resumption | A | **G**, using A’s recovery mechanisms |

For AT-1..17, §15 omits **AT-14 and AT-17**. Recover their definitions under V3R-7 and assign their final acceptance to G. Preserve the other listed owners unless the recovered definitions expose a mismatch.

Explicitly assign these remaining obligations:

- **B:** initial planning authority and the locked extension seam.
- **F:** live analytics source integration, freshness/unknowns, and extension decision evidence.
- **G:** completed production factory, composed restore, all-gate end-to-end test, and final live qualification.
- **B/G:** B owns visibly disabled Mode A; G preserves the **partial** acceptance label until research qualifies.
- **G:** distinguish the four rendered pilot episodes from the five-episode production LAUNCH threshold.

The per-R-ID matrix can remain a phase-spec deliverable. Its combined ownership must be checked before acceptance so cross-cutting requirements cannot disappear between phases.

