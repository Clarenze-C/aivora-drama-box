Phase C spec **v0.3** landed — all 16 findings applied, none BLOCKED.

- **PC-1** applied — §1.2 + §4 + §12 + C-T3: common idempotent entry helper after setup approval **and** STORY LOCK; derives items + forecast, advances the applicable scope to CASTING, enqueues each root ×3 exactly once; votes never invoke it
- **PC-2** applied — §2.2 CD2 + C-T1: V3 reference-kind/lock-body/lock-view contracts + workflow-aware readers/builders; V1/V2 unchanged; typed-path roundtrips
- **PC-3** applied — §2 C-1, §4, C-T4: per-candidate immutable parent ref/version + invalidation generation; freshness on the selected candidate; reroll invalidates without enqueueing; fresh unselected candidate can't freshen an old selection
- **PC-4** applied — §2 C-6, §7, §8, C-T11/T13: uploads bind to the audition vote + catalogue identity; Approve requires the clip matching the current audition; 6-member voice hash tuple; `provider_voice_ref` stable for NULL-speaker entries
- **PC-5** applied — §8 gate + lock step 1: activation binds full membership, exact clips, wardrobe record/version/hash, inspection records; mutation supersedes/reopens
- **PC-6** applied — §1.9 + §8: transaction-owned adoption helper (creator's `tx`, pre-commit, A's lock order, effectively-approved lock); V1 wrapper preserved
- **PC-7** applied — §5 + §17 + C-T6: batch limits stop new submissions only; recovery admission after death/ambiguous submission; inode not replaced while generators run; mount topology exposes replacement; real-mount test
- **PC-8** applied — §2.2 CD4 + C-T5: wait-view CASE **and** IN filter; asserted through the production `track_waits` reader
- **PC-9** applied — §3/§4/§11 + C-T3: per-kind dispatch (image/library/voice), initial library jobs scheduled, generate-next counts (outfits ×3, views ×1), forecast uses the same counts
- **PC-10** applied — §6: C5 note defines transition/temporary-interval, terminal carry, resets, composition/precedence, incompatible-combination rejection; C-T8 through the V3 resolver
- **PC-11** applied — §7/§8 + C-T11/T13: per-voice rights validated at audition, registration, Approve, import, dispatch; community needs per-voice evidence; Botnoi keeps OPERATOR_ATTESTED + WORLDWIDE
- **PC-12** applied — §7/§10 + new CD6: global-maintenance exception untracked with its own replay identity; fence stated; recorded catalogue snapshot; total tie-break (NULLS LAST + unique id)
- **PC-13** applied — §9 + C-T12: cast-consistency and forbidden-likeness recorded separately; every candidate assessed; empty selected set never PASS
- **PC-14** applied — new §1.13 + §8 + §11 + C-1/C-T13: scope/extension identity carried through commands, jobs, demands, binding resolution; initial vs extension stamping; no F UI implied
- **PC-15** applied — §5/§10 + C-T3: seed + request inputs persisted per `<pick, gen_seq>`; retries/polling/reconcile/restart retain them
- **PC-16** applied — §13/§14: C2 gates forecast data/panel, C9 gates the CAST condition; early-budget entry, typed roundtrips, old-selected/new-unselected, stale-review, rollback/concurrency, in-flight crash clauses added — no acceptance row weakened (C-T13 extends)

**Commit:** `6ce01a4` on `feat/microdrama-m0-m4` · **846 lines** (was 734). O-C1/O-C9 remain OPEN (OPERATOR); no BLOCKED items; only `phase-C-spec.md` touched; no report file written. Cross-checks against phase-A-spec v0.3, A1 §2.4, A2 §5, phase-B §8, SPEC-v3 §1/§12.2 and all cited code anchors (incl. `0002:142`, `service.py:287`, `v2_planning.py:1067–1072`) verified before folding. Ready for the round-2 Codex critique.
