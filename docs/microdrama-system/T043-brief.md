# T043 — poster, preview and creative lineage

## Goal

Derive a readable static poster from approved character/title/CTA assets and
an optional episode-one preview of at most 90 seconds from accepted footage.
Keep these distinct from the three existing 20–40-second hook candidates.
No new video generation or publication slot is created by making derivatives.

## Ownership and anchors

Worker writes only `microdrama/src/microdrama/editing/` and scoped
`microdrama/tests/unit/editing/` and `tests/contract/editing/` paths.
Existing safe FFmpeg/export, cover and variants services are in
`editing/{ffmpeg,export,covers,variants_service,hooks}.py`; reuse their
argument-safe execution and accepted-source rules. T039 provides season title
and episode pack; T040 provides approved character/style asset versions.
Review package/schema/route registration is integrator-owned: propose any
required cross-module contract changes rather than editing `contracts/`,
`review/`, migrations, root config or task ledger.

## Acceptance

Poster and preview records must carry exact source IDs/versions/hashes,
rights, reveal boundary, source ranges, mobile safe zones, platform variant,
CTA truth, output/package hash and downstream lineage. Reject stale/unaccepted
source media, spoilers beyond reveal boundary, wrong CTA, unreadable poster and
unsupported rights. A changed source invalidates only its derivatives. The
optional preview must not be forced into the release plan, and the three hook
candidates remain intact.

Test poster/preview generation with local fake/accepted assets and FFmpeg,
source change invalidation and Gate 2 package projection handoff. Run scoped
tests/Ruff; parent runs `make check` after integration under CPUQuota45%.
No paid/cloud/public actions; no commit. Return exact files/results and any
shared contract or Gate 2 integration proposal.
