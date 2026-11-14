**Phase G spec v0.2 applied in place — commit `e76bda3`, 760 lines (was 556). 19/19 Majors applied, 0 BLOCKED.**

**Majors (all applied):**
- **M1** — pause episode semantics pinned in §4: "active PACE_WEEK deferral" = non-terminal regardless of `retry_at` (clamp never shortens an episode); durable edge = per-firing recorded evaluations, episode = maximal run of true evaluations, reconstructed on restart; un-pause reader = the A0 §5.7 gate re-evaluated on deferred retries; predicate and gate share the stored observation stream; `track='production'` justified
- **M2** — poller kept, choice recorded: 60 s → **300 s** (the catalog's fastest class, `registry.py:129/:135`, verified); §4 states why polled-not-evented (falling edge has no event source; gate-side emission goes silent once all jobs defer); §16 rejected-alternative row added
- **M3** — §2.1b durable-home rule: ephemeral-profile records must reference committed sha256-bound exports under `microdrama/evidence/pilot/`; production store authoritative for LIVE claims/activation; export-at-phase-close; retention-then-teardown; calibration→forecast bridge through the export; §15 + §16 rows
- **M4** — §5.5 proof-kind matrix (unclean test-profile proof vs nightly control proof with **fake-transport** composition — never real duplicate Telegram sends); activation takes the freshest PASS of either kind; **one shared backup entrypoint** for drill + timer (§3.3, G3 row, O-G2)
- **M5** — P2 window defined: release-interval span since LAUNCH, complete intervals only, window named in the report; catch-up must be scheduled or recorded UNMEASURED with a signed adaptation (§7.4, §7.5, §9)
- **M6** — GD3 registers the `pilot.*`/`ops.*` command-audit event families (sink, naming, no A-registry collision)
- **M7** — §5.1 corrected: drill restores via `psql -v ON_ERROR_STOP=1` (drill.sh:127, verified); objects extraction marked as **new G work**; catch-up bound re-attributed to A §9.1.4 with the code cite supporting §5.2 only
- **M8** — §0 + decision 8: FM §5 → FM §1 (both verified against the factmap TOC)
- **M9** — both §7.6 threshold-sign-off refs retargeted to §7.5 + the §10 command
- **M10** — "master" alias declared in the preamble; every master ref qualified document-wide (headings included; swept line-by-line — 3 stragglers fixed post-write)
- **M11** — decision 6 names the two alert causes (`QUOTA_UNREADABLE`, `PACE_WEEK`); per-window refusals explicitly never alert
- **M12** — split coverage defined (re-cut at boundaries where no speech is mid-utterance, one expression per clip) + anchored to master §6 MA12 / SPEC-v3.md:550-553
- **M13** — §11 prerequisite sentence fixed: A0/A/B/C/E/F accepted, D pending; **D gates G4–G6, not G1–G3** (G7 C/ARISA-pinned)
- **M14** — Home surface pinned in §4 (scope banner from the episode record, dismissable via A1 scope-alert dismissal) + new G-T2(i)
- **M15** — Create/Modify column; drill.sh and Makefile marked as modifications of live operator tooling
- **M16** — G-T2 (a–i) / G-T4 (a–j) / G-T5 (a–f) as enumerated one-observable-per-bullet lists below the table; G-T4's broken 4-line row rejoined
- **M17** — G-T2(a) names the seam: the one composition factory, production role config, A0 §5.8 fake at the gateway interface with seeded qualification rows — no second composition
- **M18** — startup-vs-dispatch matrix (config-enabled + missing piece → startup refuses; switch-off → disabled with typed deferral; post-startup expiry → dispatch refuses); "enabled in configuration" phrasing
- **M19** — §15 + four new rows (episode-state reconstruction, evidence retention, P2 window, upstream volatility) + two §16 rows (alert placement, record home)

**Nits:** all 42 swept — cite fixes (N1 `events.py:8-10`/`service.py:21-22`); preamble conventions (N2 runbook Q7 named, A-line defined, 0026, B:213); ARISA-blocked critical path + run-ahead (N3); A1 v1.4 + sourced acceptances + symmetric Opus re-checks (N4); YuE2, `dramabox-llm`, Home, V1 `make pilot` defined (N5–N8); §10 gains Scope/revision-owner + Activation columns, invocation surface, PilotRunV3 writer named (N9, N14); step numbering, O-11/AR-4/S05-S06 glosses, A0-LIVE-REPORT marked prospective + drill.sh full path (N10–N12); AT-28 topology mirror + fairness-as-conformance, broken code span (N13, N23); token rotated before P1 (N24, decision 14); fifth-type-family + sealing reuse (N25); G-T3 cadence scoped (N26); pilot-output disposition (N27); runtime bound as hard 2× gate (N28); five-tables dropped→named (N29); both-models wording (N30); ungated items asserted + runbooks located (N31); C-T6 harness as ARISA side (N32); +LIVE trace, O-G6/G-T8 aligned, §13 last row rekeyed (N33–N35); bolding key stated (N36); G-T3 clause, ×2 dropped, directing, casing, LIVE antecedent, catalog gloss (N37–N42); authorization spelling unified (N17).

**Verification:** every fact written in was checked against the tree/specs first (drill.sh 108–141, code cites, B:213, A1 v1.4, F §2.2/§12 conventions, master §6/§10.6/§16.3 wording, O-11, AR-4); diff audited — no acceptance row weakened, several strengthened. Hard limits held: offline, no pushes/merges/deletes, no env output.
