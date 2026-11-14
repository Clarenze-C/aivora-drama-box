**Verdict: REWORK.** Reviewed v0.3 at `40c4d13`; the working spec matches. Scoped to round-1 findings and their edits. Read-only; no files changed or tests run.

- **PG-1 — CLOSED.** [G §7.0](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:548) explicitly blocks publication at four episodes and requires separate authorization for additional production.

- **PG-2 — CLOSED.** [G §7.4](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:637) preserves F-6 first-approval intervals, labels preliminary rates and keeps missing sustained/catch-up evidence UNMEASURED.

- **PG-3 — PARTIAL — PG5-1, BLOCKING: the operative pause predicate still contradicts automatic recovery.** [G §4](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:345) remains true whenever a non-terminal `PACE_WEEK` deferral exists, regardless of `retry_at`. A fresh GD4 on-pace observation therefore cannot clear that predicate as [the recovery clause promises](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:362).
  
  **Replacement:** “Derive the route pause from GD4’s latest evidence under its freshness policy and current isolation status. Fresh readable, on-pace evidence supersedes historical refusals even while their deferred job rows remain non-terminal. Preserve refusal history, gateway reset times and per-job retry clamps separately.” Test recovery with an old non-terminal `PACE_WEEK` row still present.

- **PG-4 — CLOSED.** [G decision 4](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:114) requires independent authorization enforcement across admission paths; [G-T6](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:820) covers bypass, drift, expiry and retries.

- **PG-5 — CLOSED.** [G §5.5](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:495) requires a credential-free restore composition, replacement of every external transport and zero real calls across recovery paths.

- **PG-6 — PARTIAL — PG5-2, SHOULD-FIX: the added test still preserves the operation’s local intent.** [G §5.1](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:414) seeds `SUBMITTED` before the dump; acceptance afterward removes neither that row nor its client token from the snapshot. This tests reconciliation of a recovered identity, not discovery of an effect whose intent is absent. [§5.4’s fence-and-reconcile procedure](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:481) is correct but lacks that exercise.
  
  **Replacement:** “Retain the recovered-intent case. Add an operation created and accepted after the snapshot, with its local operation row and client token absent from the dump. Preserve external evidence across restore; fence the source, discover and reconcile the omitted activity, and assert that unresolved activity blocks admission without another submit.”

- **PG-7 — CLOSED.** [G §3.3](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:311) binds the object closure to the snapshot, declares immutability and requires integrity verification before resume; G-T3 includes negative cases.

- **PG-8 — CLOSED.** [G §4](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:378) declares durable evaluation records and atomic evaluation/firing/alert commits; G-T2(e) covers rollback and restart around both edges.

- **PG-9 — PARTIAL — PG5-3, BLOCKING: calibration cannot use the specified switch sequence.** [G §7.2](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:580) keeps the image switch off until calibration completes, while calibration itself requires live Nano Banana. Switching it on earlier also releases queued ordinary cast work unless admission distinguishes the calibration workload. The provisional-price exception does not resolve this switch conflict.
  
  **Replacement:** “Authorize calibration as a distinct bounded workload, then enable the provider with every-admission guards admitting only that workload and refusing ordinary cast image jobs, including queued jobs. Register C’s provisional-price exception for calibration only. Admit ordinary cast generation only after measured receipts, the committed checkpoint and the complete demand-list fit check pass.” Add a dry test proving calibration proceeds while queued cast jobs remain refused.

- **PG-10 — CLOSED.** [G §2.1b](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:218) requires independently verifiable evidence closure, terminal closure for PASS/FAIL/ABORTED and equivalent scratch-proof retention.

- **PG-11 — CLOSED.** [G §7.6](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:696) and the command prerequisites require signed retained evidence, completed applicable LIVE acceptance, current T032 qualifications and exact verified release identities.

- **PG-12 — CLOSED.** [G §10](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:768) separates `P1_SCREEN` from `FINAL`; screen approval cannot complete final throughput acceptance.

- **PG-13 — CLOSED.** [G decision 3](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:102) defines authorized mode boundaries and reconciliation choreography without widening either mode.

- **PG-14 — CLOSED.** [G §8](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:731) preserves submission-cutoff and recovery protection semantics; [§7.4](/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-G-spec.md:666) separates quota evidence, charges and attestations.