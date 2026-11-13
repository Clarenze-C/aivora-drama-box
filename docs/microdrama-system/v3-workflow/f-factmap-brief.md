# Phase F fact map (GLM swarm): today's code for metadata, Gate 2, teaser, release calendar, slots and amendment integration

Orchestrator: GLM (weekend runbook), 13 Nov 2026. A phase F spec will be written from your facts. **Facts
only: no design and no recommendations. Read-only. Write no files.** Put the whole fact map in your
**final message** (only the final message is kept).

## Where

- Repo `/root/AIVORA/drama-box`, branch `feat/microdrama-m0-m4` (main checkout). Code
  `microdrama/src/microdrama/` (cite as `S/…`), migrations `microdrama/migrations/` (`M/…`), tests
  `microdrama/tests/` (`X/…`). Migrations 0026–0027 are in
  `/root/AIVORA/drama-box/.scratch/a0d-gate/microdrama/migrations/`.
- Requirement context, skimmed and not summarised: `docs/microdrama-system/v3-workflow/SPEC-v3.md` §4.8
  (metadata and thumbnail drafts), §4.9 (Gate 2), §4.10 (teaser), §9.1–§9.4 (slot matrix, calendar and
  authority, dependencies and failures, throughput SLO), §12.6 (amendment: phase A coordinator, phase F
  integration), §15.1 phase F row (V3-AT-11, 12, 29, 30, 31). Also `DECISIONS.md` rows on extension
  (V3C-26) and O-8 (EN/ZH caption delivery on TikTok/Facebook).

## Rules for every fact

- Cite `file:line` and quote the decisive line or signature (≤ 2 lines).
- If you searched and found nothing, write **NOT FOUND** and the search terms you used. Never guess.
- Keep the whole answer under about 350 lines. Use tables.
- Never print environment variables, `.env` files, keys or tokens.

## Facts needed

1. **Metadata and thumbnails today:** any episode metadata record/draft (title, description, hashtags,
   captions per language), where it is edited, and any thumbnail concept/pick. What exists vs NOT FOUND.
2. **Gate 2 today:** the current final approval gate before release — its records, its approver binding,
   what it approves (hashes? revisions?), and what happens on approve.
3. **Teaser:** any teaser/promo concept tied to a premiere date, or NOT FOUND.
4. **Release slots and calendar:** `ReleaseSlotPlan` and friends — records, the requirement that it needs a
   schedule, slot identities, per-destination slots (YouTube Shorts, TikTok, Facebook), how a date/schedule
   is stored and versioned, and how slots bind to episodes and approvals.
5. **Publication workers:** the M3 social wave — publishers per platform, execute_action seams, disclosure
   gates (IG/FB HELD states), readback verification, retry/reconcile, dedupe, and how a slot transitions
   to published/partial/held. Where per-destination failure is handled.
6. **Scheduler and outbox:** the in-app scheduler (n8n was dropped), outbox tables/consumers, how
   time-based dispatch is triggered, and how a held/failed slot retries.
7. **Amendment vs job vs publication race surfaces:** any existing locking/versioning that a V3C-26
   extension or a reschedule must respect: approval hashes, calendar revisions, published-media
   immutability, dependency recording on date-bearing content.
8. **Buffer/premiere rules:** anything resembling "teaser at premiere − 3 days", "episode 1 depends on
   verified teaser publication", "predecessor slot dependency", "5 approved episodes before start", or
   NOT FOUND.
9. **Caption tracks:** any caption/subtitle file handling per destination (upload vs burned-in), or NOT
   FOUND.
10. **Throughput:** the MA11 SLO surfaces — any existing throughput/rate tracking per platform, or NOT FOUND.
11. **Gaps:** things phase F will need that do not exist at all.
