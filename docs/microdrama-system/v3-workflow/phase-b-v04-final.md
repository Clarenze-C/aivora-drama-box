Applied all 45 Goldfish findings (C-B1, C-M1..M22, C-N1..N22) to phase-B-spec.md → **v0.4** (702 lines).

- **C-B1 register (§2.4):** step keys `step_01..03` adopted from A2 (no CHECK amendment); B1-owned migration extending A1's `RevisionTargetKind` (`PROPOSAL`, `EPISODE_PLAN`, `BIBLE_SECTION`, `SEAM`, `TIER`) + optional `V3DecisionCommand.target`; `edit_tier` command row; citation convention swept (e.g. dead "A2 §5.2" → A2 note §2.2/OQ-2; "A3 §7.1" → phase-A §7.1 + A3 note §3.4).
- **Two rulings needed reconciliation against frozen contracts, written as found:** A1 validates `replaces_job_id` only within one `logical_work_id` (A1 note §2.4), so the C-M1 round scopes the **semantic key**, not the work ID; and note-target kinds are Python-validated (no SQL CHECK exists to amend — A1 note §2.3).
- New sections: §2.4 deltas register, §9 B commands, §15 Risks, §16 Alternatives, §17 finding map (one line per id). Header re-pinned to master v0.4.6, A2/A3 notes v1.0.
- Corrected four stale code anchors (`primitives.py:54`, `v2.py:206/213`, `v2.py:1041`, `service.py:790`); every new code claim carries `file:line` (verified live, incl. `Settings` `S/config.py:42` and the exact seven tables for B-T5's restricted role).
- No code changed; only this file (`a0r1-build-REPORT.md` was dirty before this task).

`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-B-spec.md`
