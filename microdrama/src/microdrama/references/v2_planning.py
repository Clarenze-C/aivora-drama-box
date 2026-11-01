"""Demand-driven V2 reference planning and offline persistence (T040).

Consumes frozen V2 records and the Gate-1 approved V1 ``SeasonScope``. Provider
dispatch and budget reservations remain injected; durable media and versioned
typed records use the existing asset store and ``v2_contract_documents`` ledger.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from microdrama.contracts.enums import AssetKind, AssetState, Provenance
from microdrama.contracts.errors import Conflict, NotFound, SchemaInvalid
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.media import AssetDescriptor, MediaInfo
from microdrama.contracts.primitives import UtcDateTime
from microdrama.contracts.registries import RightsRecord
from microdrama.contracts.season import SeasonScope
from microdrama.contracts.v2 import (
    AssetSheet,
    EpisodePack,
    EpisodeScene,
    LocationLayout,
    OutfitDefinition,
    PropSheet,
    RightsGrant,
    SceneWardrobeAssignment,
    StateEvent,
    StateValue,
    StyleBible,
    WardrobeBible,
    validate_current_rights_grant,
    validate_state_event_chain,
    validate_wardrobe_assignment,
    verify_v2_record_hash,
)
from microdrama.persistence import Database, get_asset, jsonb, register_asset


@dataclass(frozen=True)
class AssetDemand:
    role: str
    subject_id: str
    view_name: str
    prompt: str
    cache_key: str
    rights: RightsGrant
    estimated_micro_usd: int
    seed: int = 0


@dataclass(frozen=True)
class MockAsset:
    cache_key: str
    payload: bytes
    sha256: str
    provenance: str = "OFFLINE_MOCK"


def make_offline_style_video() -> bytes:
    """Render a tiny deterministic moving test pattern, never a provider call."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SchemaInvalid("ffmpeg is required for an OFFLINE_MOCK moving style sample")
    with tempfile.TemporaryDirectory(prefix="md-style-sample-") as temp_dir:
        target = Path(temp_dir) / "style-sample.mp4"
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=8:duration=1",
                    "-an",
                    "-frames:v",
                    "8",
                    "-c:v",
                    "mpeg4",
                    "-q:v",
                    "8",
                    "-threads",
                    "1",
                    "-y",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SchemaInvalid("bounded FFmpeg OFFLINE_MOCK sample generation failed") from exc
        payload = target.read_bytes()
    if not payload or len(payload) > 2_000_000:
        raise SchemaInvalid("OFFLINE_MOCK style sample output exceeded its byte bound")
    return payload


def _probe_video_bytes(payload: bytes) -> MediaInfo:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise SchemaInvalid("ffprobe is required to validate the moving style sample")
    with tempfile.TemporaryDirectory(prefix="md-style-probe-") as temp_dir:
        source = Path(temp_dir) / "sample.mp4"
        source.write_bytes(payload)
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
                    "-of",
                    "json",
                    str(source),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            facts = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise SchemaInvalid("style sample is not a readable audiovisual file") from exc
    streams = facts.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video is None:
        raise SchemaInvalid("moving style sample contains no video stream")
    try:
        duration_ms = round(float(facts["format"]["duration"]) * 1000)
        fps_num, fps_den = map(int, video["r_frame_rate"].split("/", maxsplit=1))
        return MediaInfo(
            duration_ms=duration_ms,
            has_video=True,
            has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
            width=int(video["width"]),
            height=int(video["height"]),
            fps_num=fps_num,
            fps_den=fps_den,
            video_codec=video.get("codec_name"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaInvalid("ffprobe returned incomplete moving style sample metadata") from exc


@dataclass(frozen=True)
class PersistedDemandAsset:
    descriptor: AssetDescriptor
    sheet: AssetSheet
    reused: bool


@dataclass(frozen=True)
class PreparedReferenceSet:
    assets: list[PersistedDemandAsset]
    forecast_micro_usd: int


class V2ReferenceRepository:
    """Durable V2 document and private asset repository for the references lane."""

    def __init__(self, db: Database, store: ObjectStore | None) -> None:
        self._db = db
        self._store = store

    @staticmethod
    def _asset_id(cache_key: str) -> UUID:
        return _deterministic_uuid("demand-asset", cache_key)

    @staticmethod
    def _sheet_id(demand: AssetDemand) -> UUID:
        return _deterministic_uuid(
            "asset-sheet", f"{demand.role}:{demand.subject_id}:{demand.view_name}"
        )

    def load_cached(self, demand: AssetDemand) -> PersistedDemandAsset | None:
        """Load the exact content-addressed asset/document pair after a restart."""
        asset_id = self._asset_id(demand.cache_key)
        with self._db.transaction(readonly=True) as tx:
            try:
                descriptor = get_asset(tx, asset_id)
            except NotFound:
                return None
            row = tx.fetchone(
                "SELECT payload FROM v2_contract_documents WHERE contract_type = 'AssetSheet' "
                "AND payload->>'asset_id' = %s ORDER BY version DESC LIMIT 1",
                (str(asset_id),),
            )
            if row is None:
                raise Conflict(
                    "cached asset has no current typed AssetSheet", asset_id=str(asset_id)
                )
            sheet = AssetSheet.model_validate(row["payload"])
        if not self._store.verify(descriptor.object_key, descriptor.sha256):
            raise Conflict(
                "cached reference bytes failed hash verification", asset_id=str(asset_id)
            )
        if sheet.asset_sha256 != descriptor.sha256 or sheet.asset_version != descriptor.version:
            raise Conflict(
                "cached AssetSheet does not match the exact asset row", asset_id=str(asset_id)
            )
        if demand.role == "style" and demand.view_name == "moving_sample":
            if (
                descriptor.asset_kind is not AssetKind.VIDEO
                or descriptor.media is None
                or not descriptor.media.has_video
                or descriptor.media.duration_ms <= 0
                or sheet.view_name != "moving_sample"
            ):
                raise Conflict("cached moving style sample is not a measured video asset")
        return PersistedDemandAsset(descriptor, sheet, True)

    def load_mock(self, demand: AssetDemand) -> MockAsset | None:
        persisted = self.load_cached(demand)
        if persisted is None:
            return None
        payload = self._store.get_bytes(persisted.descriptor.object_key)
        return MockAsset(
            cache_key=demand.cache_key,
            payload=payload,
            sha256=sha256(payload).hexdigest(),
        )

    def prepare_demands(
        self,
        demands: Sequence[AssetDemand],
        *,
        episode_id: UUID,
        season_id: UUID,
        now: datetime,
        episode_cap_micro_usd: int,
        current_spend_micro_usd: int,
        resolve_current: Callable[[str, object, str], RightsRecord | None],
        territories: list[str],
        reserve: Callable[[AssetDemand], None],
        cached_allocation_micro_usd: Mapping[str, int],
        already_allocated_cache_keys: set[str] | None = None,
        allocate_cached: Callable[[AssetDemand, int], None] | None = None,
        generator: Callable[[AssetDemand], bytes] | None = None,
    ) -> PreparedReferenceSet:
        """Resolve cache, rights, budget, generation and durable typed sheet output."""
        cached: dict[str, MockAsset] = {}
        for demand in demands:
            hit = self.load_mock(demand)
            if hit is not None:
                cached[demand.cache_key] = hit
        generated, forecast = generate_offline_missing(
            demands,
            cache=cached,
            episode_cap_micro_usd=episode_cap_micro_usd,
            current_spend_micro_usd=current_spend_micro_usd,
            at=now,
            resolve_current=resolve_current,
            territories=territories,
            reserve=reserve,
            cached_allocation_micro_usd=cached_allocation_micro_usd,
            already_allocated_cache_keys=already_allocated_cache_keys,
            allocate_cached=allocate_cached,
            generator=generator,
        )
        generated_by_key = {asset.cache_key: asset for asset in generated}
        results: list[PersistedDemandAsset] = []
        for demand in demands:
            if demand.cache_key in cached:
                hit = self.load_cached(demand)
                if hit is None:
                    raise Conflict("reference cache disappeared during preparation")
                results.append(hit)
            else:
                result = self.persist_generated(
                    demand,
                    generated_by_key[demand.cache_key],
                    episode_id=episode_id,
                    season_id=season_id,
                    now=now,
                )
                results.append(result)
        return PreparedReferenceSet(results, forecast)

    def persist_generated(
        self,
        demand: AssetDemand,
        generated: MockAsset,
        *,
        episode_id: UUID,
        season_id: UUID,
        now: datetime,
    ) -> PersistedDemandAsset:
        """Write fake bytes, V1 AssetDescriptor and V2 AssetSheet atomically in metadata."""
        if generated.cache_key != demand.cache_key or generated.provenance != "OFFLINE_MOCK":
            raise SchemaInvalid("references lane accepts only matching labeled offline mock output")
        instant = _aware(now)
        digest = sha256(generated.payload).hexdigest()
        if digest != generated.sha256:
            raise Conflict("generated reference bytes do not match their output hash")
        cached = self.load_cached(demand)
        if cached is not None:
            if self._store.get_bytes(cached.descriptor.object_key) != generated.payload:
                raise Conflict("deterministic cache key returned different mock bytes")
            return cached
        asset_id = self._asset_id(demand.cache_key)
        object_key = f"v2/references/{demand.cache_key}.bin"
        moving_sample = demand.role == "style" and demand.view_name == "moving_sample"
        media = _probe_video_bytes(generated.payload) if moving_sample else None
        media_type = "video/mp4" if moving_sample else "application/octet-stream"
        stored = self._store.put_bytes(object_key, generated.payload, media_type=media_type)
        if stored.sha256 != digest:
            raise Conflict("private store returned a different reference hash")
        descriptor = AssetDescriptor(
            asset_id=asset_id,
            asset_kind=(
                AssetKind.VIDEO
                if moving_sample
                else AssetKind.IMAGE
                if demand.role != "voice"
                else AssetKind.OTHER
            ),
            object_key=object_key,
            sha256=digest,
            size_bytes=len(generated.payload),
            media_type=stored.media_type,
            media=media,
            state=AssetState.PROVISIONAL,
            provenance=Provenance.FAKE_SYNTHETIC,
            episode_id=episode_id,
            season_id=season_id,
            version=1,
            license_refs=[demand.rights.rights_route_id],
            created_at=instant,
        )
        sheet = AssetSheet.seal(
            record_id=self._sheet_id(demand),
            version=1,
            created_at=instant,
            updated_at=instant,
            valid_from=instant,
            validity_from=instant,
            asset_role=demand.role,
            subject_id=demand.subject_id,
            asset_id=asset_id,
            asset_version=descriptor.version,
            asset_sha256=digest,
            view_name=demand.view_name,
            rights=demand.rights,
        )
        with self._db.transaction() as tx:
            descriptor = register_asset(tx, descriptor, generation_key=demand.cache_key)
            sheet = self.persist_document(tx, sheet)
        return PersistedDemandAsset(descriptor, sheet, False)

    def persist_document[T](self, tx, record: T) -> T:
        """Append a typed V2 record version and return the canonical persisted version."""
        from microdrama.contracts.v2 import V2Record

        if not isinstance(record, V2Record):
            raise SchemaInvalid("only frozen V2 records can be persisted here")
        verify_v2_record_hash(record)
        contract_type = type(record).__name__
        payload = record.model_dump(mode="json")
        current = tx.fetchone(
            "SELECT version, payload, payload_sha256 FROM v2_contract_documents "
            "WHERE contract_type = %s AND record_id = %s AND current FOR UPDATE",
            (contract_type, record.record_id),
        )
        if current is not None:
            if canonical_hash(current["payload"]) == current["payload_sha256"]:
                saved = type(record).model_validate(current["payload"])
                if saved == record:
                    return saved
            next_version = int(current["version"]) + 1
            tx.execute(
                "UPDATE v2_contract_documents SET current = false "
                "WHERE contract_type = %s AND record_id = %s AND current",
                (contract_type, record.record_id),
            )
            payload = record.model_dump(mode="python")
            payload["version"] = next_version
            record = type(record).seal(**payload)
            payload = record.model_dump(mode="json")
        else:
            previous_version = tx.fetchval(
                "SELECT max(version) FROM v2_contract_documents "
                "WHERE contract_type = %s AND record_id = %s",
                (contract_type, record.record_id),
            )
            if previous_version is not None:
                payload = record.model_dump(mode="python")
                payload["version"] = int(previous_version) + 1
                record = type(record).seal(**payload)
                payload = record.model_dump(mode="json")
        rights = getattr(record, "rights", None)
        if rights is None and getattr(record, "outfits", None):
            rights = record.outfits[0].rights
        rights_route_id = rights.rights_route_id if rights is not None else None
        rights_version = rights.rights_version if rights is not None else None
        tx.execute(
            "INSERT INTO v2_contract_documents "
            "(contract_type, record_id, version, payload, payload_sha256, rights_route_id, "
            "rights_version, valid_from, valid_until, current) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)",
            (
                contract_type,
                record.record_id,
                record.version,
                jsonb(payload),
                canonical_hash(record),
                rights_route_id,
                rights_version,
                record.valid_from,
                record.valid_until,
            ),
        )
        return record

    def persist_companion_records[T](self, records: Sequence[T]) -> list[T]:
        """Persist WardrobeBible, assignments, StateEvent, PropSheet, LocationLayout and StyleBible.

        Records are produced by their frozen typed contracts from approved story and
        layout data. This routine supplies only durable versioning and readback.
        """
        with self._db.transaction() as tx:
            return [self.persist_document(tx, record) for record in records]

    def make_prop_sheet(
        self,
        *,
        prop_id: str,
        asset: PersistedDemandAsset,
        purpose: str,
        visual_anchor: str,
        dimensions: str,
        known_states: list[str],
        owner_character_id: str | None,
        now: datetime,
        text_layer_sha256: str | None = None,
    ) -> PropSheet:
        if asset.sheet.asset_role != "prop" or asset.sheet.subject_id != prop_id:
            raise Conflict("prop sheet source asset has a different typed role or owner")
        return seal_reference_record(
            PropSheet,
            f"{prop_id}:{asset.sheet.asset_id}:{asset.sheet.asset_version}",
            now,
            prop_id=prop_id,
            purpose=purpose,
            visual_anchor=visual_anchor,
            owner_character_id=owner_character_id,
            dimensions=dimensions,
            known_states=known_states,
            text_layer_sha256=text_layer_sha256,
            asset_id=asset.sheet.asset_id,
            asset_version=asset.sheet.asset_version,
            asset_sha256=asset.sheet.asset_sha256,
            rights=asset.sheet.rights,
            asset_valid_until=asset.sheet.validity_until,
        )

    def make_location_layout(
        self,
        *,
        location_id: str,
        empty_plate: PersistedDemandAsset,
        entrance_ids: list[str],
        camera_zones: list[str],
        light_states: list[str],
        prop_ownership: dict[str, str],
        now: datetime,
    ) -> LocationLayout:
        if (
            empty_plate.sheet.asset_role != "location"
            or empty_plate.sheet.subject_id != location_id
        ):
            raise Conflict("location layout source asset has a different typed role or owner")
        return seal_reference_record(
            LocationLayout,
            f"{location_id}:{empty_plate.sheet.asset_id}:{empty_plate.sheet.asset_version}",
            now,
            location_id=location_id,
            geometry_sha256=empty_plate.sheet.asset_sha256,
            entrance_ids=entrance_ids,
            camera_zones=camera_zones,
            light_states=light_states,
            prop_ownership=prop_ownership,
            rights=empty_plate.sheet.rights,
        )

    def make_style_bible(
        self,
        *,
        season_id: UUID,
        moving_sample: PersistedDemandAsset,
        medium: str,
        realism: str,
        palette: list[str],
        lighting_language: str,
        lens_and_movement: str,
        material_rules: list[str],
        typography_rules: list[str],
        subtitle_safe_top_bp: int,
        subtitle_safe_bottom_bp: int,
        sound_motifs: list[str],
        exclusions: list[str],
        now: datetime,
    ) -> StyleBible:
        if moving_sample.sheet.asset_role != "style":
            raise Conflict("moving style sample must resolve to a style-role asset")
        if (
            moving_sample.sheet.view_name != "moving_sample"
            or moving_sample.descriptor.asset_kind is not AssetKind.VIDEO
            or moving_sample.descriptor.media is None
            or not moving_sample.descriptor.media.has_video
        ):
            raise Conflict("StyleBible moving sample must be a measured video AssetSheet")
        return seal_reference_record(
            StyleBible,
            f"{season_id}:{moving_sample.sheet.asset_id}:{moving_sample.sheet.asset_version}",
            now,
            season_id=season_id,
            medium=medium,
            realism=realism,
            palette=palette,
            lighting_language=lighting_language,
            lens_and_movement=lens_and_movement,
            material_rules=material_rules,
            typography_rules=typography_rules,
            subtitle_safe_top_bp=subtitle_safe_top_bp,
            subtitle_safe_bottom_bp=subtitle_safe_bottom_bp,
            sound_motifs=sound_motifs,
            exclusions=exclusions,
            moving_sample_asset_id=moving_sample.sheet.asset_id,
            moving_sample_sha256=moving_sample.sheet.asset_sha256,
            rights=moving_sample.sheet.rights,
        )


def validate_episode_reference_state(
    pack: EpisodePack,
    prop_sheets: Sequence[PropSheet],
    location_layouts: Sequence[LocationLayout],
    state_events: Sequence[StateEvent],
) -> None:
    """Check key prop, holder/hand and location light state against typed records."""
    props = {sheet.prop_id: sheet for sheet in prop_sheets}
    layouts = {layout.location_id: layout for layout in location_layouts}
    if len(props) != len(prop_sheets) or len(layouts) != len(location_layouts):
        raise Conflict("duplicate prop sheet or location layout")
    character_ids = {character.character_id for character in pack.character_logic}
    scenes_by_id = {scene.scene_id: scene for scene in pack.scenes}
    if len(scenes_by_id) != len(pack.scenes):
        raise Conflict("duplicate episode scene identifier")
    for scene in pack.scenes:
        layout = layouts.get(scene.location_id)
        if layout is None:
            raise SchemaInvalid(f"scene {scene.scene_id} has no location layout")
        for prop_id in scene.prop_ids:
            sheet = props.get(prop_id)
            if sheet is None:
                raise SchemaInvalid(f"scene key prop {prop_id} has no prop sheet")
            declared_owner = layout.prop_ownership.get(prop_id)
            if declared_owner != sheet.owner_character_id:
                raise Conflict(
                    f"prop ownership disagrees for {prop_id}",
                    layout_owner=declared_owner,
                    sheet_owner=sheet.owner_character_id,
                )
        _require_scene_state_coverage(scene, scene.prop_ids)
        for state in [
            *scene.state_in,
            *(state for beat in scene.beats for state in beat.state_in),
            *(state for beat in scene.beats for state in beat.state_out),
            *scene.state_out,
        ]:
            _validate_scene_state_value(
                state, scene.prop_ids, props, scene.location_id, layout, character_ids
            )
        for snapshot in [
            scene.state_in,
            scene.state_out,
            *(beat.state_in for beat in scene.beats),
            *(beat.state_out for beat in scene.beats),
        ]:
            _validate_holder_hand_snapshot(snapshot, scene.prop_ids)
    if state_events:
        if any(event.episode_id != pack.episode_id for event in state_events):
            raise Conflict("state event belongs to another episode")
        for event in state_events:
            scene = scenes_by_id.get(event.scene_id)
            if scene is None:
                raise Conflict("state event points to an unknown scene", scene_id=event.scene_id)
            _validate_scene_state_value(
                StateValue(entity_id=event.entity_id, field=event.field, value=event.before),
                scene.prop_ids,
                props,
                scene.location_id,
                layouts[scene.location_id],
                character_ids,
            )
            _validate_scene_state_value(
                StateValue(entity_id=event.entity_id, field=event.field, value=event.after),
                scene.prop_ids,
                props,
                scene.location_id,
                layouts[scene.location_id],
                character_ids,
            )
        validate_state_event_chain(list(state_events))
        _validate_event_scene_boundaries(state_events, scenes_by_id)
        for scene_id, scene in scenes_by_id.items():
            _validate_event_holder_hand_intervals(
                scene, [event for event in state_events if event.scene_id == scene_id]
            )


def resolve_shot_prop_bindings(shot, prompt_manifest, prop_sheets, *, at):
    """Resolve requested shot props to exact current typed PROP assets.

    The returned asset IDs are suitable for the legacy flat render request; the
    returned hashes remain attached to the frozen prompt manifest for audit.
    This is deliberately a pre-dispatch check and has no persistence/provider effects.
    """
    from microdrama.contracts.v2 import (
        PromptManifest,
        PropSheet,
        ReferenceRole,
        ShotReferenceBinding,
    )

    if not isinstance(prompt_manifest, PromptManifest):
        raise SchemaInvalid("V2 prop preflight requires a typed PromptManifest")
    sheets = {}
    for sheet in prop_sheets:
        if not isinstance(sheet, PropSheet):
            raise SchemaInvalid("V2 prop preflight requires typed PropSheet records")
        if sheet.prop_id in sheets:
            raise Conflict("duplicate PropSheet for requested shot", prop_id=sheet.prop_id)
        sheets[sheet.prop_id] = sheet
    bindings = {
        binding.subject_id: binding
        for binding in prompt_manifest.bindings
        if binding.role is ReferenceRole.PROP
    }
    if len(bindings) != sum(b.role is ReferenceRole.PROP for b in prompt_manifest.bindings):
        raise Conflict("duplicate semantic PROP binding in prompt manifest")
    requested = set(shot.prop_ids)
    bound = set(bindings)
    if requested != bound:
        raise SchemaInvalid(
            "shot prop IDs and semantic PROP bindings must match exactly",
            missing=sorted(requested - bound),
            unrelated=sorted(bound - requested),
        )
    assets = []
    source_hashes = set(prompt_manifest.source_hashes)
    for prop_id in sorted(requested):
        sheet = sheets.get(prop_id)
        binding = bindings[prop_id]
        if sheet is None:
            raise SchemaInvalid(f"requested prop {prop_id} has no current PropSheet")
        if not isinstance(binding, ShotReferenceBinding) or (
            binding.asset_id,
            binding.asset_version,
            binding.asset_sha256,
        ) != (sheet.asset_id, sheet.asset_version, sheet.asset_sha256):
            raise SchemaInvalid(f"PROP binding for {prop_id} does not match its exact PropSheet")
        if not sheet.valid_from <= at or (
            sheet.valid_until is not None and at >= sheet.valid_until
        ):
            raise SchemaInvalid(f"PropSheet for {prop_id} is stale at dispatch")
        if sheet.asset_valid_until is not None and at >= sheet.asset_valid_until:
            raise SchemaInvalid(f"prop asset for {prop_id} is retired at dispatch")
        if not binding.valid_from <= at or (
            binding.valid_until is not None and at >= binding.valid_until
        ):
            raise SchemaInvalid(f"PROP binding for {prop_id} is stale at dispatch")
        if sheet.asset_sha256 not in source_hashes or binding.asset_sha256 not in source_hashes:
            raise SchemaInvalid(f"prompt source hashes omit the exact PROP asset for {prop_id}")
        assets.append(sheet.asset_id)
    return tuple(assets), tuple(sorted(source_hashes))


def build_prop_prompt_manifest(
    db: Database,
    *,
    episode_id: UUID,
    manifest_version: int,
    shot,
    prompt_text: str,
    at: datetime,
):
    """Build a shot prompt from current V2 prop, wardrobe and reference records.

    The writer's V1 shot supplies requested prop IDs and dialogue/location context.
    PropSheets, outfit assignments, identity references and location references are
    read from the current V2 document revisions; missing or ambiguous rows fail closed.
    """
    from microdrama.contracts.v2 import (
        PromptManifest,
        PropSheet,
        ReferenceRole,
        SceneWardrobeAssignment,
        ShotReferenceBinding,
        WardrobeBible,
    )

    instant = _aware(at)
    with db.transaction(readonly=True) as tx:
        prop_rows = tx.fetchall(
            "SELECT payload FROM v2_contract_documents WHERE contract_type = 'PropSheet' "
            "AND current AND payload->>'prop_id' = ANY(%s)",
            (list(shot.prop_ids),),
        )
        assignment_rows = tx.fetchall(
            "SELECT payload FROM v2_contract_documents "
            "WHERE contract_type = 'SceneWardrobeAssignment' AND current "
            "AND payload->>'episode_id' = %s AND payload->>'scene_id' = %s",
            (str(episode_id), shot.scene_id),
        )
        binding_rows = tx.fetchall(
            "SELECT payload FROM v2_contract_documents "
            "WHERE contract_type = 'ShotReferenceBinding' AND current"
        )
        bible_rows: dict[UUID, dict] = {}
        assignments = [
            SceneWardrobeAssignment.model_validate(row["payload"]) for row in assignment_rows
        ]
        for assignment in assignments:
            row = tx.fetchone(
                "SELECT payload FROM v2_contract_documents WHERE contract_type = 'WardrobeBible' "
                "AND record_id = %s AND current",
                (assignment.wardrobe_bible_id,),
            )
            if row is None:
                raise SchemaInvalid("outfit assignment has no current WardrobeBible")
            bible_rows[assignment.wardrobe_bible_id] = row["payload"]

    prop_sheets = [PropSheet.model_validate(row["payload"]) for row in prop_rows]
    assignments_by_character = {item.character_id: item for item in assignments}
    if len(assignments_by_character) != len(assignments):
        raise Conflict("duplicate current wardrobe assignment for the shot scene")
    binding_by_key = {}
    for row in binding_rows:
        binding = ShotReferenceBinding.model_validate(row["payload"])
        key = (binding.role, binding.subject_id)
        if key in binding_by_key:
            raise Conflict(
                "multiple current semantic reference bindings", role=key[0].value, subject=key[1]
            )
        binding_by_key[key] = binding

    bindings: list[ShotReferenceBinding] = []
    source_hashes = {canonical_hash(shot)}
    for prop_id in sorted(set(shot.prop_ids)):
        sheets = [sheet for sheet in prop_sheets if sheet.prop_id == prop_id]
        if len(sheets) != 1:
            raise SchemaInvalid(f"prop {prop_id} must have one current typed PropSheet")
        sheet = sheets[0]
        verify_v2_record_hash(sheet)
        if not sheet.valid_from <= instant or (
            sheet.valid_until is not None and instant >= sheet.valid_until
        ):
            raise SchemaInvalid(f"PropSheet for {prop_id} is stale at dispatch")
        if sheet.asset_valid_until is not None and instant >= sheet.asset_valid_until:
            raise SchemaInvalid(f"prop asset for {prop_id} is retired at dispatch")
        binding = ShotReferenceBinding.seal(
            record_id=uuid5(
                NAMESPACE_URL,
                f"render-prop-binding:{episode_id}:{shot.shot_id}:{prop_id}:{sheet.asset_version}",
            ),
            version=1,
            created_at=instant,
            updated_at=instant,
            valid_from=max(sheet.valid_from, instant),
            role=ReferenceRole.PROP,
            subject_id=prop_id,
            asset_id=sheet.asset_id,
            asset_version=sheet.asset_version,
            asset_sha256=sheet.asset_sha256,
            rights=sheet.rights,
        )
        bindings.append(binding)
        source_hashes.add(sheet.asset_sha256)
        source_hashes.add(sheet.content_sha256)

    visible_characters = set(shot.speaker_ids) | set(assignments_by_character)
    if not visible_characters:
        raise SchemaInvalid(
            "prop prompt has no current scene wardrobe/visible-character assignment"
        )
    for character_id in sorted(visible_characters):
        identity = binding_by_key.get((ReferenceRole.CHARACTER_IDENTITY, character_id))
        assignment = assignments_by_character.get(character_id)
        if identity is None or assignment is None:
            raise SchemaInvalid(
                f"prop prompt lacks current identity or outfit assignment for {character_id}"
            )
        verify_v2_record_hash(assignment)
        if not assignment.valid_from <= instant or (
            assignment.valid_until is not None and instant >= assignment.valid_until
        ):
            raise SchemaInvalid(f"wardrobe assignment for {character_id} is stale at dispatch")
        bible = WardrobeBible.model_validate(bible_rows[assignment.wardrobe_bible_id])
        verify_v2_record_hash(bible)
        if bible.version != assignment.wardrobe_bible_version:
            raise SchemaInvalid(f"wardrobe assignment for {character_id} is stale")
        outfit = next(
            (
                item
                for item in bible.outfits
                if item.outfit_id == assignment.outfit_id
                and item.version == assignment.outfit_version
            ),
            None,
        )
        if outfit is None or (
            outfit.asset_id,
            outfit.asset_version,
            outfit.asset_sha256,
        ) != (assignment.asset_id, assignment.asset_version, assignment.asset_sha256):
            raise SchemaInvalid(f"wardrobe assignment for {character_id} disagrees with its bible")
        location = binding_by_key.get((ReferenceRole.LOCATION, shot.location_id))
        if location is None:
            raise SchemaInvalid(
                f"prop prompt lacks current location reference for {shot.location_id}"
            )
        bindings.extend(
            [
                identity,
                ShotReferenceBinding.seal(
                    record_id=uuid5(
                        NAMESPACE_URL,
                        f"render-outfit-binding:{episode_id}:{shot.shot_id}:{character_id}:{assignment.asset_version}",
                    ),
                    version=1,
                    created_at=instant,
                    updated_at=instant,
                    valid_from=max(assignment.valid_from, instant),
                    role=ReferenceRole.OUTFIT,
                    subject_id=character_id,
                    asset_id=assignment.asset_id,
                    asset_version=assignment.asset_version,
                    asset_sha256=assignment.asset_sha256,
                    rights=assignment.rights,
                ),
                location,
            ]
        )
        source_hashes.update(
            {
                identity.asset_sha256,
                identity.content_sha256,
                assignment.asset_sha256,
                assignment.content_sha256,
                location.asset_sha256,
                location.content_sha256,
            }
        )
    unique_bindings = {(item.role, item.subject_id): item for item in bindings}
    prompt = PromptManifest.seal(
        record_id=uuid5(
            NAMESPACE_URL,
            f"render-prompt:{episode_id}:{shot.shot_id}:manifest{manifest_version}",
        ),
        version=1,
        created_at=instant,
        updated_at=instant,
        valid_from=instant,
        episode_id=episode_id,
        shot_id=shot.shot_id,
        shot_sequence=shot.sequence,
        shot_duration_ms=shot.target_duration_ms,
        prompt_text=prompt_text,
        bindings=list(unique_bindings.values()),
        source_hashes=sorted(source_hashes),
    )
    return prompt, prop_sheets


def _require_scene_state_coverage(scene: EpisodeScene, prop_ids: Sequence[str]) -> None:
    for boundary_name, states in (("state_in", scene.state_in), ("state_out", scene.state_out)):
        declared = {(state.entity_id, state.field) for state in states}
        for prop_id in prop_ids:
            has_holder = any(
                (prop_id, field) in declared for field in ("holder_character_id", "holder")
            )
            has_hand = any((prop_id, field) in declared for field in ("hand", "holder_hand"))
            if not has_holder or not has_hand:
                raise SchemaInvalid(
                    f"scene {scene.scene_id} {boundary_name} must state prop {prop_id} holder and hand"
                )
        if (scene.location_id, "light_state") not in declared and (
            scene.location_id,
            "light",
        ) not in declared:
            raise SchemaInvalid(
                f"scene {scene.scene_id} {boundary_name} must state the location light condition"
            )


def _validate_scene_state_value(
    state: StateValue,
    scene_prop_ids: Sequence[str],
    props: Mapping[str, PropSheet],
    location_id: str,
    layout: LocationLayout,
    character_ids: set[str],
) -> None:
    if state.entity_id in scene_prop_ids:
        sheet = props[state.entity_id]
        if state.field in {"holder", "holder_character_id"} and state.value is not None:
            if not isinstance(state.value, str) or state.value not in character_ids:
                raise SchemaInvalid(f"prop {state.entity_id} holder must name a pack character")
        if state.field in {"hand", "holder_hand"}:
            if state.value not in {None, "left", "right", "both", "none"}:
                raise SchemaInvalid(f"prop {state.entity_id} hand state is unsupported")
        if state.field in {"state", "prop_state"} and state.value not in sheet.known_states:
            raise SchemaInvalid(f"prop {state.entity_id} state is absent from its PropSheet")
    elif state.field in {"light", "light_state"}:
        if state.entity_id != location_id:
            raise SchemaInvalid("light-state value must target the scene's exact location")
        if state.value not in layout.light_states:
            raise SchemaInvalid(f"location {location_id} light state is absent from its layout")
    elif state.field in {"holder", "holder_character_id", "hand", "holder_hand"}:
        raise SchemaInvalid("prop holder/hand state must target a visible key prop")


def _validate_holder_hand_snapshot(states: Sequence[StateValue], prop_ids: Sequence[str]) -> None:
    values = {(state.entity_id, state.field): state.value for state in states}
    for prop_id in prop_ids:
        holder_key = next(
            (
                key
                for key in ((prop_id, "holder_character_id"), (prop_id, "holder"))
                if key in values
            ),
            None,
        )
        hand_key = next(
            (key for key in ((prop_id, "holder_hand"), (prop_id, "hand")) if key in values),
            None,
        )
        if holder_key is not None and hand_key is not None:
            holder, hand = values[holder_key], values[hand_key]
            if holder is None and hand not in (None, "none"):
                raise Conflict(f"prop {prop_id} has a hand assigned without a holder")
            if holder is not None and hand == "none":
                raise Conflict(f"prop {prop_id} has a holder but no hand assignment")


def _validate_event_holder_hand_intervals(
    scene: EpisodeScene, events: Sequence[StateEvent]
) -> None:
    boundaries = sorted({event.effective_from_ms for event in events})
    for instant in boundaries:
        values = {(state.entity_id, state.field): state.value for state in scene.state_in}
        for event in events:
            if event.effective_from_ms <= instant < event.effective_until_ms:
                values[(event.entity_id, event.field)] = event.after
        snapshot = [
            StateValue(entity_id=entity, field=field, value=value)
            for (entity, field), value in values.items()
        ]
        _validate_holder_hand_snapshot(snapshot, scene.prop_ids)


def _validate_event_scene_boundaries(
    state_events: Sequence[StateEvent], scenes: Mapping[str, EpisodeScene]
) -> None:
    grouped: dict[tuple[str, str, str], list[StateEvent]] = {}
    for event in state_events:
        grouped.setdefault((event.scene_id, event.entity_id, event.field), []).append(event)
    for (scene_id, entity_id, field), events in grouped.items():
        scene = scenes[scene_id]
        baseline = next(
            (
                value.value
                for value in scene.state_in
                if (value.entity_id, value.field) == (entity_id, field)
            ),
            None,
        )
        final = next(
            (
                value.value
                for value in scene.state_out
                if (value.entity_id, value.field) == (entity_id, field)
            ),
            None,
        )
        ordered = sorted(events, key=lambda event: (event.effective_from_ms, event.sequence))
        if any(value.entity_id == entity_id and value.field == field for value in scene.state_in):
            if ordered[0].before != baseline:
                raise Conflict(
                    "state event before value contradicts scene state_in",
                    scene_id=scene_id,
                    entity_id=entity_id,
                    field=field,
                )
        if any(value.entity_id == entity_id and value.field == field for value in scene.state_out):
            if ordered[-1].after != final:
                raise Conflict(
                    "state event after value contradicts scene state_out",
                    scene_id=scene_id,
                    entity_id=entity_id,
                    field=field,
                )


def targeted_invalidation(
    changed_dependency_ids: Sequence[str], dependency_graph: Mapping[str, Sequence[str]]
) -> list[str]:
    """Return only transitive dependents of changed sources, in stable order."""
    reverse: dict[str, set[str]] = {}
    for dependent, sources in dependency_graph.items():
        for source in sources:
            reverse.setdefault(source, set()).add(dependent)
    invalidated: set[str] = set()
    pending = list(changed_dependency_ids)
    visited = set(pending)
    while pending:
        source = pending.pop()
        for dependent in reverse.get(source, set()):
            if dependent not in visited:
                visited.add(dependent)
                invalidated.add(dependent)
                pending.append(dependent)
    return sorted(invalidated)


def outfit_for_scene_time(
    assignment: SceneWardrobeAssignment,
    bible: WardrobeBible,
    state_events: Sequence[StateEvent],
    *,
    at_ms: int,
    now: datetime,
    resolve_current: Callable[[str, object, str], RightsRecord | None],
    territories: list[str],
) -> OutfitDefinition:
    """Resolve an explicit in-scene wardrobe event to its exact bible outfit."""
    if type(at_ms) is not int or at_ms < 0:
        raise SchemaInvalid("scene wardrobe resolution time must be a non-negative integer")
    validate_wardrobe_assignment(assignment, bible)
    relevant = [
        event
        for event in state_events
        if event.episode_id == assignment.episode_id
        and event.scene_id == assignment.scene_id
        and event.entity_id == assignment.character_id
        and event.field == "outfit_id"
    ]
    if relevant:
        validate_state_event_chain(relevant)
    active = [
        event for event in relevant if event.effective_from_ms <= at_ms < event.effective_until_ms
    ]
    if len(active) > 1:
        raise Conflict("multiple wardrobe state events overlap this shot interval")
    selected_id = str(active[0].after) if active else assignment.outfit_id
    selected = next((outfit for outfit in bible.outfits if outfit.outfit_id == selected_id), None)
    if selected is None:
        raise SchemaInvalid(
            f"wardrobe state selects outfit {selected_id} absent from the exact bible"
        )
    if selected.story_day_from > assignment.story_day or (
        selected.story_day_until is not None and assignment.story_day > selected.story_day_until
    ):
        raise SchemaInvalid("wardrobe state selects an outfit outside its story-day validity")
    if assignment.setting not in selected.setting_tags:
        raise SchemaInvalid("wardrobe state selects an outfit not approved for the scene setting")
    _current_rights(selected.rights, resolve_current, at=_aware(now), territories=territories)
    return selected


def plan_reference_demands(
    pack: EpisodePack,
    scope: SeasonScope,
    wardrobe_assignments: Sequence[SceneWardrobeAssignment],
    *,
    grants: Mapping[tuple[str, str], RightsGrant],
    model_config_ref: str,
    view_requirements: Mapping[tuple[str, str], Sequence[str]],
    estimated_cost_micro_usd: Mapping[str, int],
    dimensions: tuple[int, int] = (512, 512),
) -> list[AssetDemand]:
    """Plan only cast, outfits, props, locations and style used by this episode.

    ``view_requirements`` is supplied by the approved camera/asset plan. It makes
    angle count explicit and prevents the historical six-images-for-everything
    behavior. Silent visible cast are included by construction.
    """
    validate_pack_scope(pack, scope)
    characters = {item.character_id: item for item in scope.characters}
    visible = sorted({cid for scene in pack.scenes for cid in scene.visible_character_ids})
    locations = sorted({scene.location_id for scene in pack.scenes})
    props = sorted({prop for scene in pack.scenes for prop in scene.prop_ids})
    outfit_subjects = sorted({(item.character_id, item.outfit_id) for item in wardrobe_assignments})
    subjects: list[tuple[str, str, str]] = []
    for character_id in visible:
        brief = characters.get(character_id)
        if brief is None:
            raise SchemaInvalid(f"visible character {character_id} is absent from approved scope")
        subjects.append(("character_identity", character_id, brief.description))
        subjects.append(("voice", character_id, brief.voice_direction))
    for character_id, outfit_id in outfit_subjects:
        subjects.append(
            ("outfit", f"{character_id}:{outfit_id}", f"wardrobe {outfit_id} for {character_id}")
        )
    subjects.extend(("prop", prop, f"prop sheet for {prop}") for prop in props)
    subjects.extend(
        ("location", location, f"empty plate and geometry for {location}") for location in locations
    )
    subjects.append(
        ("style", str(pack.season_id), "series look bible and short moving style sample")
    )

    demands: dict[str, AssetDemand] = {}
    for role, subject_id, prompt in subjects:
        grant = grants.get((role, subject_id))
        if grant is None:
            raise SchemaInvalid(f"missing rights grant for {role}:{subject_id}")
        views = tuple(view_requirements.get((role, subject_id), ()))
        if role == "style" and "moving_sample" not in views:
            views = (*views, "moving_sample")
        if not views:
            raise SchemaInvalid(f"no camera-driven view requirements for {role}:{subject_id}")
        cost = estimated_cost_micro_usd.get(role)
        if type(cost) is not int or cost < 0:
            raise SchemaInvalid(f"missing or invalid forecast cost for role {role}")
        for view_name in sorted(set(views)):
            compiled = f"{prompt}; required view: {view_name}"
            key = demand_key(
                asset_role=role,
                subject_id=subject_id,
                view_name=view_name,
                prompt=compiled,
                model_config_ref=model_config_ref,
                grant=grant,
                dimensions=dimensions,
                seed=int(canonical_hash([role, subject_id, view_name])[:8], 16),
            )
            demands.setdefault(
                key,
                AssetDemand(
                    role,
                    subject_id,
                    view_name,
                    compiled,
                    key,
                    grant,
                    cost,
                    int(canonical_hash([role, subject_id, view_name])[:8], 16),
                ),
            )
    return [demands[key] for key in sorted(demands)]


def generate_offline_missing(
    demands: Sequence[AssetDemand],
    *,
    cache: Mapping[str, MockAsset],
    episode_cap_micro_usd: int,
    current_spend_micro_usd: int,
    at: datetime,
    resolve_current: Callable[[str, object, str], RightsRecord | None],
    territories: list[str],
    reserve: Callable[[AssetDemand], None],
    cached_allocation_micro_usd: Mapping[str, int],
    already_allocated_cache_keys: set[str] | None = None,
    allocate_cached: Callable[[AssetDemand, int], None] | None = None,
    generator: Callable[[AssetDemand], bytes] | None = None,
) -> tuple[list[MockAsset], int]:
    """Bound fake generation and reuse allocations before dispatch.

    A cached asset is never silently free: its source charge needs an explicit
    allocation basis unless this episode already recorded that allocation.
    """
    instant = _aware(at)
    all_unique = {demand.cache_key: demand for demand in demands}
    unique = {key: item for key, item in all_unique.items() if key not in cache}
    already_allocated = already_allocated_cache_keys or set()
    cached_to_allocate = {
        key: item
        for key, item in all_unique.items()
        if key in cache and key not in already_allocated
    }
    missing_allocations = set(cached_to_allocate) - set(cached_allocation_micro_usd)
    if missing_allocations:
        raise SchemaInvalid("cached reference needs an explicit source-cost allocation")
    reuse_costs = {key: cached_allocation_micro_usd[key] for key in cached_to_allocate}
    if any(type(amount) is not int or amount < 0 for amount in reuse_costs.values()):
        raise SchemaInvalid("cached reference allocation must be non-negative integer micro-USD")
    forecast = sum(item.estimated_micro_usd for item in unique.values()) + sum(reuse_costs.values())
    if current_spend_micro_usd + forecast > episode_cap_micro_usd:
        raise SchemaInvalid("reference forecast exceeds remaining episode allowance")
    # Resolve all current rights before the first reservation or generation call.
    for item in unique.values():
        _current_rights(item.rights, resolve_current, at=instant, territories=territories)
    for item in cached_to_allocate.values():
        _current_rights(item.rights, resolve_current, at=instant, territories=territories)
    for key, item in cached_to_allocate.items():
        if allocate_cached is not None:
            allocate_cached(item, reuse_costs[key])
    outputs: list[MockAsset] = []
    for item in unique.values():
        reserve(item)
        if generator is not None:
            payload = generator(item)
        elif item.role == "style" and item.view_name == "moving_sample":
            payload = make_offline_style_video()
        else:
            payload = item.cache_key.encode("ascii")
        outputs.append(
            MockAsset(
                cache_key=item.cache_key,
                payload=payload,
                sha256=sha256(payload).hexdigest(),
            )
        )
    return outputs, forecast


def _deterministic_uuid(namespace: str, semantic_key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://microdrama.invalid/{namespace}/{semantic_key}")


def seal_reference_record[T](
    record_type: type[T], semantic_key: str, now: datetime, **fields: object
) -> T:
    """Seal a frozen V2 reference/state record with stable identity and timestamps."""
    from microdrama.contracts.v2 import V2Record

    if not isinstance(record_type, type) or not issubclass(record_type, V2Record):
        raise SchemaInvalid("reference records must use a frozen V2 contract type")
    instant = _aware(now)
    fields.setdefault("valid_from", instant)
    return record_type.seal(
        record_id=_deterministic_uuid(record_type.__name__, semantic_key),
        version=1,
        created_at=instant,
        updated_at=instant,
        **fields,
    )


def _aware(value: datetime) -> UtcDateTime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaInvalid("reference planning requires a timezone-aware instant")
    return value


def validate_pack_scope(pack: EpisodePack, scope: SeasonScope) -> None:
    """Require the exact Gate-1-approved scope before deriving reference prompts."""
    scope_hash = canonical_hash(scope)
    if pack.approved_scope_hash != scope_hash:
        raise Conflict(
            "episode pack is not bound to the supplied Gate-1-approved scope",
            episode_scope_hash=pack.approved_scope_hash,
            approved_scope_hash=scope_hash,
        )


def _current_rights(
    grant: RightsGrant,
    resolve_current: Callable[[str, object, str], RightsRecord | None],
    *,
    at: UtcDateTime,
    territories: list[str],
) -> RightsRecord:
    try:
        return validate_current_rights_grant(grant, resolve_current, at=at, territories=territories)
    except ValueError as exc:
        raise SchemaInvalid(f"reference dispatch blocked by current rights: {exc}") from exc


def assign_scene_wardrobes(
    pack: EpisodePack,
    wardrobe_bibles: Sequence[WardrobeBible],
    *,
    at: datetime,
    resolve_current: Callable[[str, object, str], RightsRecord | None],
    territories: list[str],
    reuse_reasons: Mapping[tuple[str, int, str], str] | None = None,
) -> list[SceneWardrobeAssignment]:
    """Resolve one rights-current outfit per visible character in every scene.

    A changed story day prefers a different outfit. Reusing yesterday's outfit
    requires an explicit reason keyed by (character, day, setting).
    """
    instant = _aware(at)
    reasons = reuse_reasons or {}
    bibles: dict[str, WardrobeBible] = {}
    for bible in wardrobe_bibles:
        verify_v2_record_hash(bible)
        if bible.season_id != pack.season_id:
            raise Conflict("wardrobe bible belongs to a different season")
        if bible.character_id in bibles:
            raise Conflict(
                "duplicate wardrobe bible for character", character_id=bible.character_id
            )
        bibles[bible.character_id] = bible

    assignments: list[SceneWardrobeAssignment] = []
    previous: dict[str, tuple[int, str]] = {}
    for scene in sorted(
        pack.scenes, key=lambda item: (item.story_time.story_day, item.scene_number)
    ):
        day = scene.story_time.story_day
        # Wardrobe tags use the canonical location/setting identifier. StoryTime.setting
        # is descriptive prose in the frozen contract and is not an Identifier.
        setting = scene.location_id
        for character_id in scene.visible_character_ids:
            bible = bibles.get(character_id)
            if bible is None:
                raise SchemaInvalid(f"visible character {character_id} has no wardrobe bible")
            candidates = [
                outfit
                for outfit in bible.outfits
                if outfit.story_day_from <= day
                and (outfit.story_day_until is None or day <= outfit.story_day_until)
                and setting in outfit.setting_tags
            ]
            if not candidates:
                raise SchemaInvalid(
                    f"no eligible outfit for visible character {character_id} on day {day} in {setting}"
                )
            old = previous.get(character_id)
            reason = reasons.get((character_id, day, setting))
            if old is not None and old[0] < day:
                new_candidates = [outfit for outfit in candidates if outfit.outfit_id != old[1]]
                if new_candidates:
                    candidates = new_candidates
                elif old[1] in {outfit.outfit_id for outfit in candidates} and not reason:
                    raise SchemaInvalid(
                        f"next-day outfit reuse for {character_id} requires an explicit reuse reason"
                    )
            newest_by_outfit: dict[str, OutfitDefinition] = {}
            for candidate in candidates:
                existing = newest_by_outfit.get(candidate.outfit_id)
                if existing is None or candidate.version > existing.version:
                    newest_by_outfit[candidate.outfit_id] = candidate
            outfit = newest_by_outfit[sorted(newest_by_outfit)[0]]
            _current_rights(outfit.rights, resolve_current, at=instant, territories=territories)
            semantic = f"{pack.episode_id}:{scene.scene_id}:{character_id}:{outfit.outfit_id}:{outfit.version}"
            assignment = SceneWardrobeAssignment.seal(
                record_id=_deterministic_uuid("wardrobe-assignment", semantic),
                version=1,
                created_at=instant,
                updated_at=instant,
                valid_from=instant,
                episode_id=pack.episode_id,
                scene_id=scene.scene_id,
                character_id=character_id,
                story_day=day,
                setting=setting,
                wardrobe_bible_id=bible.record_id,
                wardrobe_bible_version=bible.version,
                outfit_id=outfit.outfit_id,
                outfit_version=outfit.version,
                asset_id=outfit.asset_id,
                asset_version=outfit.asset_version,
                asset_sha256=outfit.asset_sha256,
                reuse_reason=reason if old is not None and old[1] == outfit.outfit_id else None,
                rights=outfit.rights,
            )
            assignments.append(assignment)
            previous[character_id] = (day, outfit.outfit_id)
    return assignments


def demand_key(
    *,
    asset_role: str,
    subject_id: str,
    view_name: str,
    prompt: str,
    model_config_ref: str,
    grant: RightsGrant,
    dimensions: tuple[int, int],
    seed: int = 0,
    lineage_sha256: Sequence[str] = (),
) -> str:
    """Full semantic cache/cost key; rights route, subject and exact version are included."""
    return canonical_hash(
        {
            "asset_role": asset_role,
            "subject_id": subject_id,
            "view_name": view_name,
            "prompt": prompt,
            "model_config_ref": model_config_ref,
            "rights": {
                "route": grant.rights_route_id,
                "subject_kind": grant.subject_kind.value,
                "subject_ref": grant.subject_ref,
                "version": grant.rights_version,
                "evidence": sorted(grant.evidence_sha256),
            },
            "dimensions": dimensions,
            "seed": seed,
            "lineage_sha256": sorted(lineage_sha256),
        }
    )


__all__ = [
    "AssetDemand",
    "MockAsset",
    "PersistedDemandAsset",
    "PreparedReferenceSet",
    "V2ReferenceRepository",
    "assign_scene_wardrobes",
    "build_prop_prompt_manifest",
    "demand_key",
    "generate_offline_missing",
    "make_offline_style_video",
    "outfit_for_scene_time",
    "plan_reference_demands",
    "validate_pack_scope",
]
