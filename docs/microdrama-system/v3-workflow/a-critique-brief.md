# Codex critique: Phase A spec v0.1 (Foundations), before the build

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-A-spec.md` **v0.1**.
Master: `SPEC-v3.md` **v0.4.2** (read §2, §3, §9.4, §10.0, §10.5, §10.6, §12.3, §12.6, §15, §16).
Depends on: `phase-A0-spec.md` v0.2 (LLM gateway, `LlmStep`, migration 0027).
Facts: `a-factmap.md` (the reuse compatibility audit the spec's §2 register is built from). All are in the
same folder.

Code (read-only): `/root/AIVORA/drama-box/microdrama/src/microdrama/`, `microdrama/migrations/`,
`microdrama/tests/`, `microdrama/deployment/`, `microdrama/Makefile`. Branch `feat/microdrama-m0-m4`.

## Answer

1. **Reuse register (§2, R1–R23).** For each row: is "today" accurate, and is the required change
   complete and buildable? Name every reader/writer of a changed component the register misses (gates,
   `approval_events` CHECKs, `GATE_ACTIONS`, `_entity`, scheduler selectors, `human_wait_guard`, the
   janitor, progress, budget accounts and their SQL CHECKs). **Would any change alter V1 behaviour or
   break `make check` / `make pilot`?**
2. **Version discriminator (§1).** Is `seasons.workflow_version` enough to keep V1 and V3 apart in every
   selector, guard and view, including episodes reached without a season join?
3. **Tracks (§3).** Do the track tables + pinned legacy state avoid every legacy reader that interprets
   `seasons.state` / `episodes.state`? Is the command table complete for phase A? Lock order vs budget
   locks.
4. **Gates (§4).** Is the `GateHandler` registry compatible with today's `decide_season` /
   `decide_episode`, human session, CSRF, idempotency key and revision binding? Is "V3 Gate 2 refused
   until F" safe?
5. **Budget hierarchy (§5).** Is the `SEASON` → child → categories lock order deadlock-free with the
   existing `reserve()`? Do the scoped SQL cap CHECKs + `account_cap_amendments` keep caps immutable in the
   guarded sense? Is the "no partial overrun" claim true with concurrent workers? Does the cleanup/shutdown
   exception still hold?
6. **Amendment fence (§7).** Is the mandatory `expected_input_revision` + completion re-read enough to stop
   stale writes, including for work inside a provider operation that completes after cancellation?
   Interaction with `JobService.cancel` and in-flight reconciliation.
7. **Outbox + bot (§8), scheduler (§9 R20), production composition (§9).** Do they reuse
   `domain_events` / `event_dispatches` / `OutboxDispatcher` correctly? Is the advisory-lock singleton
   sound? Does the fail-closed composition leave staging untouched?
8. **Migrations (0028+), tests, acceptance (§10).** Are A-T1..A-T18 sufficient to prove V3-AT-1, 2, 13,
   16, 20, 21 and R-11.2..R-11.6, R-12.6, R-12.7? What is missing? Is the phase too large to build as one
   package; if so, propose a split into ordered packages with their own gates.
9. **Anything else** that would make the build fail, change V1 behaviour, or contradict master v0.4.2 or
   A0 v0.2.

## Output

- Read-only; no writes. Put the full report in your final message, at most about 220 lines.
- Issues use IDs `AC-1`…, with severity **BLOCKING / SHOULD-FIX / NIT**, a `file:line` fact where it
  applies, and replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
