"""Anchor planning, full-key caching and reference-version persistence (T011).

An anchor is one reusable identity asset version (face, wardrobe, location, style or
voice). The cache key is the hash of the FULL generation inputs — model profile,
rights route, prompt, dimensions, seed and lineage references — so identical content
is generated (and paid) once per season and everything else is a reuse. SPEC §7 also
forbids deduping "purely by script text": the key carries every input that changes
the bytes, not the text alone.
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from microdrama.contracts.hashing import canonical_hash
from microdrama.contracts.season import Script, SeasonScope, ShotManifest
from microdrama.persistence.db import Tx, insert_row
from microdrama.references.config import ReferencesConfig
from microdrama.references.models import AnchorSpec, RefKind

REFERENCES_NAMESPACE = uuid5(NAMESPACE_URL, "https://microdrama.invalid/references/v1")

#: Reference-version states that may be resolved and reused (SUPERSEDED/FAILED never are).
LIVE_STATES = ("PROVISIONAL", "ACCEPTED", "LOCKED")


def ref_id_for(kind: str, key: str) -> UUID:
    return uuid5(REFERENCES_NAMESPACE, f"{kind}:{key}")


def deterministic_seed(ref_key: str) -> int:
    """A stable non-negative seed derived from the reference key (no RNG)."""
    return int(canonical_hash(ref_key)[:8], 16)


def face_key(character_key: str) -> str:
    return f"face.{character_key}"


def wardrobe_key(character_key: str, outfit: int) -> str:
    return f"wardrobe.{character_key}.{outfit}"


def location_key(location_id: str) -> str:
    return f"location.{location_id}"


def style_key() -> str:
    return "style.season"


def voice_key(character_key: str) -> str:
    return f"voice.{character_key}"


def voice_id_for(character_key: str, version: int) -> str:
    """The contract ``Identifier`` a dialogue line/shot carries for one voice version."""
    return f"voice-{character_key}-v{version}"


def _character_prompt(scope: SeasonScope, character_key: str) -> str | None:
    return next((c for c in scope.characters if c.character_id == character_key), None)


def plan_anchors(
    script: Script, manifest: ShotManifest, scope: SeasonScope, config: ReferencesConfig
) -> list[AnchorSpec]:
    """Every anchor the episode's current script/manifest needs, deterministically ordered.

    Style once per season, one face per speaking character, one wardrobe per
    (character, outfit) — outfits default to one until the story lane emits ids — one
    set per location, one voice anchor per speaking character (its sample text is the
    speaker's first Thai line in this script).
    """
    width, height = config.anchor_dimensions
    speakers: list[str] = sorted(
        {ln.speaker_character_id for sc in script.scenes for ln in sc.lines}
    )
    locations = sorted(
        {sc.location_id for sc in script.scenes} | {shot.location_id for shot in manifest.shots}
    )
    anchors: list[AnchorSpec] = [
        AnchorSpec(
            ref_kind=RefKind.STYLE,
            ref_key=style_key(),
            prompt=(
                f"style anchor: {scope.title_en} — {scope.logline}"
                + ("".join(f"; rule: {r}" for r in scope.creative_constraints.style_rules[:4]))
            )[:4000],
            width=width,
            height=height,
            seed=deterministic_seed(style_key()),
        )
    ]
    for character_key in speakers:
        brief = _character_prompt(scope, character_key)
        if brief is None:
            # The story critics already refuse unknown speakers; this is the typed backstop.
            from microdrama.contracts.errors import NotFound

            raise NotFound(
                "script speaker has no approved character brief", character_key=character_key
            )
        anchors.append(
            AnchorSpec(
                ref_kind=RefKind.FACE,
                ref_key=face_key(character_key),
                character_key=character_key,
                prompt=f"face anchor: {brief.name_en} ({brief.name_th}), {brief.role}. {brief.description}"[
                    :4000
                ],
                width=width,
                height=height,
                seed=deterministic_seed(face_key(character_key)),
            )
        )
        for outfit in range(1, config.outfits_per_character + 1):
            anchors.append(
                AnchorSpec(
                    ref_kind=RefKind.WARDROBE,
                    ref_key=wardrobe_key(character_key, outfit),
                    character_key=character_key,
                    prompt=f"wardrobe {outfit} for {brief.name_en} ({brief.name_th})"[:4000],
                    width=width,
                    height=height,
                    seed=deterministic_seed(wardrobe_key(character_key, outfit)),
                )
            )
        first_line = next(
            (
                ln.text_th
                for sc in script.scenes
                for ln in sc.lines
                if ln.speaker_character_id == character_key
            ),
            brief.name_th,
        )
        anchors.append(
            AnchorSpec(
                ref_kind=RefKind.VOICE,
                ref_key=voice_key(character_key),
                character_key=character_key,
                prompt=first_line[:1000],
                width=width,
                height=height,
                seed=deterministic_seed(voice_key(character_key)),
            )
        )
    for location_id in locations:
        anchors.append(
            AnchorSpec(
                ref_kind=RefKind.LOCATION,
                ref_key=location_key(location_id),
                location_id=location_id,
                prompt=f"set anchor for location {location_id}: {scope.title_en}"[:4000],
                width=width,
                height=height,
                seed=deterministic_seed(location_key(location_id)),
            )
        )
    return anchors


def anchor_cache_key(spec: AnchorSpec, *, model_config_ref: str, rights_route_id: str) -> str:
    """Full input/model/license hash. Everything that changes the bytes is in the key."""
    return canonical_hash(
        {
            "kind": spec.ref_kind.value,
            "model": model_config_ref,
            "rights_route": rights_route_id,
            "prompt": spec.prompt,
            "width": spec.width,
            "height": spec.height,
            "seed": spec.seed,
            "lineage": sorted(str(a) for a in spec.lineage_asset_ids),
        }
    )


def cache_inputs_hash(spec: AnchorSpec, *, model_config_ref: str, rights_route_id: str) -> str:
    """The recorded ``source_hash``: the same inputs the cache key covers."""
    return canonical_hash(
        {
            "model": model_config_ref,
            "rights_route": rights_route_id,
            "prompt": spec.prompt,
            "width": spec.width,
            "height": spec.height,
            "seed": spec.seed,
            "lineage": sorted(str(a) for a in spec.lineage_asset_ids),
        }
    )


# --- reference-version reads/writes -------------------------------------------------------


def next_version(tx: Tx, season_id: UUID, ref_kind: RefKind, ref_key: str) -> int:
    value = tx.fetchval(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM reference_versions "
        "WHERE season_id = %s AND ref_kind = %s AND ref_key = %s",
        (season_id, ref_kind.value, ref_key),
    )
    return int(value or 1)


def by_cache_key(tx: Tx, season_id: UUID, cache_key: str) -> dict[str, Any] | None:
    return tx.fetchone(
        "SELECT * FROM reference_versions WHERE season_id = %s AND cache_key = %s "
        "AND state = ANY(%s) ORDER BY version DESC LIMIT 1",
        (season_id, cache_key, list(LIVE_STATES)),
    )


def live_version(tx: Tx, season_id: UUID, ref_kind: RefKind, ref_key: str) -> dict[str, Any] | None:
    return tx.fetchone(
        "SELECT * FROM reference_versions WHERE season_id = %s AND ref_kind = %s AND ref_key = %s "
        "AND state = ANY(%s) ORDER BY version DESC LIMIT 1",
        (season_id, ref_kind.value, ref_key, list(LIVE_STATES)),
    )


def locked_member(tx: Tx, lock_id: UUID, ref_kind: RefKind, ref_key: str) -> dict[str, Any] | None:
    return tx.fetchone(
        "SELECT rv.* FROM identity_lock_assets la JOIN reference_versions rv ON rv.id = "
        "la.reference_version_id WHERE la.lock_id = %s AND rv.ref_kind = %s AND rv.ref_key = %s",
        (lock_id, ref_kind.value, ref_key),
    )


def insert_reference_version(
    tx: Tx,
    *,
    season_id: UUID,
    spec: AnchorSpec,
    version: int,
    asset_id: UUID,
    content_sha256: str,
    cache_key: str,
    source_hash: str,
    license_hash: str | None,
    now,
) -> dict[str, Any]:
    row = insert_row(
        tx,
        "reference_versions",
        {
            "id": ref_id_for(
                "refver", f"{season_id}:{spec.ref_kind.value}:{spec.ref_key}:v{version}"
            ),
            "season_id": season_id,
            "ref_kind": spec.ref_kind.value,
            "ref_key": spec.ref_key,
            "version": version,
            "asset_id": asset_id,
            "content_sha256": content_sha256,
            "source_hash": source_hash,
            "license_hash": license_hash,
            "cache_key": cache_key,
            "character_key": spec.character_key,
            "state": "PROVISIONAL",
            "reviewed_in_package_id": None,
            "created_at": now,
            "updated_at": now,
        },
        returning="*",
    )
    return dict(row)


def insert_voice_row(
    tx: Tx,
    *,
    season_id: UUID,
    character_id: UUID,
    character_key: str,
    version: int,
    provider: str,
    provider_voice_ref: str,
    rights_route_id: str,
    license_hash: str | None,
    anchor_asset_id: UUID,
    now,
) -> None:
    insert_row(
        tx,
        "voices",
        {
            "id": ref_id_for("voice", f"{season_id}:{character_key}:v{version}"),
            "season_id": season_id,
            "character_id": character_id,
            "voice_key": voice_key(character_key),
            "version": version,
            "provider": provider,
            "provider_voice_ref": provider_voice_ref,
            "rights_route_id": rights_route_id,
            "license_hash": license_hash,
            "anchor_asset_id": anchor_asset_id,
            "state": "PROVISIONAL",
            "created_at": now,
            "updated_at": now,
        },
        returning="id",
    )


def dependents_of(tx: Tx, season_id: UUID, asset_id: UUID) -> list[dict[str, Any]]:
    """Live reference versions whose asset was derived from ``asset_id`` (asset_lineage)."""
    return tx.fetchall(
        "SELECT rv.* FROM reference_versions rv JOIN asset_lineage al ON al.asset_id = rv.asset_id "
        "WHERE rv.season_id = %s AND al.source_asset_id = %s AND rv.state = ANY(%s) "
        "ORDER BY rv.ref_kind, rv.ref_key, rv.version",
        (season_id, asset_id, list(LIVE_STATES)),
    )


__all__ = [
    "LIVE_STATES",
    "REFERENCES_NAMESPACE",
    "anchor_cache_key",
    "by_cache_key",
    "cache_inputs_hash",
    "dependents_of",
    "deterministic_seed",
    "face_key",
    "insert_reference_version",
    "insert_voice_row",
    "live_version",
    "location_key",
    "locked_member",
    "next_version",
    "plan_anchors",
    "ref_id_for",
    "style_key",
    "voice_id_for",
    "voice_key",
    "wardrobe_key",
]
