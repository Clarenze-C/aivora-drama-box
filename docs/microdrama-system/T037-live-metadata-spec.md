# T037 live metadata completion — integration spec

This specifies the remaining V2 Gate 2 and live-submit work after the offline
W09 rearm correction. It does not authorize a public post.

## Contract

Keep the V1 `ReleasePackage.package_hash` and its existing database approval
binding intact for legacy readback. A V2 `ReleaseApprovalManifest` must be
compiled before Gate 2 from that exact package, its immutable per-slot metadata,
cover/CTA and mutation policy. Gate 2 must show the complete manifest and bind
its hash in the same human approval event. The event must retain the V1 package
hash and carry the V2 manifest hash separately, with a database check that both
belong to the same episode/package. An event cannot be added later to give an
old approval new metadata authority.

Canonical per-slot metadata must retain its `ApprovedSlotMetadata` ID, version,
content hash, package ID/hash, slot identity, cover ID/version/hash and CTA.
The legacy `PostMetadata` projection may be derived for provider adapters, but
cannot substitute for this canonical approved record. A substantive metadata
edit requires the existing bounded management policy and an immutable new
version; the current version must be checked against approved policy at submit.

## Persistence and runtime

Add an ordered migration with immutable V2 manifest and per-slot metadata
storage, exact package/event associations and unique current-version/slot
constraints. Preserve existing V1 rows and offline mock behavior. The scheduler
and pilot runner must load the post's exact approved package and current
canonical slot metadata; publishing verifies the manifest hash bound to the
human event, exact slot/metadata/cover/CTA values, rights, capability and
approval freshness before any live transport call. A cover or CTA may be
explicitly absent when the approved slot policy does not require one; the
sealed manifest must bind that absence, and a later addition or change is
stale. Missing required fields or an old
V1-only approval hold the live slot with a typed reason. OFFLINE_MOCK alone may
use its explicit synthetic metadata path.

## Acceptance

Fixture tests must prove one absent-result rearm and verified readback; restart
and concurrent timer dedupe; stale package, event, manifest, metadata, policy,
cover and CTA changes all block before transport; a cover/CTA required by the
approved slot policy cannot be omitted. No mock-labeled title/caption/
description reaches a live transport. A pre-migration V1 package remains
readable, but cannot acquire V2 live authority by a later update. Migration
upgrade/readback and backup restore are tested in isolated PostgreSQL. Run
scoped review/publishing/scheduling tests, `make check`, and `make pilot`.

This work is offline software validation. T032 separately qualifies real
accounts, permissions, disclosure readback and public URLs.
