# Codex critique: phase G spec v0.2 (live qualification, restore, all-gate composition, LIVE pilot), before code — round 1

Spec: `phase-G-spec.md` **v0.2** (`e76bda3`, 760 lines). GLM drafted v0.1 and applied its own
Goldfish rulings (`phase-g-goldfish-rulings.md` — zero blockers, 61 findings; review in
`phase-g-review/`). You did not write it.

Binding context: `SPEC-v3.md` v0.4.6 §12.5, §16.2–§16.3, §15.1 phase G row (V3-AT-14, 17, 32, 34,
AT-28's live half); `phase-A-spec.md` v0.3; `A1-design-note.md` v1.4 (ACCEPTED); accepted **B v0.6,
C v0.4.1, E v0.4**; `phase-F-spec.md` v0.4; the T031 run-readiness spec v0.3 (metering discipline);
`g-factmap.md`. Code (read-only): `microdrama/src/microdrama/` on `feat/microdrama-m0-m4`.

## Answer
1. Records/exports: the durable-home rule for pilot evidence (sha256-bound exports); LIVE claims
   bound to the production store; retention/teardown; the calibration→forecast bridge.
2. `dramabox-llm` + Pro off-pace (V3-AT-14): the pause-with-bot-alert wiring vs A0's surfaces and
   §3.3's bot; what "off pace" reads and who re-enables.
3. Composed restore (V3-AT-32): DB+objects together; scheduler/outbox/jobs resume without duplicate
   effects; notification ambiguity documented honestly.
4. All-gate composition (V3-AT-34): the offline end-to-end test across every gate — fixtures, what
   it proves that per-phase tests don't.
5. LIVE pilot (§16.3, V3-AT-17): P0/P1/P2 phases; PILOT-REPORT with measured cost/quota per
   provider; T031's authorization/verification discipline inherited; **every paid step
   operator-gated** — verify the spec never auto-spends.
6. AT-28's live half: the ARISA/Drama lock test procedure from C's design.
7. Throughput (MA11): closed-interval observations consistent with F's counter discipline.
8. Packages G1… order + acceptance mapping; anything that would make a G build fail or contradict
   the accepted phases.

## Output: read-only; ≤180 lines; issues `PG-1`… BLOCKING/SHOULD-FIX/NIT + replacement wording;
verdict **APPROVE / APPROVE-WITH-CHANGES / REWORK**.
