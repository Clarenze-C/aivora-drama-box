# Codex critique: phase F spec v0.2 (release: metadata, Gate 2, teaser, calendar, slots, amendment integration), before code — round 1

Spec: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md` **v0.2** (`ef63e65`,
786 lines). GLM drafted v0.1 and applied its own Goldfish rulings (`phase-f-goldfish-rulings.md`,
review `phase-f-review/consolidated_review_report.md`). You did not write any of it.

Binding context: `SPEC-v3.md` v0.4.6 §4.8–§4.10, §9, §12.6, §15 (phase F row: V3-AT-11, 12, 29, 30, 31);
`DECISIONS.md` Q6; `phase-A-spec.md` v0.3; `phase-B-spec.md` v0.5/v0.6-in-flight; `phase-C-spec.md`
v0.2/v0.3-in-flight (picks engine F extends); facts: `f-factmap.md`. Code (read-only):
`microdrama/src/microdrama/` on `feat/microdrama-m0-m4` (publishing, review, slots, scheduler, outbox).

## Answer

1. The former Blockers: in-place date UPDATE reschedule (vs `service.py:1045-1058`, `M/0005` triggers);
   the synthetic carrier episode for season-scoped posts (vs `platform_posts` NOT NULLs, `slots.py`);
   gate-column re-map (each package's gate passable at its own step).
2. Admission transaction (`w13-release-admission`): the `schedule_release` invariant inventory, re-bind
   after reschedule, extension-identity allocation, calendar/content authority split.
3. Teaser: `PROMO_CUT` at premiere − 3d gating episode 1 per destination; recovery paths; metering
   (SEASON_SETUP); the carrier's admission checks.
4. Metadata/thumbnails: drafts prefill Gate 2; sealed manifest = edited drafts; thumbnail pick before
   Approve via C's picks engine (pick_kind THUMBNAIL) — consistent with phase C v0.2/v0.3?
5. Amendment integration (V3C-26, V3-AT-30/31): extension during/after release; stale results and old
   approvals cannot release changed artifacts; §8's race fences.
6. Buffer/dependencies (V3-AT-12) and the 30-episode simulation (V3-AT-29): HELD/MISSED/PARTIAL
   derivation, proven-absence re-arm, no duplicated posts.
7. Packages F1–F10 order and F-T1..F-T13 sufficiency for the five ATs.
8. Anything that would make an F build fail or contradict A/B/C.

O-8 (caption delivery) is OPEN (OPERATOR) by design — F5 is marked conditionally blocked on it; flag
dependency risk, do not demand resolution. Phases D/E specs don't exist yet — F5's E-contract
dependency should be marked, not resolved.

## Output

- Read-only; no writes. Final message at most about 180 lines.
- Issues `PF-1`…, severity **BLOCKING / SHOULD-FIX / NIT**, `file:line`/`§`, replacement wording.
- Verdict: **APPROVE** / **APPROVE-WITH-CHANGES** / **REWORK**.
