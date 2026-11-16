# WEEKEND HANDOFF — GLM → Opus (Sun 15 Nov 2026)

Written by the GLM orchestrator session at the close of the weekend runbook (Fri 13 → Sun 15 Nov).
**Opus: read the runbook's STATE section for the full audit trail; this file is the summary.**
The operator's standing decisions this weekend (all logged in STATE): O-8 ruled, O-C1 + the V1
carve-out decided, the rule-7 round waivers, the A-track fixes, and the closing directive
("finish A1 → r5-fix1 → handoff").

## Accepted (gate green + Codex ACCEPT, nothing merged/pushed)

| What | Version / tip | Notes |
|---|---|---|
| **A0-D** (gateway, `LlmStep`, 0027) | `eea2f79` on `feat/a0d-gateway` | 6 fix rounds, 7 reviews (13→10→7→4→2→1→0 findings); decisive gate 372 integration |
| **A1** (discriminator, gates, decision transaction, 0028–0031) | `307a81e` on `feat/a0d-gateway` | 2 fix rounds (11→3→0); decisive gate 3,227 unit / 467 contract / 541 integration / pilot |
| **B spec** | v0.6 | + B1 note v0.3, B5 note v0.3 (both ACCEPTED) |
| **C spec** | v0.4.1 | O-C1/O-C9 decided by operator |
| **E spec** | v0.4 | |
| **G spec** | v0.4 | |
| **A3 / A6b notes** | v1.3 / v1.2 | |
| **A1 note** | v1.4 | |

## Parked / deferred (Monday decisions)

- **A2 note** — 4 review rounds; each lock-table fold regressed elsewhere (final: R4 closed 4/5 but
  introduced 2 new blockers). **Needs Opus to design the global lock order once, properly** — not
  another wording round. Lineage: `codex-a2-r4.md` + `codex-a2-r3.md`.
- **A0-R1** — round-2 FIX-REQUIRED (3 BLOCKING); fix brief never written (operator may prefer Opus
  to redo it alongside A2's lock design — same `#6→#7→#6` cycle domain).
- **F spec r3** — deferred with D/E context (operator's plan).
- **D spec** — deliberately last; needs T031's REAL Pika results (operator-gated).
- **A1 note's A2-parked OQs** (OQ-2/3/5) — resolve with A2's design.

## In flight at handoff (this session's loop continues until they land)

> **Closed 16 Nov (Opus):** r5-fix1 died on the 00:14Z disk-full with all commits intact; after
> r5-fix2 and Codex R3 ACCEPT, **T031 R5 is ACCEPTED at `45811d3`** and RR-T3 PASSED (local rebuild).
> See `HANDOFF.md` CURRENT, 16 Nov update.

- **r5-fix1** (T031's 10 review findings, brief `T031-fix-round/r5-fix1-brief.md`, worktree
  `.scratch/t031-r5`) → verify → R2 review → gate. The RR-T3 image rebuild stays **disk-blocked**
  (needs ≥12GiB free; ~4G at handoff) and the push/paid run stay operator-gated.

## For the operator (unchanged + additions)

1. A0-D: install the gateway systemd unit + group 64010 + dirs; OK the live qualification (≤5 calls).
2. Disk cleanup ≥12GiB (RR-T3 + general headroom); the stray `docs/microdrama-system/v3/` dir
   (typo artifact) may go.
3. T031 post-accept: push the image, token file, A40 quote, authorization, live run.
4. A0-R1 merge decision (after its fix).
5. Bot token rotation before go-live.
6. **Monday test-robustness item**: the `edit.assemble_episode`/`edit.variants_and_hooks` ffmpeg
   tests failed empty-detail 3× this weekend, only under concurrent load, never solo — retry/timeout
   isolation candidate.

## Numbers

- **240+ commits** on `feat/microdrama-m0-m4` (docs/specs/rulings) + 30 commits on
  `feat/a0d-gateway` (the two accepted packages). Nothing pushed/merged.
- ~40 Codex reviews/critiques; 6 full gates green (2 superseded by later tips); every GLM ruling
  marked "Opus re-check Mon".
- **Four dormancy gaps** (≈4h, 2h, 9.5h, 3.6h of idle quota) — keepwarm is now always-on, which
  fixes the root cause; the lesson (idle wakeups must always re-arm) is embedded in the loop.
- Zero rule breaches: no pushes, merges, deletions, service restarts, or paid calls at any point.

## Where to resume Monday

`WEEKEND-GLM-RUNBOOK.md` STATE (latest entries at the bottom of the STATE block) → this file → the
parked items above. The v3 program's design layer is complete except A2/A0-R1; the build layer now
has A0-D + A1 accepted, with A2's build blocked on its parked design.
