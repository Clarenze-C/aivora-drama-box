**phase-F-spec.md v0.1 DRAFT written** (567 lines). Key decisions:

1. **Two-part release authority:** content (Gate 2 / `TEASER_FINAL` via A's decision transaction) + calendar (LAUNCH); one admission point (`w13-release-admission`) checks fence, effective approval, calendar revision, live binding, caption route, dependencies — W09 untouched.
2. **V3 `platform_posts` rows created at dispatch admission**, dates resolved from the bound calendar revision — resolves the date-pinning/slot-UNIQUE immutability conflict (FM §4) without touching V1/V2 triggers or reinterpreting historical dated approvals.
3. **Calendar = versioned `ReleaseCalendarV3` document**; reschedule is calendar authority (Confirm + impact hash), never an amendment; published media immutable; N11 corrective posts operator-approved.
4. **Thumbnails = phase C pick pattern** (votes start no work, pick before Approve, staleness computed); drafts prefill Gate 2 via one A0 `LlmStep` call per episode; sealed manifest = edited drafts.
5. **Teaser** `PROMO_CUT` at premiere − 3 d gates episode 1 per destination; recovery = approved repair or reschedule. HELD/MISSED/PARTIAL are derived per-destination states (N43 reading).
6. **Extension (V3C-26):** F owns the decision screen + viewership windows; B's `create_extension` + calendar revision append; fences per §8.5 race table.
7. Build packages **F1–F10** (F1/F2/F4/F7/F8 notes critiqued first); acceptance F-T1…F-T13 covering V3-AT-11/12/29/30/31.

**Open questions (10, each with a recommendation):** O-F1 = **O-8 (operator decides before F5)** — recommend YT caption tracks now, TT/FB TH-only until T032 qualifies caption files; O-F2 admission-time post creation; O-F3 teaser at 19:00; O-F4 swap = date remap; O-F5 corrective route per capability; O-F6 rolling vs daily windows; O-F7 hashtag limits from capability records; **O-F8 N43 is cited in SPEC §2.2 but defined nowhere (grep verified) — needs an orchestrator anchor**; O-F9 one LLM call per episode; O-F10 rescheduled-CTA substantive boundary.

File: `/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/phase-F-spec.md`
