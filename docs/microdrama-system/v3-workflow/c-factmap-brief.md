# Phase C fact map (GLM swarm): today's code for the character bible, picks, wardrobe, voices and CAST LOCK

Orchestrator: Opus, 13 Nov 2026. A phase C spec will be written from your facts. **Facts only:** no design and no
recommendations. **Read-only. Write no files.** Put the whole fact map in your **final message** (only the final
message is kept).

## Where

- Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4` (main checkout). Code `microdrama/src/microdrama/`
  (cite as `S/…`), migrations `microdrama/migrations/` (`M/…`), tests `microdrama/tests/` (`X/…`). Migrations 0026–0027
  are in `/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/migrations/`.
- Requirement context, skimmed and not summarised: `docs/microdrama-system/v3-workflow/SPEC-v3.md` §4.4 (step 4:
  character bible → CAST LOCK), §5–§7, §15.1 (phase C row: V3-AT-5, 6, 7, 15, 22, 23, 28, 33). Also skim
  `DECISIONS.md` "D2 revised again" (one neutral Botnoi voice per speaker) and Q8 (Nano Banana; one process at a time,
  shared with ARISA SFW).
- ARISA's Nano Banana usage, for the cross-system lock only: `/root/AIVORA/arisa/studio/sfw/providers/` and any lock or
  quota-guard code it uses. Read-only.

## Rules for every fact

- Cite `file:line` and quote the decisive line or signature (≤ 2 lines).
- If you searched and found nothing, write **NOT FOUND** and the search terms you used. Never guess.
- Keep the whole answer under about 350 lines. Use tables.
- Never print environment variables, `.env` files, keys or tokens.

## Facts needed

1. **References and identity lock today:**
   - the models, services and tables for character references, the identity lock (versions, `reference_lock_version`,
     provisional refs), and how a lock attaches to episodes;
   - **the known bug:** episodes created after episode 1 are not attached to the identity lock (R-12.1). Find where
     attachment happens and why later episodes miss it.
2. **Assets and provenance:**
   - the asset registry (kinds, states `ACCEPTED`/`LOCKED`, provenance enum values including `FAKE_SYNTHETIC`), content
     hashing, versioning;
   - any `ProvenanceRecord`, or NOT FOUND.
3. **Image generation adapters:** every image provider seam (fake and live), its config switch, and how a generated
   image becomes an asset. Is there any Nano Banana / Gemini / Vertex adapter in drama-box? Or NOT FOUND.
4. **Picks / variant selection:** anything resembling 2–3 candidate variants per item, votes, re-roll or lock
   (`S/editing/variants*` and similar), and its tables.
5. **Wardrobe and appearance:** outfits, appearance states, story days, props and locations: records and their links to
   shots and episodes today.
6. **Voices:** voice registry/records, Botnoi or other TTS adapters, the rights basis for voices, and how a voice
   reference reaches a render request.
7. **Rights registry** for references, voices and generated assets: route ids, evidence, territories, eligibility
   checks.
8. **Cross-system lock:**
   - how ARISA SFW guarantees one Nano Banana process at a time (file lock, advisory lock, container name, quota
     keeper);
   - whether drama-box has any equivalent, or NOT FOUND.
9. **Demand list hand-off:** what phase B's `SeasonDemandListV3` will feed (from `phase-B-spec.md` §4). Does today's
   code have any demand/cast-requirement structure?
10. **Gaps:** things phase C will need that do not exist at all.
