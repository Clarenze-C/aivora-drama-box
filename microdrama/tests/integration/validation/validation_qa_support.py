"""T030 validation support: seed a reviewable episode against the composed world.

The same durable shapes the lanes' own tests use (season → Gate 1 → episode →
CURRENT script → registered media asset), built with persistence APIs only —
then every check runs through the COMPOSED world's services.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from microdrama.contracts.enums import AssetKind, AssetState, Provenance
from microdrama.contracts.examples import script as example_script
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import AssetDescriptor
from microdrama.persistence import Database, insert_row, jsonb, register_asset
from microdrama.testing.media import probe
from microdrama.testing.seed import seed_episode, seed_gate1_approval

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def seed_season_with_gate1(db: Database) -> uuid.UUID:
    from microdrama.contracts.examples import season_scope

    season_id = uuid.uuid4()
    scope = season_scope().model_copy(update={"season_id": season_id, "scope_version": 1})
    scope_hash = canonical_hash(scope)
    with db.transaction() as tx:
        approval = seed_gate1_approval(tx, season_id, scope_hash)
        tx.execute(
            "INSERT INTO seasons (id, state, title_th, title_en, approved_scope_version, "
            "approved_scope_hash, approval_event_id, approved_at) VALUES (%s, "
            "'SEASON_APPROVED', %s, 'Test season', 1, %s, %s, %s)",
            (season_id, scope.title_th, scope_hash, approval, T0),
        )
    return season_id


def seed_episode_with_script(db: Database, season_id: uuid.UUID) -> uuid.UUID:
    with db.transaction() as tx:
        episode_id = seed_episode(tx, season_id, state="AI_REVIEW")
        script = example_script().model_copy(
            update={"episode_id": episode_id, "script_id": uuid.uuid4()}
        )
        insert_row(
            tx,
            "scripts",
            {
                "id": script.script_id,
                "episode_id": episode_id,
                "version": 1,
                "canon_version": 1,
                "body": jsonb(script),
                "body_hash": canonical_hash(script),
                "status": "CURRENT",
            },
        )
        tx.execute(
            "UPDATE episodes SET current_script_id = %s WHERE id = %s",
            (script.script_id, episode_id),
        )
    return episode_id


def register_media_asset(world, episode_id: uuid.UUID, path: Path, *, media=None) -> uuid.UUID:
    """Store a real media file and register it as the episode's ACCEPTED asset.

    ``media`` overrides the probed descriptor (truncated files cannot probe)."""
    data = path.read_bytes()
    if media is None:
        with tempfile.NamedTemporaryFile(suffix=path.suffix) as tmp:
            tmp.write(data)
            tmp.flush()
            media = probe(Path(tmp.name))
    with world.db.transaction(readonly=True) as tx:
        season_id = tx.fetchone("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))[
            "season_id"
        ]
    stored = world.store.put_bytes(
        f"t030/{episode_id}/{uuid.uuid4().hex}{path.suffix}", data, media_type="video/mp4"
    )
    asset_id = uuid.uuid4()
    with world.db.transaction() as tx:
        register_asset(
            tx,
            AssetDescriptor(
                asset_id=asset_id,
                asset_kind=AssetKind.VIDEO,
                object_key=stored.key,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type="video/mp4",
                media=media,
                state=AssetState.ACCEPTED,
                provenance=Provenance.ORIGINAL_FIXTURE,
                episode_id=episode_id,
                season_id=season_id,
                created_at=world.fakes.clock.now(),
            ),
        )
    return asset_id
