# Phase F Codex critique round 1 — GLM rulings (13 Nov 2026)

Input: `codex-phase-f-critique.md` (verdict REWORK; PF-1..11 BLOCKING, PF-12..17 SHOULD-FIX) against
`phase-F-spec.md` v0.2. Every ruling is a **GLM ruling, Opus re-check Mon**. All findings are technical
conformance fixes with replacement wording; O-8 stays OPEN (PF-15 keeps F5 conditionally blocked —
correct). **All 17 ACCEPTED**; no acceptance row weakened (PF-16 re-gates and adds cases).

| ID | Ruling (one line) |
|---|---|
| PF-1 | ACCEPT — version-selected adapters for scheduling/command/submit/poll/recovery/release views; V3 uses `episode_tracks`, legacy state pinned, shared transport/persistence reused beneath; V1/V2 unchanged. |
| PF-2 | ACCEPT — compare the effective approval's decided-activation `content_revision` with the authoritative scope `content_revision`; never `approval_events.expected_revision`; test where decision and content revisions differ. |
| PF-3 | ACCEPT — carrier registered as an explicit V3 contract crossing: guarded carrier identity/numbering, season-gate→carrier-package binding, manifest resolution, catalog policy, corrective-post authority; version-aware validation preserves V1/V2; F-T6 exercises the real typed + SQL paths. |
| PF-4 | ACCEPT — season-scoped identity graph (same-season/destination checks, cycle detection) for discovery + submit; approved swap/closeout decisions supply explicit dependency overrides consumed by both checks; V1/V2 keep package-local DAG. |
| PF-5 | ACCEPT — V3 content obligations separated from resolved calendar instants; the V3 command builder resolves schedule from the current authorized calendar binding and checks it against the post projection; legacy dated packages/hashes keep their interpretation; crossing registered in §2.2. |
| PF-6 | ACCEPT — the V3 submit adapter revalidates content/calendar/cancellation/binding under A's lock order immediately before `provider_ops.begin`; reschedule checks operation history/linkage and fences/replaces obsolete queued commands atomically; barriers before begin and after begin/before response. |
| PF-7 | ACCEPT — guarded V3 rebinding operation for unpublished identities after proving no external effect (package/approval/media/token handling specified, attempt history preserved, begun work reconciled first, published media immutable); date-only UPDATE stays valid when content authority is unchanged. |
| PF-8 | ACCEPT — extension revision carries authority forward for unchanged existing obligations (explicit equivalence rule); new-range authority from the extension decision; new Gate 2 approvals supply content authority; extension dispatch/completion rules defined with prior approvals and coarse states preserved. |
| PF-9 | ACCEPT — first option: retain A's Gate 2 feedback contract (timecoded) and add typed targeting through an explicitly registered compatible extension (registered as an FD crossing); V1/V2 unchanged; real JSON/HTML submission + commit test. |
| PF-10 | ACCEPT — F registers its dependency edges and rebuild handlers with A4 (exact source versions, approval/identity bindings); Impact and Apply traverse the closure; E-owned recap/CTA/caption rebuild needs E's pinned contract (explicit dependency); unchanged published artifacts excluded. |
| PF-11 | ACCEPT — V3 completion quantifies over all required allocated identities (with or without posts); first-slot admission advances the track once; later destination admissions valid in the release states and never replay as whole-episode completion. |
| PF-12 | ACCEPT — Gate 2 records content authority independently of allocation; allocation binds every already-approved in-scope episode; later effective approvals refresh affected content bindings (incl. initial-five and teaser replacements) without rerunning LAUNCH. |
| PF-13 | ACCEPT — state precedence + permitted dispatch window defined; expired obligations needing reschedule stay undispatchable until approved recovery supplies calendar authority; recoverable-held distinguished from unresolved external effects. |
| PF-14 | ACCEPT — thumbnail candidates persist asset/version/hash + source pack/cast/content bindings + inspection ref per candidate; voting only selects; stale candidates need regeneration + fresh selection; release picks use explicit consumer scope, never entering CAST LOCK membership or cast forecasts. |
| PF-15 | ACCEPT — conditional on O-8: F5 implements the selected route's durable delivery + verification workflow binding exact E-produced tracks; required-caption failure holds release qualification with retry/reconcile. F5 stays blocked on O-8. |
| PF-16 | ACCEPT (strengthens) — A-compliant test handlers/fixtures for early gates; schema vs workflow compatibility split; real 30-day simulation rerun after recovery integration; date-only vs rebuilt-content assertions separated; the concrete race/missing-destination/extension/candidate cases added to their gates. |
| PF-17 | ACCEPT — buffer counts consecutive currently-approved release obligations ahead of the next release with destination constraints; daily observations over closed non-overlapping intervals with idempotent catch-up; rolling rates use complete intervals. |

**Apply:** fold all 17 into **phase-F-spec.md v0.3** (job `dramabox:f-spec-v03`, docs only, queued behind
c-spec-v03 and b-spec-v06). Round-2 critique follows v0.3 (F has one round left under rule 7).
