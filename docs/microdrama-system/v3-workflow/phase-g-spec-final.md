Phase G spec drafted — one file, docs only, no code.

- **Shape:** 556 lines, v0.1 DRAFT in the accepted-chain style (C/E/F): scope → 14 binding decisions → records → seven topic sections → packages G1–G7 → acceptance → trace, open questions, risks, alternatives.
- **Records:** exactly one migration (`G-1`, the `v3_ops_documents` store) holding `PilotRunV3`, `LiveClaimV3`, `RestoreProofV3`, `ProductionCompositionV3`; everything else reuses existing tables — justified against the per-record-table and second-quota-table alternatives. Two contract crossings registered (GD1 schedule, GD2 jobless `track.wait_started`).
- **Key rulings:** off-pace reads as A0's admission (PACE_WEEK defers with week-reset retry; QUOTA_UNREADABLE pauses the route; one bot alert per pause episode; no-fallback is structural); the composed-restore proof restores an *unclean* world (in-flight op, CLAIMED intent, pending firing) and asserts zero duplicate effects with an honest at-least-once notifications statement; AT-34 runs all real handlers with fake providers and records as a committed evidence file; P1 is the pilot's screen gating P2 (T031 discipline); every live/paid step stays operator-gated via signed authorizations and account hard stops — G never spends.
- **Packages:** G1 records → G2 AT-14 → G3 AT-32 → G4 AT-34 → G5 composition + domain activation → G6 pilot scaffolding → G7 live procedures (G1/G3/G6/G7 note-first); AT-17/§16.3/AT-28-live marked LIVE, completing only by operator-gated execution.
- Eight open questions with recommendations (pilot topology, backup timer, image-price bootstrap, AT-28 staging, frozen-workload size, all-gates target, report location, bot live during pilot).

`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md`
