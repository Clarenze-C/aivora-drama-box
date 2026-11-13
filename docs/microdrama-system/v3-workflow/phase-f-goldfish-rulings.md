# Phase F Goldfish rulings — GLM (13 Nov 2026)

Input: `phase-f-review/consolidated_review_report.md` (4 Blocker / 33 Major incl. 3 [format] / 36 Nit)
against `phase-F-spec.md` v0.1. Every ruling is a **GLM ruling, Opus re-check Mon**. Root architecture
blessed (Stage 8); no acceptance row weakened; no operator decision taken by GLM — O-8 stays the
operator's (CON-B3).

## Blockers

- **CON-B1 — ACCEPT (Stage-8 resolution).** Reschedule apply UPDATEs the date columns in place on V3
  rows locked in SCHEDULED (identity columns byte-identical, published rows immutable, past-`begin`
  settles per §8.5); §1.4's absolutist sentence and F-4's "set once" rewritten to match; §8.1/§8.5 agree
  on reachable states; new assertion in F-T3/F-T9 (two reschedules → still exactly one row per identity).
- **CON-B2 — ACCEPT option (a).** Synthetic carrier episode + season-scoped teaser release package ride
  the ordinary path (zero new machinery; no change to the shared V1/V2 table); corrective posts use the
  same carrier pattern with their own slot identity; teaser admission checks written; new acceptance test.
- **CON-B3 — ACCEPT, split.** GLM cannot take O-8. v0.2 states **F5 is conditionally blocked on the
  operator's O-8 ruling** and records the fully-specified recommendation (YT caption tracks now via
  `upload_captions`; TT/FB TH-only until T032 qualifies; per-destination flip) as recommendation only.
  F1–F4 may proceed. O-8 → OPERATOR QUEUE (already implied by O-F1; now explicit with F5 blocked on it).
- **CON-B4 — ACCEPT.** Re-map the §13 gate column: F3 gets its own drafts/thumbnails/staleness gate;
  reschedule-dependent assertions move to F7/F-T9 or split staged; seeding requirements stated for
  F-T2/F-T3.

## Majors

| ID | Ruling | Direction |
|---|---|---|
| CON-M1 | ACCEPT | Correct the false trigger-immutability premise; the update-dates alternative is adopted via CON-B1; alternatives paragraph added for §1.2. |
| CON-M2 | ACCEPT | §8.1 apply re-binds all not-yet-admitted identities; §7.1(3) = "bound by the latest binding authority (LAUNCH or extension approval) and equal to the current revision"; §8.4 assigns extension-identity allocation to the extension approval handler. |
| CON-M3 | ACCEPT | Metadata-delta Gate 2 re-approval is the stated default for unaired sealed episodes; policy-edit/N11 restricted to published slots; O-F10 updated. |
| CON-M4 | ACCEPT | Enumerate the `schedule_release` invariants admission replicates and the owning function; name the fork or expose a per-slot variant. |
| CON-M5 | ACCEPT | Short risks treatment for the four operational modes (w13 availability/catch-up, REFUSED alert growth bound, mid-RELEASING abort via A's cancel_season, lead-time vs predecessor verification). |
| CON-M6 | ACCEPT — extend C's engine | Thumbnail picks extend C's `cast_pick_items`/`cast_pick_votes` (pick_kind THUMBNAIL, episode/teaser scope, ASSET refs + `inspection_ref`); no parallel vote tables. Register the C-side delta in C's C-B1-style crossing register. |
| CON-M7 | ACCEPT | Teaser key art charged to SEASON_SETUP; §1.15 restated; `step_10` mapped in §10. |
| CON-M8 | ACCEPT | F-T5 → F-T8 at line 380. |
| CON-M9 | ACCEPT | Re-point the eight "§14 O-Fn" refs to §15. |
| CON-M10 | ACCEPT | Both "(F-2)" labels → F-1; qualify package refs ("package F2") at first use. |
| CON-M11 | ACCEPT | "SPEC §n" for master refs; doc-letter convention for siblings; fix the two wrong internal targets. |
| CON-M12 | ACCEPT | Prerequisites cite acceptance artifacts; F5 marked blocked-until-E-accepted; `S/editing` named as the `teaser_cut` reuse seam. |
| CON-M13 | ACCEPT | `CapabilityLimits` gains title/hashtag limit fields (added in F1/F2); effective cap = min(platform, contract); 200-vs-100 conflict resolved for the prefill lint. |
| CON-M14 | ACCEPT | Caption-route record gets a storage home (F-1 contract type) named in F1/F2 Builds; resolves with CON-B3's O-8 dependency. |
| CON-M15 | ACCEPT | Commit to `metadata_draft_versions` (decisive columns stated); the reuse option dropped (non-viable). |
| CON-M16 | ACCEPT | Add the close-out command (actor, prerequisites, effect) to §12. |
| CON-M17 | ACCEPT | Define CONTINUED vs RESUMED calendar modes before F1/F8. |
| CON-M18 | ACCEPT | Re-attribute Q6→DECISIONS.md; V3C-26/O-8/N35/N11→SPEC-v3 anchors. |
| CON-M19 | ACCEPT | Add the missing §16 trace rows (V3-AT-2 corrected or heading fixed; V3-AT-5, V3R-6, AR-4 rows; AR-4 provenance named). |
| CON-M20 | ACCEPT | One row per ID in §16. |
| CON-M21 | ACCEPT | §13 Builds cells: verb phrases, §-anchors, Create/Modify/Reuse markers; F2's mentions disambiguated. |
| CON-M22 | ACCEPT | §14 Proves cells in stimulus ⇒ expected form with units; seeded scenarios for F-T7/F-T9. |
| CON-M23..M30 | ACCEPT | "release admission" as the one name; §7.4 units split; §3.3 staleness referent = current calendar revision in force; "that" inserted; LAUNCH condition 5 rewritten as testable invariant + exception; horizon gets config name + default; `approved_episodes` aligned (per episode); "slot identity" vs "publish slot". |
| CON-M31 | ACCEPT `[format]` | Alternatives Considered per B §16 (the four single-path choices; may fold CON-M1's and CON-B2's option analyses in). |
| CON-M32 | ACCEPT `[format]` | Risks & Mitigations roll-up + security note for the three new operator surfaces (folds CON-M5). |
| CON-M33 | ACCEPT `[format]` | Problem statement added to §0. |

## Nits (grouped)

- **CON-N1..N8, N13..N20, N22..N29, N32..N36: ACCEPT** — mechanical sweep in v0.2 (naming, units,
  casing, pointers, table hygiene, register; N1 prefill lane verified; N6 `reschedule_calendar`
  defined; N8 the two new schedules added to §10; N14 CSRF; N31 w13b's calendar-trigger dependency on
  A6b stated with ordering after 19:00).
- **CON-N9: ACCEPT** — teaser key shape decided in v0.2 (nullable episode_id + explicit scope key on
  the draft/candidate tables).
- **CON-N10, N11, N21, N25: ACCEPT** — fence comparator defined (bound approval revision vs current
  release-track revision); the admitted-past-air-unverified state added to §7.4's derivation;
  "appends a vote; starts no work" phrasing; derivation inputs aligned (three, incl. admissions).
- **CON-N12: ACCEPT** — F-2 cell unpacked (schema, projection, UNIQUE, SUPERSEDED explained).
- **CON-N30: ACCEPT** — phase D's status stated in prerequisites (supplier).
- **CON-N3: ACCEPT** — derive rolling counters on read unless F-6 justifies storage (prefer derive).

## Apply

Fold into **phase-F-spec.md v0.2** (job `dramabox:f-spec-v02`, docs only, queued behind c-spec-v02 and
b-spec-v05): all four Blockers (B3 as "F5 conditionally blocked on O-8" — the operator decides), all 33
Majors, the grouped Nits. The C-side picks-engine delta (CON-M6) is recorded as a crossing-register entry
for phase C, not edited into phase-C-spec by this job.
