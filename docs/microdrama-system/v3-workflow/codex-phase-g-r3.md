**Verdict: APPROVE.** Reviewed v0.4 at `39171da`; the working spec matches. Scope: PG5-1–PG5-3 and defects introduced by their edits.

- **PG5-1 — CLOSED.** [§4, phase-G-spec.md:354](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:354) derives the pause from current GD4 evidence and isolation status. Fresh on-pace evidence supersedes historical refusals. G-T2(h), line 895, explicitly tests recovery with an old non-terminal `PACE_WEEK` row present.

- **PG5-2 — CLOSED.** [§5.1, phase-G-spec.md:438](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:438) adds an effect created and accepted after the snapshot, with neither its operation row nor client token restored. §§5.1–5.2 and G-T3 require fencing, external discovery, blocked admission while unresolved, and adoption without another submit.

- **PG5-3 — CLOSED.** [§7.2, phase-G-spec.md:618](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:618) distinguishes the authorized calibration workload at every image admission. Queued cast jobs remain refused until measured receipts, the committed checkpoint and complete demand-list fit pass. G-T6, line 872, exercises calibration and queued-cast exclusion together.

No new PG6 findings within scope. Read-only review; no files changed or tests run.