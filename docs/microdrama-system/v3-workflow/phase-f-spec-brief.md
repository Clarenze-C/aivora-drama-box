# Phase F spec draft (GLM, docs only): metadata + Gate 2 + teaser + release calendar, slots and amendment integration

Orchestrator: GLM (weekend runbook), 13 Nov 2026. **Write one file:**
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md`, **v0.1 DRAFT**. No code, no other
file. It will go through Goldfish and then a Codex critique, so make every claim checkable. If
`phase-F-spec.md` already exists, you are resuming: continue it.

## Binding inputs (read fully)

- `SPEC-v3.md` **v0.4.6**: §4.8 (step 8: metadata and thumbnail drafts), §4.9 (step 9: Gate 2), §4.10
  (step 10: teaser), §9.1 (slot matrix), §9.2 (calendar and authority), §9.3 (dependencies and failures),
  §9.4 (throughput SLO), §12.6 (amendment: phase A coordinator, **phase F integration**), §15.1 phase F
  row (V3-AT-11, 12, 29, 30, 31 and their definitions), §15.2 (the R-IDs phase F owns).
- `DECISIONS.md`: V3C-26 (extension: decision and integration in phase F), O-8 (EN/ZH caption delivery on
  TikTok/Facebook — **the operator decides in phase F; do not decide it, propose), N11 (corrective
  community post), N35, and any T032 rows (platform qualification; unsupported capabilities hold slots).
- `f-factmap.md` (today's code; your source of facts, cite it as `FM §n`). Spot-check any fact you rely
  on in the code (`microdrama/src/microdrama/`, read-only). Note: `M/` ends at 0025 in the main checkout;
  0026–0027 exist only under `.scratch/a0d-gate/` — use symbolic migration names `F-1…` (numbers come
  later, after A).
- Contracts you build on, and must not contradict:
  - `phase-A-spec.md` v0.3 (gates, decision transaction, budgets, fence, command table; §12.6 makes A
    the amendment coordinator);
  - `phase-B-spec.md` (season structures, the demand list that eventually feeds calendars);
  - `phase-A0-spec.md` v0.4 (`LlmStep`) — only if metadata drafting uses an LLM step;
  - today's publishing contracts: `S/contracts/release.py` (`PostMetadata`), `S/contracts/v2.py`
    (`ApprovedSlotMetadata`, `ApprovedMetadataPolicy`), `M/0005`, `M/0021` (per FM §1–§2).
- Style and structure model: `phase-B-spec.md` / `phase-C-spec.md`. Same section order (scope, binding
  decisions, records, steps, jobs/fence/waits, UI, build packages, acceptance, open questions,
  requirement trace).

## What the spec must decide

1. **Records:** V3 metadata draft (prefill → edit → seal), thumbnail candidates + pick, the teaser and
   its gate, the versioned release calendar, slot identities per destination, per-slot publication state
   (incl. PARTIAL/HELD and proven-absence re-arm), the LAUNCH decision, amendment/extension rows for
   V3C-26. Reuse today's `metadata_versions`/`platform_posts`/`approval_events` machinery where it fits
   (FM §1–§2); name every new table symbolically (`F-1…`).
2. **Metadata and thumbnails (V3-AT-11):** drafts prefill Gate 2; the sealed manifest equals the edited
   drafts; a thumbnail must be picked before Approve. Today no thumbnail pick exists (FM §1) — define it
   (2–3 candidates, votes start no work, pick before seal; same pick pattern as phase C).
3. **Gate 2 in V3:** through phase A's decision transaction (stale hash refused; Revise regenerates only
   noted units). Keep the V2 manifest binding and caption-alignment guard semantics (FM §2); state
   exactly what carries over, what changes, and how V1/V2 history stays readable (no reinterpretation).
4. **Teaser (§4.10, V3-AT-12):** `PROMO_CUT` at premiere − 3 days; the teaser gates the premiere per
   destination on verified publication. Nothing exists today (FM §3) — define the records, the gate, the
   dependency, and the late/failed-teaser recovery (approved repair or reschedule).
5. **Calendar and authority (§9.2):** versioned calendar proposed before editing; daily 19:00
   Asia/Bangkok; LAUNCH binds calendar revision + slot identities + approval hashes; initial activation
   needs current approvals for the first five consecutive episodes and the teaser; later episodes bind
   their slot at Gate 2; dispatch requires content **and** calendar authority; rescheduling rebuilds
   date-bearing content, published media stays immutable, the reschedule screen lists inaccurate published
   CTAs for an operator-approved corrective post (N11). V3 publication compatibility without
   reinterpreting historical dated approvals (today `ReleaseSlotPlan` requires a schedule — FM §4).
6. **Slots and failures (§9.1, §9.3, V3-AT-29):** one full-episode post per destination (YT Shorts,
   TikTok, FB), TH; EN/ZH as caption tracks (O-8 stays an open question with a recommendation);
   readback-verified delivery; unsupported capabilities (e.g. FB AI disclosure until T032 qualifies)
   **hold** slots; predecessor dependencies per destination; rejected/unready episodes near air time →
   HELD with bot options (repair/swap/push, each approved); PARTIAL destination failure with
   per-destination retry/reconcile; a post is never duplicated — only proven absence re-arms a slot
   (FM §5–§6).
7. **Amendment vs job vs publication (V3C-26, V3-AT-30/31):** extension during release and after
   completion incl. changed cast; stale results and old approvals cannot release changed artifacts;
   published hashes and authority remain intact. Define the integration seam with phase A's coordinator
   role (§12.6) and the race fences (job completion, publication dispatch).
8. **Buffer rules (V3-AT-12, 29):** ≥5 approved episodes before a start date; teaser at premiere − 3 d;
   the 30-episode release simulation as an offline acceptance test covering: late teaser, rejected
   episode, zero buffer, partial destination failure, ambiguous publication.
9. **Throughput (§9.4):** the MA11 SLO surface — what is measured, where it is recorded, what the
   Costs/status pages show.
10. **Build packages `F1…` in order,** each with its acceptance rows. Name which need a design note
    critiqued before code (money, locks or migrations: yes).
11. **Open questions,** each with a recommendation. O-8 is the operator's decision — present the options
    and recommend one.

## Rules

- **Never contradict `SPEC-v3.md` or `DECISIONS.md`.** If they conflict with the code or with each other,
  record it as an open question; don't resolve it silently.
- Facts carry `file:line` or `FM §n`. Mark anything unverified as `UNVERIFIED`.
- Target about 450–650 lines.
- No deletion commands. Never print env vars, keys or tokens. No pushes, no merges.
- **Final message:** at most 15 lines summarising the decisions and listing the open questions, then the
  file path.
