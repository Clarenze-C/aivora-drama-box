"""Production suppliers for the V2 dispatch boundary (T047).

``rendering.routing.ReferenceContext`` declares the two seams T041b deferred to
this task: an authoritative current-rights resolver and a
``verify_current_asset`` that must prove the live descriptor is ACCEPTED at the
exact version/hash **and** that the stored bytes still hash to it, before any
render reservation. This module supplies both, plus the loader that assembles a
context from an episode's current hash-verified V2 records.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from pydantic import ValidationError

from microdrama.contracts.errors import Conflict, SchemaInvalid
from microdrama.contracts.hashing import sha256_hex
from microdrama.contracts.infra import ObjectStore
from microdrama.contracts.registries import EvidenceRef, RightsRecord
from microdrama.contracts.v2 import (
    AssetSheet,
    DirectingManifest,
    EpisodePack,
    LocationLayout,
    PropSheet,
    SceneWardrobeAssignment,
    SecretLedger,
    StyleBible,
    WardrobeBible,
)
from microdrama.persistence.db import Database
from microdrama.references.v2_binding import RightsResolver
from microdrama.rendering.routing import V2ReferencePreflightContext as ReferenceContext


def make_verify_current_asset(db: Database, store: ObjectStore) -> Callable[[UUID, int, str], None]:
    """The T047 asset gate: ACCEPTED row at the exact version/hash + live bytes.

    A binding that names a superseded version, a stale hash, a non-ACCEPTED
    row, or bytes that no longer hash to the registered sha256 fails typed
    before render reservation. Asset immutability triggers keep the row
    honest; this check keeps the *bytes* honest too.
    """

    def verify_current_asset(asset_id: UUID, asset_version: int, asset_sha256: str) -> None:
        with db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT version, state, sha256, object_key FROM assets WHERE id = %s",
                (asset_id,),
            )
        if row is None:
            raise SchemaInvalid("referenced asset does not exist", asset_id=str(asset_id))
        if row["state"] != "ACCEPTED":
            raise SchemaInvalid(
                "referenced asset is not ACCEPTED",
                asset_id=str(asset_id),
                state=str(row["state"]),
            )
        if int(row["version"]) != int(asset_version):
            raise SchemaInvalid(
                "referenced asset version is not the live version",
                asset_id=str(asset_id),
                expected_version=int(asset_version),
                live_version=int(row["version"]),
            )
        if str(row["sha256"]) != asset_sha256:
            raise SchemaInvalid(
                "referenced asset hash differs from the registered row",
                asset_id=str(asset_id),
            )
        actual = sha256_hex(store.get_bytes(str(row["object_key"])))
        if actual != asset_sha256:
            raise Conflict(
                "stored asset bytes do not hash to the registered sha256",
                asset_id=str(asset_id),
                expected=asset_sha256[:16],
                actual=actual[:16],
            )

    return verify_current_asset


def make_registry_rights_resolver(db: Database) -> RightsResolver:
    """The authoritative current-rights resolver over ``rights_registry``.

    Resolves (route, subject kind, subject ref) to its CURRENT registry record;
    absent subjects return None so ``validate_current_rights_grant`` fails
    closed. Superseded rows are never returned.
    """

    def resolve(route_id: str, subject_kind: object, subject_ref: str) -> RightsRecord | None:
        with db.transaction(readonly=True) as tx:
            row = tx.fetchone(
                "SELECT * FROM rights_registry WHERE rights_route_id = %s"
                " AND subject_kind = %s AND subject_ref = %s AND current",
                (route_id, str(subject_kind), subject_ref),
            )
        if row is None:
            return None
        try:
            return RightsRecord(
                record_id=row["id"],
                rights_route_id=row["rights_route_id"],
                version=int(row["version"]),
                subject_kind=row["subject_kind"],
                subject_ref=row["subject_ref"],
                territories=[str(t) for t in (row["territories"] or [])],
                commercial_use=row["commercial_use"],
                output_release_allowed=row["output_release_allowed"],
                required_disclosures=list(row["required_disclosures"] or []),
                expires_at=row["expires_at"],
                evidence=[EvidenceRef.model_validate(item) for item in (row["evidence"] or [])],
                status=row["status"],
                recorded_at=row["created_at"],
            )
        except ValidationError as exc:
            # An unreadable registry row can never authorize a dispatch.
            raise SchemaInvalid(
                "current rights registry row failed validation",
                rights_route_id=str(row["rights_route_id"]),
            ) from exc

    return resolve


# --- the current-record loader ---------------------------------------------------


def _current_doc(tx, model: type, *, key: str, value: str, label: str):
    """The one current row for a payload key, model-validated and hash-verified.

    DB-5: exactly one current row must match — the store permits several
    current records to name the same payload key (uniqueness is per
    record_id), and guessing between them with an unordered fetchone would
    dispatch against arbitrary content. Ambiguity is a typed error.
    """
    rows = tx.fetchall(
        "SELECT record_id, version, payload, payload_sha256 FROM v2_contract_documents "
        "WHERE contract_type = %s AND current AND payload->>%s = %s ORDER BY record_id",
        (model.__name__, key, value),
    )
    if rows is None or len(rows) == 0:
        raise SchemaInvalid(f"no current {model.__name__} record for this {label}")
    if len(rows) > 1:
        raise SchemaInvalid(
            f"ambiguous current {model.__name__} records for this {label}", **{label: value}
        )
    row = rows[0]
    try:
        record = model.model_validate(row["payload"])
    except ValidationError as exc:
        raise SchemaInvalid(
            f"current {model.__name__} record failed validation", **{label: value}
        ) from exc
    from microdrama.contracts.hashing import canonical_hash

    if canonical_hash(record) != row["payload_sha256"]:
        raise SchemaInvalid(
            f"current {model.__name__} record failed hash verification",
            **{label: value},
        )
    return record


def _current_docs(tx, model: type, *, key: str, value: str) -> list:
    rows = tx.fetchall(
        "SELECT record_id, version, payload, payload_sha256 FROM v2_contract_documents "
        "WHERE contract_type = %s AND current AND payload->>%s = %s ORDER BY record_id",
        (model.__name__, key, value),
    )
    from microdrama.contracts.hashing import canonical_hash

    records = []
    for row in rows:
        try:
            record = model.model_validate(row["payload"])
        except ValidationError as exc:
            raise SchemaInvalid(f"a current {model.__name__} record failed validation") from exc
        if canonical_hash(record) != row["payload_sha256"]:
            raise SchemaInvalid(f"a current {model.__name__} record failed hash verification")
        records.append(record)
    return records


def load_reference_context(
    db: Database,
    store: ObjectStore,
    episode_id: UUID,
    *,
    resolve_current_rights: RightsResolver,
    territories: list[str],
    style_subject_id: str = "style",
    explicit_frames: tuple = (),
) -> ReferenceContext:
    """Assemble the dispatch context from the episode's current typed records.

    Every record is loaded from its current row and hash-verified; ambiguity is
    impossible for episode-keyed singles (one current row is expected, none is
    a typed error), and list-valued records are returned whole for the resolver
    to check. Fail-closed: any unreadable record blocks the load.
    """
    with db.transaction(readonly=True) as tx:
        episode = tx.fetchone("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if episode is None:
            raise SchemaInvalid("episode does not exist", episode_id=str(episode_id))
        season_id = str(episode["season_id"])
        episode_key = str(episode_id)
        pack = _current_doc(tx, EpisodePack, key="episode_id", value=episode_key, label="episode")
        manifest = _current_doc(
            tx, DirectingManifest, key="episode_id", value=episode_key, label="episode"
        )
        secret_ledger = _current_doc(
            tx, SecretLedger, key="season_id", value=season_id, label="season"
        )
        style_bible = _current_doc(tx, StyleBible, key="season_id", value=season_id, label="season")
        assignments = _current_docs(
            tx, SceneWardrobeAssignment, key="episode_id", value=episode_key
        )
        wardrobe_bibles = _current_docs(tx, WardrobeBible, key="season_id", value=season_id)
        subjects = (
            {style_subject_id}
            | {scene.location_id for scene in pack.scenes}
            | {o.outfit_id for bible in wardrobe_bibles for o in bible.outfits}
            | {c.character_id for c in pack.character_logic}
        )
        # DB-2: season provenance, the same approach as the T044b2 F2 workbench
        # fix. Sheet ids are shared identifiers (any season may have a 'style'
        # subject or a 'fon' character), so a sheet is visible to this episode's
        # dispatch only when ITS asset row belongs to the episode's season.
        season_asset_ids = {
            str(row["id"])
            for row in tx.fetchall("SELECT id FROM assets WHERE season_id = %s", (season_id,))
        }
        asset_sheets = [
            sheet
            for subject in sorted(subjects)
            for sheet in _current_docs(tx, AssetSheet, key="subject_id", value=subject)
            if str(sheet.asset_id) in season_asset_ids
        ]
        scene_props = {prop for scene in pack.scenes for prop in scene.prop_ids}
        prop_sheets = [
            sheet
            for prop in sorted(scene_props)
            for sheet in _current_docs(tx, PropSheet, key="prop_id", value=prop)
            if str(sheet.asset_id) in season_asset_ids
        ]
        # A LocationLayout carries no asset reference; it is minted from the
        # same empty plate as the season's location AssetSheet, so geometry
        # equality against a proven plate IS the provenance chain (shared plate
        # bytes across seasons degrade to ambiguity, which one-layout binding
        # refuses — an honest unknown, never a guess).
        plate_shas = {
            sheet.asset_sha256
            for sheet in _current_docs(tx, AssetSheet, key="asset_role", value="location")
            if str(sheet.asset_id) in season_asset_ids
        }
        location_layouts = [
            layout
            for location_id in sorted({scene.location_id for scene in pack.scenes})
            for layout in _current_docs(tx, LocationLayout, key="location_id", value=location_id)
            if layout.geometry_sha256 in plate_shas
        ]
    verify_current_asset = make_verify_current_asset(db, store)
    return ReferenceContext(
        episode_pack=pack,
        directing_manifest=manifest,
        secret_ledger=secret_ledger,
        wardrobe_assignments=assignments,
        wardrobe_bibles=wardrobe_bibles,
        style_bible=style_bible,
        asset_sheets=asset_sheets,
        prop_sheets=prop_sheets,
        location_layouts=location_layouts,
        resolve_current_rights=resolve_current_rights,
        verify_current_asset=verify_current_asset,
        territories=territories,
        style_subject_id=style_subject_id,
        explicit_frames=explicit_frames,
    )


def _current_docs_all(tx, model: type) -> list:
    """Every current record of one type, validated and hash-verified."""
    from microdrama.contracts.hashing import canonical_hash

    rows = tx.fetchall(
        "SELECT record_id, version, payload, payload_sha256 FROM v2_contract_documents "
        "WHERE contract_type = %s AND current ORDER BY record_id",
        (model.__name__,),
    )
    records = []
    for row in rows:
        try:
            record = model.model_validate(row["payload"])
        except ValidationError as exc:
            raise SchemaInvalid(f"a current {model.__name__} record failed validation") from exc
        if canonical_hash(record) != row["payload_sha256"]:
            raise SchemaInvalid(f"a current {model.__name__} record failed hash verification")
        records.append(record)
    return records


__all__ = [
    "load_reference_context",
    "make_registry_rights_resolver",
    "make_verify_current_asset",
]
