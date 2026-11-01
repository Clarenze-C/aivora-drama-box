"""T043's deterministic layout and preview export bounds."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from editing_support import T0, World
from pydantic import ValidationError
from test_variants_support import variants_service

from microdrama.contracts.enums import (
    AssetKind,
    AssetState,
    DisclosureKind,
    EpisodeState,
    EvidenceSource,
    Platform,
    Provenance,
    RightsStatus,
    RightsSubjectKind,
    SlotKind,
    TrackKind,
)
from microdrama.contracts.errors import Conflict
from microdrama.contracts.examples import (
    release_package,
    release_package_with_derivatives,
    v2_rights,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.media import (
    AssetDescriptor,
    EditDecisionList,
    EdlClip,
    MediaInfo,
    OutputFormat,
)
from microdrama.contracts.primitives import EvidenceRef
from microdrama.contracts.registries import RightsRecord
from microdrama.contracts.release import ReleasePackage, RightsGrant
from microdrama.contracts.routes import EpisodeReviewView, ReviewMediaLink
from microdrama.core.registry.rights import RightsRegistry
from microdrama.editing.creative_derivatives import (
    PREVIEW_MAX_MS,
    CreativeSource,
    PosterPlan,
    PreviewPlan,
    SafeZone,
    platform_poster_frame,
    run_poster_export,
)
from microdrama.editing.ffmpeg import FFmpegRunner
from microdrama.editing.variants_service import VariantsService
from microdrama.persistence.assets import register_asset


def test_platform_frame_and_mobile_crop_are_deterministic() -> None:
    width, height, crop = platform_poster_frame(1080, 1920, "1:1")
    assert (width, height) == (1080, 1080)
    assert crop is not None
    assert crop.model_dump() == {"x": 0, "y": 420, "width": 1080, "height": 1080}


def test_safe_zone_rejects_empty_or_reversed_rectangle() -> None:
    with pytest.raises(ValidationError):
        SafeZone(left=8000, top=2000, right=7000, bottom=9000)


def _poster_fields(*, cta: str = "Watch episode", readability: str = "PASS") -> dict:
    ids = [uuid4(), uuid4(), uuid4()]
    rights = v2_rights()
    created = datetime(2026, 10, 30, tzinfo=UTC)
    sources = [
        CreativeSource(
            asset=AssetDescriptor(
                asset_id=asset_id,
                asset_kind=AssetKind.IMAGE,
                object_key=f"source/{asset_id}",
                sha256=f"{index + 1:064x}",
                size_bytes=1,
                media_type="image/png",
                state=AssetState.ACCEPTED,
                provenance=Provenance.ORIGINAL_FIXTURE,
                version=1,
                created_at=created,
            ),
            rights=rights,
        )
        for index, asset_id in enumerate(ids)
    ]
    fields = {
        "episode_id": uuid4(),
        "platform": Platform.TIKTOK,
        "variant_key": "tiktok-9x16",
        "character": sources[0],
        "title": sources[1],
        "cta": sources[2],
        "title_text": "Mother's Stall",
        "cta_text": cta,
        "approved_cta_texts": ["Watch episode"],
        "width": 360,
        "height": 640,
        "safe_zone": SafeZone(left=500, top=500, right=9500, bottom=9500),
        "title_box": SafeZone(left=1000, top=1000, right=9000, bottom=3000),
        "cta_box": SafeZone(left=1000, top=7000, right=9000, bottom=9000),
        "readability_check": readability,
        "readability_evidence_sha256": sha256(b"readability-evidence").hexdigest(),
        "rights_as_of": created,
        "approved_reveal_episode": 1,
        "source_hashes": {
            "character": sources[0].asset.sha256,
            "title": sources[1].asset.sha256,
            "cta": sources[2].asset.sha256,
        },
        "downstream_lineage": ids,
    }
    constructed = PosterPlan.model_construct(**fields, package_hash="0" * 64)
    fields["package_hash"] = canonical_hash(
        constructed.model_dump(mode="json", exclude={"package_hash"})
    )
    return fields


def test_poster_rejects_unreadable_or_unapproved_cta() -> None:
    with pytest.raises(ValidationError, match="readability_check"):
        PosterPlan(**_poster_fields(readability="FAIL"))
    with pytest.raises(ValidationError, match="not an approved truthful CTA"):
        PosterPlan(**_poster_fields(cta="Get rich now"))


def _preview_fields(
    *,
    duration_ms: int = 1_000,
    reveal_ms: int = 1_000,
    source_in_ms: int = 0,
    timeline_in_ms: int = 0,
) -> dict:
    source_id, episode_id = uuid4(), uuid4()
    source_hash = sha256(b"accepted footage").hexdigest()
    source_out_ms = source_in_ms + duration_ms
    created = datetime(2026, 10, 30, tzinfo=UTC)
    source = CreativeSource(
        asset=AssetDescriptor(
            asset_id=source_id,
            asset_kind=AssetKind.VIDEO,
            object_key=f"source/{source_id}",
            sha256=source_hash,
            size_bytes=1,
            media_type="video/mp4",
            media=MediaInfo(
                duration_ms=source_out_ms,
                has_video=True,
                has_audio=True,
                width=360,
                height=640,
                fps_num=24,
            ),
            state=AssetState.ACCEPTED,
            provenance=Provenance.ORIGINAL_FIXTURE,
            version=1,
            created_at=created,
        ),
        rights=v2_rights(),
    )
    edl = EditDecisionList(
        edl_id=uuid4(),
        episode_id=episode_id,
        version=1,
        purpose=SlotKind.HOOK,
        output=OutputFormat(width=360, height=640, fps_num=24),
        clips=[
            EdlClip(
                clip_id="footage",
                track=TrackKind.VIDEO,
                source_asset_id=source_id,
                source_in_ms=source_in_ms,
                source_out_ms=source_out_ms,
                timeline_in_ms=timeline_in_ms,
            )
        ],
    )
    fields = {
        "platform": Platform.TIKTOK,
        "variant_key": "tiktok-preview",
        "source_edl": edl,
        "sources": [source],
        "source_hashes": {str(source_id): source_hash},
        "rights_as_of": created,
        "reveal_boundary_ms": reveal_ms,
        "source_ranges_ms": [(source_in_ms, source_out_ms)],
        "cta_text": "Watch episode",
        "safe_zone": SafeZone(left=500, top=500, right=9500, bottom=9500),
        "cta_box": SafeZone(left=1000, top=7000, right=9000, bottom=9000),
        "approved_cta_texts": ["Watch episode"],
        "downstream_lineage": [source_id],
        "package_hash": "0" * 64,
    }
    constructed = PreviewPlan.model_construct(**fields)
    fields["package_hash"] = canonical_hash(
        constructed.model_dump(mode="json", exclude={"package_hash"})
    )
    return fields


def test_preview_rejects_spoiler_ranges_and_durations_over_ninety_seconds() -> None:
    with pytest.raises(ValidationError, match="crosses the reveal boundary"):
        PreviewPlan(**_preview_fields(reveal_ms=900))
    with pytest.raises(ValidationError, match="cannot exceed 90 seconds"):
        PreviewPlan(**_preview_fields(duration_ms=90_001, reveal_ms=90_001))


def test_preview_reveal_cutoff_uses_source_time_not_preview_timeline() -> None:
    valid = PreviewPlan(
        **_preview_fields(
            duration_ms=5_000, reveal_ms=40_000, source_in_ms=30_000, timeline_in_ms=2_500
        )
    )
    assert valid.source_edl.duration_ms == 7_500
    assert valid.source_ranges_ms == [(30_000, 35_000)]
    with pytest.raises(ValidationError, match="crosses the reveal boundary"):
        PreviewPlan(
            **_preview_fields(
                duration_ms=5_000, reveal_ms=34_000, source_in_ms=30_000, timeline_in_ms=2_500
            )
        )


def test_preview_limit_is_exactly_ninety_seconds() -> None:
    assert PREVIEW_MAX_MS == 90_000


def test_gate2_projection_contains_derivative_and_only_invalidates_changed_source() -> None:
    package = release_package_with_derivatives()
    preview, poster = package.creative_derivatives[1], package.creative_derivatives[0]
    output = {preview.asset_id: b"preview-bytes", poster.asset_id: b"poster-bytes"}
    descriptors = {
        ref.asset_id: AssetDescriptor(
            asset_id=ref.asset_id,
            asset_kind=(
                AssetKind.VIDEO if ref.derivative_type == "EPISODE_ONE_PREVIEW" else AssetKind.IMAGE
            ),
            object_key=f"test/{ref.asset_id}",
            sha256=sha256(output[ref.asset_id]).hexdigest(),
            size_bytes=len(output[ref.asset_id]),
            media_type="video/mp4"
            if ref.derivative_type == "EPISODE_ONE_PREVIEW"
            else "image/jpeg",
            media=(
                MediaInfo(
                    duration_ms=87_000,
                    has_video=True,
                    has_audio=True,
                    width=360,
                    height=640,
                    fps_num=24,
                )
                if ref.derivative_type == "EPISODE_ONE_PREVIEW"
                else None
            ),
            state=AssetState.ACCEPTED,
            provenance=Provenance.DERIVED_LOCAL,
            episode_id=package.episode_id,
            season_id=package.season_id,
            version=ref.asset_version,
            lineage=sorted({source.asset_id for source in ref.sources}, key=str),
            created_at=datetime.now(UTC),
        )
        for ref in (preview, poster)
    }
    refs = [
        preview.model_copy(
            update={
                "asset_sha256": descriptors[preview.asset_id].sha256,
                "derivation_manifest_sha256": canonical_hash({}),
            }
        ),
        poster.model_copy(
            update={
                "asset_sha256": descriptors[poster.asset_id].sha256,
                "derivation_manifest_sha256": canonical_hash({}),
            }
        ),
    ]
    service = object.__new__(VariantsService)
    service._creative_records = lambda _episode_id: refs
    service._asset = lambda asset_id: descriptors[asset_id]
    service._asset_state = lambda _asset_id: AssetState.ACCEPTED.value
    event_rows = [
        {
            "payload": {
                "creative_derivative": ref.model_dump(mode="json"),
                "derivation_manifest": {},
            }
        }
        for ref in refs
    ]
    service._rows = lambda sql, *_args: event_rows if "domain_events" in sql else []
    service._store = SimpleNamespace(get_bytes=lambda key: output[uuid4_from_key(key)])
    superseded = []
    service._supersede_creative_asset = superseded.append

    def current_rights(sources):
        if any(source.asset_id == preview.sources[0].asset_id for source in sources):
            raise Conflict("source hash no longer current")

    service._creative_sources_current = current_rights
    projected = VariantsService.final_review_creatives(service, package.episode_id)
    assert [item.derivative_type for item in projected] == ["POSTER"]
    assert superseded == [preview.asset_id]

    # The Gate 2 review view exposes both typed lineage and output media references.
    service._row = lambda *_args: None
    service.hook_experiment = lambda _episode_id: None
    service.final_review_creatives = lambda _episode_id: [refs[1]]
    view = VariantsService.final_review_media(service, package.episode_id)
    assert view.creative_derivatives == [refs[1]]
    assert any(ref.asset_id == poster.asset_id and ref.role == "poster" for ref in view.media)


def uuid4_from_key(key: str) -> UUID:
    return UUID(key.removeprefix("test/"))


@pytest.mark.ffmpeg
def test_poster_composes_local_fake_image_assets() -> None:
    ids = [uuid4(), uuid4(), uuid4()]
    plan = SimpleNamespace(
        character=SimpleNamespace(asset=SimpleNamespace(asset_id=ids[0])),
        title=SimpleNamespace(asset=SimpleNamespace(asset_id=ids[1])),
        cta=SimpleNamespace(asset=SimpleNamespace(asset_id=ids[2])),
        width=360,
        height=640,
        title_box=SafeZone(left=1000, top=1000, right=9000, bottom=3000),
        cta_box=SafeZone(left=1000, top=7000, right=9000, bottom=9000),
    )
    with TemporaryDirectory(prefix="md-poster-test-") as tmp:
        runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=60_000)
        runner.export(
            ["-f", "lavfi", "-i", "color=c=navy:s=360x640:d=1", "-c:v", "libx264"],
            output=runner.workdir / "source.mp4",
        )
        for i, _asset_id in enumerate(ids):
            runner.export(
                ["-i", "source.mp4", "-frames:v", "1", "-q:v", "2"],
                output=runner.workdir / f"source-{i}.jpg",
            )
        run_poster_export(
            runner,
            source_names={asset_id: f"source-{i}.jpg" for i, asset_id in enumerate(ids)},
            plan=plan,
            output="poster.jpg",
        )
        assert (runner.workdir / "poster.jpg").stat().st_size > 0


def _accepted_poster_sources(world: World, episode_id: UUID, season_id: UUID, color_base: int):
    from microdrama.contracts.media import AssetDescriptor

    rights_registry = RightsRegistry(world.db, world.clock, world.settings)
    source_refs = []
    with TemporaryDirectory(prefix="md-poster-source-") as tmp:
        runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=60_000)
        colors = [f"0x{color_base + offset * 0x20000:06x}" for offset in range(0, 3)]
        for index, role in enumerate(("character", "title", "cta")):
            path = runner.workdir / f"{role}.jpg"
            runner.export(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={colors[index]}:s=360x640:d=1",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                ],
                output=path,
            )
            data = path.read_bytes()
            stored = world.store.put_bytes(
                f"test/creative/{episode_id}/{role}-{color_base}.jpg",
                data,
                media_type="image/jpeg",
            )
            asset_id = uuid4()
            descriptor = AssetDescriptor(
                asset_id=asset_id,
                asset_kind=AssetKind.IMAGE,
                object_key=stored.key,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type="image/jpeg",
                state=AssetState.ACCEPTED,
                provenance=Provenance.ORIGINAL_FIXTURE,
                episode_id=episode_id,
                season_id=season_id,
                version=1,
                created_at=world.clock.now(),
            )
            with world.db.transaction() as tx:
                register_asset(tx, descriptor)
            evidence = EvidenceRef(
                source=EvidenceSource.FAKE_FIXTURE,
                ref=f"creative:{asset_id}",
                sha256=sha256(f"rights:{asset_id}".encode()).hexdigest(),
            )
            route_id = "creative-rights"
            subject_ref = str(asset_id)
            rights_registry.record(
                RightsRecord(
                    record_id=uuid4(),
                    rights_route_id=route_id,
                    version=1,
                    subject_kind=RightsSubjectKind.MODEL_OUTPUT,
                    subject_ref=subject_ref,
                    territories=["TH"],
                    commercial_use=True,
                    output_release_allowed=True,
                    required_disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
                    expires_at=None,
                    evidence=[evidence],
                    status=RightsStatus.ELIGIBLE,
                    recorded_at=T0,
                ),
                source_provenance=Provenance.ORIGINAL_FIXTURE,
            )
            grant = RightsGrant(
                rights_route_id=route_id,
                subject_kind=RightsSubjectKind.MODEL_OUTPUT,
                subject_ref=subject_ref,
                rights_version=1,
                status=RightsStatus.ELIGIBLE,
                territories=["TH"],
                commercial_use=True,
                output_release_allowed=True,
                evidence_sha256=[evidence.sha256],
            )
            source_refs.append(CreativeSource(asset=descriptor, rights=grant))
    return source_refs


def _poster_plan(episode_id: UUID, sources: list[CreativeSource]) -> PosterPlan:
    fields = {
        "episode_id": episode_id,
        "approved_reveal_episode": 1,
        "platform": Platform.TIKTOK,
        "variant_key": "tiktok-9x16",
        "character": sources[0],
        "title": sources[1],
        "cta": sources[2],
        "title_text": "Mother's Stall",
        "cta_text": "Watch episode",
        "approved_cta_texts": ["Watch episode"],
        "width": 360,
        "height": 640,
        "safe_zone": SafeZone(left=500, top=500, right=9500, bottom=9500),
        "title_box": SafeZone(left=1000, top=1000, right=9000, bottom=3000),
        "cta_box": SafeZone(left=1000, top=7000, right=9000, bottom=9000),
        "readability_check": "PASS",
        "readability_evidence_sha256": sha256(b"human-readability-review").hexdigest(),
        "rights_as_of": T0,
        "source_hashes": {
            "character": sources[0].asset.sha256,
            "title": sources[1].asset.sha256,
            "cta": sources[2].asset.sha256,
        },
        "downstream_lineage": [source.asset.asset_id for source in sources],
    }
    draft = PosterPlan.model_construct(**fields, package_hash="0" * 64)
    fields["package_hash"] = canonical_hash(draft.model_dump(mode="json", exclude={"package_hash"}))
    return PosterPlan(**fields)


def _grant_for_asset(world: World, descriptor: AssetDescriptor) -> RightsGrant:
    evidence = EvidenceRef(
        source=EvidenceSource.FAKE_FIXTURE,
        ref=f"creative:{descriptor.asset_id}",
        sha256=sha256(f"rights:{descriptor.asset_id}".encode()).hexdigest(),
    )
    route_id = "creative-rights"
    subject_ref = str(descriptor.asset_id)
    RightsRegistry(world.db, world.clock, world.settings).record(
        RightsRecord(
            record_id=uuid4(),
            rights_route_id=route_id,
            version=1,
            subject_kind=RightsSubjectKind.MODEL_OUTPUT,
            subject_ref=subject_ref,
            territories=["TH"],
            commercial_use=True,
            output_release_allowed=True,
            required_disclosures=[DisclosureKind.AI_GENERATED_CONTENT],
            expires_at=None,
            evidence=[evidence],
            status=RightsStatus.ELIGIBLE,
            recorded_at=T0,
        ),
        source_provenance=Provenance.ORIGINAL_FIXTURE,
    )
    return RightsGrant(
        rights_route_id=route_id,
        subject_kind=RightsSubjectKind.MODEL_OUTPUT,
        subject_ref=subject_ref,
        rights_version=1,
        status=RightsStatus.ELIGIBLE,
        territories=["TH"],
        commercial_use=True,
        output_release_allowed=True,
        evidence_sha256=[evidence.sha256],
    )


def _preview_plan(world: World, episode_id: UUID, video_id: UUID) -> PreviewPlan:
    video = AssetDescriptor.model_validate(
        world.row("SELECT descriptor FROM assets WHERE id = %s", (video_id,))["descriptor"]
    )
    with TemporaryDirectory(prefix="md-preview-audio-") as tmp:
        runner = FFmpegRunner(workdir=Path(tmp), timeout_ms=60_000)
        audio_path = runner.workdir / "ambience.wav"
        runner.export(
            ["-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "pcm_s16le"],
            output=audio_path,
        )
        audio_data = audio_path.read_bytes()
        audio_media = runner.probe(audio_path)
    audio_stored = world.store.put_bytes(
        f"test/creative/{episode_id}/ambience.wav", audio_data, media_type="audio/wav"
    )
    audio_id = uuid4()
    audio = AssetDescriptor(
        asset_id=audio_id,
        asset_kind=AssetKind.AUDIO,
        object_key=audio_stored.key,
        sha256=audio_stored.sha256,
        size_bytes=audio_stored.size_bytes,
        media_type="audio/wav",
        media=audio_media,
        state=AssetState.ACCEPTED,
        provenance=Provenance.ORIGINAL_FIXTURE,
        episode_id=episode_id,
        season_id=video.season_id,
        version=1,
        created_at=world.clock.now(),
    )
    with world.db.transaction() as tx:
        register_asset(tx, audio)
    video_source = CreativeSource(asset=video, rights=_grant_for_asset(world, video))
    audio_source = CreativeSource(asset=audio, rights=_grant_for_asset(world, audio))
    edl = EditDecisionList(
        edl_id=uuid4(),
        episode_id=episode_id,
        version=1,
        purpose=SlotKind.PROMO_CUT,
        output=OutputFormat(width=360, height=640, fps_num=24),
        clips=[
            EdlClip(
                clip_id="accepted-footage",
                track=TrackKind.VIDEO,
                source_asset_id=video_id,
                source_in_ms=0,
                source_out_ms=3_000,
                timeline_in_ms=0,
            ),
            EdlClip(
                clip_id="accepted-ambience",
                track=TrackKind.AMBIENCE,
                source_asset_id=audio_id,
                source_in_ms=0,
                source_out_ms=3_000,
                timeline_in_ms=0,
            ),
        ],
    )
    fields = {
        "platform": Platform.TIKTOK,
        "variant_key": "tiktok-ep1-preview",
        "source_edl": edl,
        "sources": [video_source, audio_source],
        "source_hashes": {str(video_id): video.sha256, str(audio_id): audio.sha256},
        "rights_as_of": T0,
        "reveal_boundary_ms": 3_000,
        "source_ranges_ms": [(0, 3_000), (0, 3_000)],
        "safe_zone": SafeZone(left=500, top=500, right=9500, bottom=9500),
        "cta_box": SafeZone(left=1000, top=7000, right=9000, bottom=9000),
        "cta_text": "Watch episode",
        "approved_cta_texts": ["Watch episode"],
        "downstream_lineage": [video_id, audio_id],
    }
    draft = PreviewPlan.model_construct(**fields, package_hash="0" * 64)
    fields["package_hash"] = canonical_hash(draft.model_dump(mode="json", exclude={"package_hash"}))
    return PreviewPlan(**fields)


@pytest.mark.ffmpeg
def test_poster_asset_persists_lineage_replays_and_projects_into_gate2(world: World) -> None:
    episode_id, season_id, _assets = world.seed_prepared_episode()
    first_sources = _accepted_poster_sources(world, episode_id, season_id, 0xAA1100)
    other_sources = _accepted_poster_sources(world, episode_id, season_id, 0x11AA00)
    service = variants_service(world)
    first = service.derive_poster(_poster_plan(episode_id, first_sources))
    replay = service.derive_poster(_poster_plan(episode_id, first_sources))
    assert replay == first
    second = service.derive_poster(_poster_plan(episode_id, other_sources))
    assert second.asset_version == first.asset_version + 1
    preview = service.derive_episode_one_preview(
        _preview_plan(world, episode_id, _assets["shots"]["sh1"])
    )
    assert preview.derivative_type == "EPISODE_ONE_PREVIEW"
    assert preview.duration_ms is not None and preview.duration_ms <= 90_000

    with world.db.transaction(readonly=True) as tx:
        stored = tx.fetchone("SELECT descriptor FROM assets WHERE id = %s", (second.asset_id,))
    descriptor = AssetDescriptor.model_validate(stored["descriptor"])
    assert descriptor.state is AssetState.ACCEPTED
    assert descriptor.version == second.asset_version
    assert descriptor.sha256 == second.asset_sha256
    assert descriptor.lineage == sorted(
        [source.asset.asset_id for source in other_sources], key=str
    )
    assert sha256(world.store.get_bytes(descriptor.object_key)).hexdigest() == second.asset_sha256

    review_media = service.final_review_media(episode_id)
    assert {item.derivative_type for item in review_media.creative_derivatives or []} == {
        "POSTER",
        "EPISODE_ONE_PREVIEW",
    }
    projected_by_type = {
        item.derivative_type: item for item in review_media.creative_derivatives or []
    }
    assert projected_by_type["POSTER"] == second
    assert projected_by_type["EPISODE_ONE_PREVIEW"] == preview
    assert any(
        media.asset_id == second.asset_id and media.role == "poster" for media in review_media.media
    )

    base = release_package()
    package_fields = base.model_dump(mode="python")
    package_fields["media"] = [*base.media, *review_media.media]
    package_fields["creative_derivatives"] = review_media.creative_derivatives
    package_fields["cast_package_asset_ids"] = [
        *base.cast_package_asset_ids,
        first_sources[0].asset.asset_id,
        other_sources[0].asset.asset_id,
    ]
    package = ReleasePackage.seal(**package_fields)
    assert package.package_hash != base.package_hash
    episode_view = EpisodeReviewView(
        episode_id=package.episode_id,
        episode_number=1,
        state=EpisodeState.AWAITING_FINAL_REVIEW,
        revision=0,
        package=package,
        gate_enabled=False,
        media=[
            ReviewMediaLink(
                asset_id=media.asset_id,
                role=media.role,
                sha256=media.sha256,
                review_path=f"private/{media.asset_id}",
            )
            for media in review_media.media
        ],
    )
    assert episode_view.package.creative_derivatives == review_media.creative_derivatives
    assert any(media.asset_id == second.asset_id for media in episode_view.media)

    service._supersede_creative_asset(first_sources[0].asset.asset_id)
    projected = service.final_review_creatives(episode_id)
    assert {item.asset_id for item in projected} == {second.asset_id, preview.asset_id}
    assert service._asset_state(first.asset_id) == AssetState.SUPERSEDED.value
    assert service._asset_state(second.asset_id) == AssetState.ACCEPTED.value
