"""Pre-motion still-frame keyframe preflight (T042a).

A *keyframe* is a typed frame-role reference binding (``FIRST_FRAME`` /
``LAST_FRAME`` / ``HANDOFF_FRAME``) whose current bytes carry a verified
checksum. Before a routed V2 attempt puts any budget hold on the episode, each
bound keyframe is observed by an injected read-only still-media inspector and
the frozen observation is compared against the current typed assignments
(visible identity, assigned outfit, prop/holder, location geometry, light,
eyeline, proof text, handoff).

Honesty rules (mirroring the QA contract):

- the observer call is media-only: no intended script/canon fact, assignment
  or prompt text ever enters it; comparison happens against a frozen
  observation afterwards;
- a missing inspector or an uncalibrated dimension is ``UNAVAILABLE``, an
  absent or below-threshold observation is ``UNKNOWN`` — neither is ever a
  ``PASS``;
- a ``PASS`` certifies the STILL frames only; it is never a motion
  certification (actual-media QA owns motion, T042b);
- a route with no bound keyframes records ``NOT_APPLICABLE`` instead of
  pretending the check passed.

Evidence is durable: every outcome is appended to ``domain_events`` keyed by a
deterministic aggregate id derived from the hashed result inputs — including the
selected route's semantic template hash — so a replay with identical inputs
returns the identical recorded evidence without re-observing, while a changed
asset, manifest, route template, typed expectation or evaluator configuration
changes the input hash and invalidates the cached result. Route capability is
checked before any replay: a stillless route is refused even when a PASS for the
same frames sits on disk, because that PASS was recorded for a different route.
Concurrent callers with identical inputs append exactly one event (a
transaction-scoped advisory lock plus an in-transaction recheck; the inspector
never runs under a DB lock). A mutable in-memory flag is never the authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID, uuid5

from microdrama.contracts.enums import ControlKind
from microdrama.contracts.errors import PolicyDenied, SchemaInvalid, UnsupportedControl
from microdrama.contracts.hashing import canonical_hash, sha256_hex
from microdrama.contracts.v2 import (
    DirectingShot,
    EpisodeScene,
    LocationLayout,
    PromptManifest,
    PropSheet,
    ReferenceRole,
    SceneWardrobeAssignment,
    StateValue,
)
from microdrama.core.events import append_event, list_events
from microdrama.persistence.db import Database
from microdrama.references.v2_binding import ExpectedReference
from microdrama.rendering.leases import RENDERING_NAMESPACE
from microdrama.rendering.workflows.templates import (
    WorkflowTemplate,
    semantic_template_sha256,
)

#: Aggregate/event names for durable keyframe preflight evidence.
KEYFRAME_AGGREGATE_TYPE = "render_keyframe_preflight"
KEYFRAME_PREFLIGHT_EVENT = "render.keyframe_preflight"

#: Transaction-scoped advisory-lock seed serialising concurrent evidence appends
#: for one deterministic preflight aggregate (see ``run_keyframe_preflight``).
_PREFLIGHT_LOCK_SEED = 451050

#: A PASS covers still frames only; motion findings need actual-media QA (T042b).
KEYFRAME_SCOPE = "STILL_FRAME_ONLY"

#: Frame roles this preflight can verify. Role comes from the typed binding key,
#: never from list order.
FRAME_ROLES = frozenset(
    {ReferenceRole.FIRST_FRAME, ReferenceRole.LAST_FRAME, ReferenceRole.HANDOFF_FRAME}
)


class KeyframeDimension(StrEnum):
    """Comparison dimensions of the pre-motion still check."""

    VISIBLE_IDENTITY = "visible_identity"
    OUTFIT = "outfit"
    PROP_HOLDER = "prop_holder"
    LOCATION_GEOMETRY = "location_geometry"
    LIGHT = "light"
    EYELINE = "eyeline"
    PROOF_TEXT = "proof_text"
    HANDOFF = "handoff"


class DimensionOutcome(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class FrameOutcome(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class KeyframePreflightStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class KeyframePreflightFailed(PolicyDenied):
    """The pre-motion still-frame check blocked dispatch before any budget hold."""

    code = "KEYFRAME_PREFLIGHT_FAILED"


def route_supports_still_frames(template: WorkflowTemplate) -> bool:
    """Whether the pinned route can carry a still-frame semantic input at all."""
    if template.supports(ControlKind.FIRST_FRAME) or template.supports(ControlKind.LAST_FRAME):
        return True
    return any(
        port in template.semantic_role_ports
        for port in ("first_frame", "last_frame", "handoff_frame")
    )


# --- observation side (media-only; no intended facts may reach it) -------------------


@dataclass(frozen=True)
class FrameAsset:
    """Exactly what the observer receives: verified frame identity and bytes.

    Deliberately carries no frame role, no subject semantics, no expected fact
    and no prompt text — the observation must stand on the media alone.
    """

    asset_id: UUID
    asset_version: int
    asset_sha256: str
    payload: bytes


@dataclass(frozen=True)
class StillFrameObservation:
    """Frozen neutral observation of one still frame.

    ``None`` means the dimension was not observed. Free-text fields are
    compared after normalization; identifiers are compared exactly.
    """

    visible_subject_ids: frozenset[str] | None = None
    outfit_by_character: Mapping[str, str] | None = None
    holder_by_prop: Mapping[str, str] | None = None
    location_id: str | None = None
    geometry_token: str | None = None
    light_state: str | None = None
    eyeline: str | None = None
    proof_text: str | None = None
    handoff: str | None = None
    confidence_bp: Mapping[KeyframeDimension, int | None] = field(default_factory=dict)

    def observation_sha256(self) -> str:
        return canonical_hash(
            {
                "visible_subject_ids": sorted(self.visible_subject_ids or ()),
                "outfit_by_character": dict(sorted((self.outfit_by_character or {}).items())),
                "holder_by_prop": dict(sorted((self.holder_by_prop or {}).items())),
                "location_id": self.location_id,
                "geometry_token": self.geometry_token,
                "light_state": self.light_state,
                "eyeline": self.eyeline,
                "proof_text": self.proof_text,
                "handoff": self.handoff,
                "confidence_bp": {
                    dimension.value: value
                    for dimension, value in sorted(
                        self.confidence_bp.items(), key=lambda item: item[0].value
                    )
                },
            }
        )


@dataclass(frozen=True)
class StillMediaInspector:
    """Injected read-only still-media inspector with declared calibration.

    ``calibrated_threshold_bp`` maps each dimension this evaluator is calibrated
    for to the minimum confidence (basis points) its observations must carry to
    clear a check. A dimension absent from the map is ``UNAVAILABLE``; an
    observation below the threshold is ``UNKNOWN`` — neither can ever pass.
    """

    evaluator_id: str
    evaluator_version: str
    source_label: str
    calibrated_threshold_bp: Mapping[KeyframeDimension, int]
    observe: Callable[[FrameAsset], StillFrameObservation]

    def __post_init__(self) -> None:
        if not self.evaluator_id or not self.evaluator_version or not self.source_label:
            raise SchemaInvalid(
                "still-frame inspector must declare an explicit evaluator identity and source label"
            )
        thresholds = dict(self.calibrated_threshold_bp)
        for dimension, threshold in thresholds.items():
            if not 0 <= threshold <= 10_000:
                raise SchemaInvalid(
                    "inspector calibration threshold must be 0..10000 basis points",
                    dimension=dimension.value,
                )
        object.__setattr__(self, "calibrated_threshold_bp", MappingProxyType(thresholds))

    def capability_sha256(self) -> str:
        """Hash of the evaluator identity plus its full calibration table."""
        return canonical_hash(
            {
                "evaluator_id": self.evaluator_id,
                "evaluator_version": self.evaluator_version,
                "source_label": self.source_label,
                "calibrated_threshold_bp": {
                    dimension.value: threshold
                    for dimension, threshold in sorted(
                        self.calibrated_threshold_bp.items(), key=lambda item: item[0].value
                    )
                },
            }
        )

    def is_calibrated(self, dimension: KeyframeDimension) -> bool:
        return dimension in self.calibrated_threshold_bp

    def clears(self, dimension: KeyframeDimension, confidence_bp: int | None) -> bool:
        """A dimension clears only at or above its calibrated threshold."""
        threshold = self.calibrated_threshold_bp.get(dimension)
        return threshold is not None and confidence_bp is not None and confidence_bp >= threshold


# --- expected side (typed records; never enters the observer call) -------------------


@dataclass(frozen=True)
class ExpectedKeyframeFacts:
    """What the current typed records say the frame must show."""

    visible_character_ids: frozenset[str]
    outfit_by_character: Mapping[str, str]
    holder_by_prop: Mapping[str, str]
    location_id: str
    geometry_sha256: str
    light_state: str | None
    eyeline: str
    action_handoff: str
    proof_text_sha256_by_prop: Mapping[str, str]

    def facts_digest(self) -> str:
        return canonical_hash(
            {
                "visible_character_ids": sorted(self.visible_character_ids),
                "outfit_by_character": dict(sorted(self.outfit_by_character.items())),
                "holder_by_prop": dict(sorted(self.holder_by_prop.items())),
                "location_id": self.location_id,
                "geometry_sha256": self.geometry_sha256,
                "light_state": self.light_state,
                "eyeline": self.eyeline,
                "action_handoff": self.action_handoff,
                "proof_text_sha256_by_prop": dict(sorted(self.proof_text_sha256_by_prop.items())),
            }
        )

    def compared_dimensions(self) -> tuple[KeyframeDimension, ...]:
        """Dimensions this shot's typed state can actually compare."""
        dimensions = {
            KeyframeDimension.LOCATION_GEOMETRY,
            KeyframeDimension.EYELINE,
            KeyframeDimension.HANDOFF,
        }
        if self.visible_character_ids:
            dimensions.add(KeyframeDimension.VISIBLE_IDENTITY)
        if self.outfit_by_character:
            dimensions.add(KeyframeDimension.OUTFIT)
        if self.holder_by_prop:
            dimensions.add(KeyframeDimension.PROP_HOLDER)
        if self.light_state is not None:
            dimensions.add(KeyframeDimension.LIGHT)
        if self.proof_text_sha256_by_prop:
            dimensions.add(KeyframeDimension.PROOF_TEXT)
        return tuple(sorted(dimensions, key=lambda dimension: dimension.value))


def _state_value(
    state_sources: Sequence[Sequence[StateValue]], entity_id: str, field_name: str
) -> str | None:
    for values in state_sources:
        for item in values:
            if item.entity_id == entity_id and item.field == field_name:
                return str(item.value) if item.value is not None else None
    return None


def build_expected_keyframe_facts(
    *,
    scene: EpisodeScene,
    directing_shot: DirectingShot,
    shot_prop_ids: Sequence[str],
    wardrobe_assignments: Sequence[SceneWardrobeAssignment],
    location_layouts: Sequence[LocationLayout],
    prop_sheets: Sequence[PropSheet],
    frame_role: ReferenceRole,
) -> ExpectedKeyframeFacts:
    """Derive the comparison facts for one frame role from the typed records only.

    Frame roles carry state meaning, not just identity: the first frame shows the
    shot/scene *entry* state, while the last and outgoing handoff frames show the
    *exit* state. Exit lookups fall back to the entry state for values the shot
    does not restate, so a legitimate mid-shot transition (a prop changing
    holder, the light changing) is compared against two deliberately different
    expectations — never by demanding identical stills.
    """
    if frame_role not in FRAME_ROLES:
        raise SchemaInvalid(
            "keyframe facts require a frame role this preflight can verify",
            frame_role=frame_role.value,
        )
    visible = frozenset(scene.visible_character_ids)
    outfits = {
        item.character_id: item.outfit_id
        for item in wardrobe_assignments
        if item.scene_id == scene.scene_id and item.character_id in visible
    }
    if visible and set(outfits) != visible:
        raise SchemaInvalid(
            "keyframe facts require exactly one current outfit assignment per visible character",
            scene_id=scene.scene_id,
        )
    layouts = [item for item in location_layouts if item.location_id == scene.location_id]
    if len(layouts) != 1:
        raise SchemaInvalid(
            "keyframe facts require exactly one current LocationLayout for the scene",
            location_id=scene.location_id,
        )
    layout = layouts[0]
    if frame_role is ReferenceRole.FIRST_FRAME:
        # The first frame stands at the shot's boundary with the previous cut:
        # entry state only, never the exit state a transition is heading to.
        state_sources = (directing_shot.state_in, scene.state_in)
    else:
        # Last and outgoing handoff frames show where the shot lands. Exit wins;
        # values the shot does not restate persist from the entry state.
        state_sources = (
            directing_shot.state_out,
            directing_shot.state_in,
            scene.state_out,
            scene.state_in,
        )
    holders: dict[str, str] = {}
    for prop_id in shot_prop_ids:
        holder = _state_value(state_sources, prop_id, "holder")
        if holder is None:
            holder = layout.prop_ownership.get(prop_id)
        if holder is not None:
            holders[prop_id] = holder
    prop_ids = set(shot_prop_ids)
    proof_layers = {
        item.prop_id: item.text_layer_sha256
        for item in prop_sheets
        if item.prop_id in prop_ids and item.text_layer_sha256 is not None
    }
    return ExpectedKeyframeFacts(
        visible_character_ids=visible,
        outfit_by_character=MappingProxyType(outfits),
        holder_by_prop=MappingProxyType(holders),
        location_id=scene.location_id,
        geometry_sha256=layout.geometry_sha256,
        light_state=_state_value(state_sources, scene.location_id, "light_state"),
        eyeline=directing_shot.eyeline,
        action_handoff=directing_shot.action_handoff,
        proof_text_sha256_by_prop=MappingProxyType(proof_layers),
    )


# --- comparison (runs against the frozen observation) --------------------------------


@dataclass(frozen=True)
class DimensionFinding:
    """One compared dimension of one frame."""

    dimension: KeyframeDimension
    outcome: DimensionOutcome
    expected: str | None
    observed: str | None
    confidence_bp: int | None = None
    note: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "dimension": self.dimension.value,
            "outcome": self.outcome.value,
            "expected": self.expected,
            "observed": self.observed,
            "confidence_bp": self.confidence_bp,
            "note": self.note,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> DimensionFinding:
        confidence = payload.get("confidence_bp")
        return cls(
            dimension=KeyframeDimension(str(payload["dimension"])),
            outcome=DimensionOutcome(str(payload["outcome"])),
            expected=_optional_str(payload.get("expected")),
            observed=_optional_str(payload.get("observed")),
            confidence_bp=None if confidence is None else int(confidence),
            note=_optional_str(payload.get("note")),
        )


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _text_token(text: str | None) -> str | None:
    if text is None:
        return None
    return f"sha256:{sha256_hex(_normalize_text(text).encode('utf-8'))}"


def _text_matches(observed: str | None, expected: str) -> bool | None:
    if observed is None:
        return None
    return _normalize_text(observed) == _normalize_text(expected)


def _finding(
    dimension: KeyframeDimension,
    inspector: StillMediaInspector,
    confidence_bp: int | None,
    expected: str | None,
    observed: str | None,
    matches: bool | None,
    unobserved_note: str,
) -> DimensionFinding:
    if not inspector.is_calibrated(dimension):
        return DimensionFinding(
            dimension=dimension,
            outcome=DimensionOutcome.UNAVAILABLE,
            expected=expected,
            observed=observed,
            confidence_bp=confidence_bp,
            note="inspector is not calibrated for this dimension",
        )
    if matches is None:
        return DimensionFinding(
            dimension=dimension,
            outcome=DimensionOutcome.UNKNOWN,
            expected=expected,
            observed=observed,
            confidence_bp=confidence_bp,
            note=unobserved_note,
        )
    if not inspector.clears(dimension, confidence_bp):
        return DimensionFinding(
            dimension=dimension,
            outcome=DimensionOutcome.UNKNOWN,
            expected=expected,
            observed=observed,
            confidence_bp=confidence_bp,
            note="observation confidence is below the calibrated threshold",
        )
    return DimensionFinding(
        dimension=dimension,
        outcome=DimensionOutcome.MATCH if matches else DimensionOutcome.MISMATCH,
        expected=expected,
        observed=observed,
        confidence_bp=confidence_bp,
        note=None,
    )


def _mapping_findings(
    dimension: KeyframeDimension,
    inspector: StillMediaInspector,
    confidence_bp: int | None,
    expected_pairs: Sequence[tuple[str, str]],
    observed_map: Mapping[str, str] | None,
    unobserved_note: str,
    pair_unobserved_note: str,
) -> DimensionFinding:
    expected_token = ",".join(f"{key}={value}" for key, value in expected_pairs)
    if observed_map is None:
        return _finding(
            dimension,
            inspector,
            confidence_bp,
            expected_token,
            None,
            None,
            unobserved_note,
        )
    observed_pairs: list[str] = []
    unobserved = False
    mismatched = False
    for key, value in expected_pairs:
        observed_value = observed_map.get(key)
        observed_pairs.append(f"{key}={observed_value or '?'}")
        if observed_value is None:
            unobserved = True
        elif observed_value != value:
            mismatched = True
    matches = False if mismatched else None if unobserved else True
    return _finding(
        dimension,
        inspector,
        confidence_bp,
        expected_token,
        ",".join(observed_pairs),
        matches,
        pair_unobserved_note,
    )


def compare_still_frame(
    observation: StillFrameObservation,
    facts: ExpectedKeyframeFacts,
    inspector: StillMediaInspector,
) -> tuple[DimensionFinding, ...]:
    """Compare a frozen media-only observation against the typed expectations."""
    findings: list[DimensionFinding] = []
    confidence = observation.confidence_bp

    if facts.visible_character_ids:
        observed_ids = observation.visible_subject_ids
        matches = (
            None
            if observed_ids is None
            else frozenset(observed_ids) == (facts.visible_character_ids)
        )
        findings.append(
            _finding(
                KeyframeDimension.VISIBLE_IDENTITY,
                inspector,
                confidence.get(KeyframeDimension.VISIBLE_IDENTITY),
                ",".join(sorted(facts.visible_character_ids)),
                None if observed_ids is None else ",".join(sorted(observed_ids)),
                matches,
                "visible identity set not observed",
            )
        )

    if facts.outfit_by_character:
        findings.append(
            _mapping_findings(
                KeyframeDimension.OUTFIT,
                inspector,
                confidence.get(KeyframeDimension.OUTFIT),
                sorted(facts.outfit_by_character.items()),
                observation.outfit_by_character,
                "assigned outfit not observed",
                "outfit for an assigned character not observed",
            )
        )

    if facts.holder_by_prop:
        findings.append(
            _mapping_findings(
                KeyframeDimension.PROP_HOLDER,
                inspector,
                confidence.get(KeyframeDimension.PROP_HOLDER),
                sorted(facts.holder_by_prop.items()),
                observation.holder_by_prop,
                "prop holder not observed",
                "holder for a shot prop not observed",
            )
        )

    expected_geometry = f"{facts.location_id}:{facts.geometry_sha256}"
    if observation.location_id is None and observation.geometry_token is None:
        observed_geometry = None
        matches = None
    else:
        observed_geometry = f"{observation.location_id or '?'}:{observation.geometry_token or '?'}"
        matches = observed_geometry == expected_geometry
    findings.append(
        _finding(
            KeyframeDimension.LOCATION_GEOMETRY,
            inspector,
            confidence.get(KeyframeDimension.LOCATION_GEOMETRY),
            expected_geometry,
            observed_geometry,
            matches,
            "location geometry not observed",
        )
    )

    if facts.light_state is not None:
        findings.append(
            _finding(
                KeyframeDimension.LIGHT,
                inspector,
                confidence.get(KeyframeDimension.LIGHT),
                facts.light_state,
                observation.light_state,
                None
                if observation.light_state is None
                else observation.light_state == facts.light_state,
                "light state not observed",
            )
        )

    findings.append(
        _finding(
            KeyframeDimension.EYELINE,
            inspector,
            confidence.get(KeyframeDimension.EYELINE),
            _text_token(facts.eyeline),
            _text_token(observation.eyeline),
            _text_matches(observation.eyeline, facts.eyeline),
            "eyeline not observed",
        )
    )

    if facts.proof_text_sha256_by_prop:
        expected_layers = sorted(facts.proof_text_sha256_by_prop.items())
        expected_token = ",".join(f"{prop}={layer}" for prop, layer in expected_layers)
        observed_token = _text_token(observation.proof_text)
        if observation.proof_text is None:
            matches = None
            note = "visible proof text not observed"
        elif len(expected_layers) > 1:
            matches = None
            note = "multiple proof text layers expected; per-layer observation required"
        else:
            matches = (
                sha256_hex(_normalize_text(observation.proof_text).encode("utf-8"))
                == expected_layers[0][1]
            )
            note = None
        findings.append(
            _finding(
                KeyframeDimension.PROOF_TEXT,
                inspector,
                confidence.get(KeyframeDimension.PROOF_TEXT),
                expected_token,
                observed_token,
                matches,
                note or "visible proof text not observed",
            )
        )

    findings.append(
        _finding(
            KeyframeDimension.HANDOFF,
            inspector,
            confidence.get(KeyframeDimension.HANDOFF),
            _text_token(facts.action_handoff),
            _text_token(observation.handoff),
            _text_matches(observation.handoff, facts.action_handoff),
            "handoff not observed",
        )
    )

    compared = set(facts.compared_dimensions())
    return tuple(finding for finding in findings if finding.dimension in compared)


# --- result -------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameCheck:
    """Evidence for one bound keyframe.

    ``bytes_checksum_verified`` is ``True`` only after the loaded bytes matched
    the binding checksum, ``False`` when they did not, and ``None`` when no
    reader was provided to attempt the verification.
    """

    role: ReferenceRole
    subject_id: str
    asset_id: UUID
    asset_version: int
    asset_sha256: str
    bytes_checksum_verified: bool | None
    outcome: FrameOutcome
    observation_sha256: str | None
    findings: tuple[DimensionFinding, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "subject_id": self.subject_id,
            "asset_id": str(self.asset_id),
            "asset_version": self.asset_version,
            "asset_sha256": self.asset_sha256,
            "bytes_checksum_verified": self.bytes_checksum_verified,
            "outcome": self.outcome.value,
            "observation_sha256": self.observation_sha256,
            "findings": [finding.as_payload() for finding in self.findings],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> FrameCheck:
        return cls(
            role=ReferenceRole(str(payload["role"])),
            subject_id=str(payload["subject_id"]),
            asset_id=UUID(str(payload["asset_id"])),
            asset_version=int(payload["asset_version"]),
            asset_sha256=str(payload["asset_sha256"]),
            bytes_checksum_verified=(
                None
                if payload.get("bytes_checksum_verified") is None
                else bool(payload["bytes_checksum_verified"])
            ),
            outcome=FrameOutcome(str(payload["outcome"])),
            observation_sha256=_optional_str(payload.get("observation_sha256")),
            findings=tuple(
                DimensionFinding.from_payload(item) for item in (payload.get("findings") or [])
            ),
        )


@dataclass(frozen=True)
class KeyframePreflightResult:
    """Durable pre-motion still-frame verdict for one routed shot attempt input."""

    result_id: UUID
    episode_id: UUID
    shot_id: str
    status: KeyframePreflightStatus
    input_sha256: str
    prompt_manifest_sha256: str
    route_template_id: str
    route_semantic_template_sha256: str | None
    route_supports_still_frames: bool
    required_frame_roles: frozenset[ReferenceRole]
    evaluator_id: str | None
    evaluator_version: str | None
    evaluator_source_label: str | None
    capability_sha256: str | None
    evaluated_at: datetime
    frames: tuple[FrameCheck, ...] = ()

    @property
    def scope(self) -> str:
        return KEYFRAME_SCOPE

    def summary(self) -> dict[str, object]:
        frames = {
            f"{frame.role.value}:{frame.subject_id}": {
                "outcome": frame.outcome.value,
                "bytes_checksum_verified": frame.bytes_checksum_verified,
                "dimensions": {
                    finding.dimension.value: finding.outcome.value for finding in frame.findings
                },
            }
            for frame in self.frames
        }
        return {
            "status": self.status.value,
            "scope": self.scope,
            "shot_id": self.shot_id,
            "input_sha256": self.input_sha256,
            "evaluator": self.evaluator_id,
            "frames": frames,
        }

    def as_payload(self) -> dict[str, object]:
        return {
            "result_id": str(self.result_id),
            "episode_id": str(self.episode_id),
            "shot_id": self.shot_id,
            "status": self.status.value,
            "scope": self.scope,
            "input_sha256": self.input_sha256,
            "prompt_manifest_sha256": self.prompt_manifest_sha256,
            "route": {
                "template_id": self.route_template_id,
                "semantic_template_sha256": self.route_semantic_template_sha256,
                "supports_still_frames": self.route_supports_still_frames,
            },
            "required_frame_roles": sorted(role.value for role in self.required_frame_roles),
            "evaluator": {
                "id": self.evaluator_id,
                "version": self.evaluator_version,
                "source_label": self.evaluator_source_label,
                "capability_sha256": self.capability_sha256,
            },
            "evaluated_at": self.evaluated_at.isoformat(),
            "frames": [frame.as_payload() for frame in self.frames],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> KeyframePreflightResult:
        evaluator = payload.get("evaluator") or {}
        route = payload.get("route") or {}
        return cls(
            result_id=UUID(str(payload["result_id"])),
            episode_id=UUID(str(payload["episode_id"])),
            shot_id=str(payload["shot_id"]),
            status=KeyframePreflightStatus(str(payload["status"])),
            input_sha256=str(payload["input_sha256"]),
            prompt_manifest_sha256=str(payload["prompt_manifest_sha256"]),
            route_template_id=str(route.get("template_id")),
            route_semantic_template_sha256=_optional_str(route.get("semantic_template_sha256")),
            route_supports_still_frames=bool(route.get("supports_still_frames")),
            required_frame_roles=frozenset(
                ReferenceRole(role) for role in (payload.get("required_frame_roles") or [])
            ),
            evaluator_id=_optional_str(evaluator.get("id")),
            evaluator_version=_optional_str(evaluator.get("version")),
            evaluator_source_label=_optional_str(evaluator.get("source_label")),
            capability_sha256=_optional_str(evaluator.get("capability_sha256")),
            evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
            frames=tuple(FrameCheck.from_payload(item) for item in (payload.get("frames") or [])),
        )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def keyframe_preflight_input_sha256(
    *,
    episode_id: UUID,
    shot_id: str,
    prompt_manifest_sha256: str,
    route_template_sha256: str,
    frame_specs: Sequence[tuple[ReferenceRole, str, UUID, int, str]],
    evaluator: StillMediaInspector | None,
    facts_by_role: Mapping[ReferenceRole, ExpectedKeyframeFacts],
    required_frame_roles: frozenset[ReferenceRole],
) -> str:
    """Hash every result input so a changed source, route or evaluator invalidates it.

    The selected workflow template enters through ``route_template_sha256``
    (callers pass :func:`semantic_template_sha256`, which covers the control and
    semantic role ports): a PASS recorded for one route can never be replayed for
    another. Evaluation time is deliberately excluded: identical inputs replay
    identically regardless of when the replay runs.
    """
    return canonical_hash(
        {
            "episode_id": str(episode_id),
            "shot_id": shot_id,
            "prompt_manifest_sha256": prompt_manifest_sha256,
            "route_template_sha256": route_template_sha256,
            "frames": [
                {
                    "role": role.value,
                    "subject_id": subject_id,
                    "asset_id": str(asset_id),
                    "asset_version": asset_version,
                    "asset_sha256": asset_sha256,
                }
                for role, subject_id, asset_id, asset_version, asset_sha256 in sorted(
                    frame_specs, key=lambda item: (item[0].value, item[1], str(item[2]))
                )
            ],
            "evaluator": None
            if evaluator is None
            else {
                "id": evaluator.evaluator_id,
                "version": evaluator.evaluator_version,
                "source_label": evaluator.source_label,
                "capability_sha256": evaluator.capability_sha256(),
            },
            "facts_sha256": {
                role.value: facts.facts_digest()
                for role, facts in sorted(facts_by_role.items(), key=lambda item: item[0].value)
            },
            "required_frame_roles": sorted(role.value for role in required_frame_roles),
        }
    )


def _frame_outcome(findings: Sequence[DimensionFinding]) -> FrameOutcome:
    outcomes = {finding.outcome for finding in findings}
    if DimensionOutcome.MISMATCH in outcomes:
        return FrameOutcome.BLOCKED
    if DimensionOutcome.UNKNOWN in outcomes or DimensionOutcome.UNAVAILABLE in outcomes:
        return FrameOutcome.UNKNOWN
    return FrameOutcome.PASS


def _blocked_frame(
    role: ReferenceRole,
    subject_id: str,
    asset_id: UUID,
    asset_version: int,
    asset_sha256: str,
    facts: ExpectedKeyframeFacts,
    *,
    bytes_checksum_verified: bool | None,
    outcome: FrameOutcome,
    note: str,
) -> FrameCheck:
    finding_outcome = (
        DimensionOutcome.UNKNOWN
        if outcome is FrameOutcome.BLOCKED
        else DimensionOutcome.UNAVAILABLE
    )
    findings = tuple(
        DimensionFinding(
            dimension=dimension,
            outcome=finding_outcome,
            expected=None,
            observed=None,
            confidence_bp=None,
            note=note,
        )
        for dimension in facts.compared_dimensions()
    )
    return FrameCheck(
        role=role,
        subject_id=subject_id,
        asset_id=asset_id,
        asset_version=asset_version,
        asset_sha256=asset_sha256,
        bytes_checksum_verified=bytes_checksum_verified,
        outcome=outcome,
        observation_sha256=None,
        findings=findings,
    )


def run_keyframe_preflight(
    db: Database,
    *,
    episode_id: UUID,
    shot_id: str,
    manifest: PromptManifest,
    expected: Mapping[tuple[ReferenceRole, str], ExpectedReference],
    facts_by_role: Mapping[ReferenceRole, ExpectedKeyframeFacts],
    required_frame_roles: frozenset[ReferenceRole],
    template: WorkflowTemplate,
    inspector: StillMediaInspector | None,
    read_frame_bytes: Callable[[UUID, int, str], bytes] | None,
    at: datetime,
) -> KeyframePreflightResult:
    """Observe, compare and durably record the pre-motion still-frame check.

    Replay with identical inputs returns the recorded evidence untouched (no
    re-observation, no duplicate event); a changed route template, typed
    expectation, frame binding or evaluator configuration invalidates the
    cached result. The selected route's still-frame capability is checked
    BEFORE any replay: a prior PASS recorded for a still-capable route can
    never wave a stillless route through. Frame roles come from the typed
    binding keys, never from list order; each frame is compared against the
    facts of its own role (entry state for the first frame, exit state for
    the last and handoff frames); and the observer never receives an intended
    fact or prompt text.

    Concurrency: the inspector runs with no DB lock held. The evidence append
    is single-flight — the write transaction takes a transaction-scoped
    advisory lock on the deterministic aggregate id and rechecks for a
    committed result, so two concurrent callers with identical inputs produce
    exactly one durable event and both return that committed result.
    """
    if at.tzinfo is None or at.utcoffset() is None:
        raise SchemaInvalid("keyframe preflight requires an aware evaluation instant")
    frame_specs: list[tuple[ReferenceRole, str, UUID, int, str]] = [
        (
            role,
            subject,
            reference.asset_id,
            reference.asset_version,
            reference.asset_sha256,
        )
        for (role, subject), reference in expected.items()
        if role in FRAME_ROLES
    ]
    frame_specs.sort(key=lambda item: (item[0].value, item[1], str(item[2])))
    for role, *_rest in frame_specs:
        if role not in facts_by_role:
            raise SchemaInvalid(
                "keyframe preflight requires typed facts for every bound frame role",
                frame_role=role.value,
            )
    route_semantic_sha256 = semantic_template_sha256(template)
    still_route = route_supports_still_frames(template)
    # Route capability precedes any cached replay: a PASS recorded for a
    # still-capable route must never be reused for a route without still-frame
    # support, whatever evidence sits under nearby aggregate ids.
    if frame_specs and not still_route:
        raise UnsupportedControl(
            "bound keyframes require a route with still-frame support",
            template_id=template.template_id,
            roles=sorted({role.value for role, *_ in frame_specs}),
        )
    input_sha256 = keyframe_preflight_input_sha256(
        episode_id=episode_id,
        shot_id=shot_id,
        prompt_manifest_sha256=manifest.content_sha256,
        route_template_sha256=route_semantic_sha256,
        frame_specs=frame_specs,
        evaluator=inspector,
        facts_by_role=facts_by_role,
        required_frame_roles=required_frame_roles,
    )
    result_id = uuid5(
        RENDERING_NAMESPACE, f"keyframe-preflight:{episode_id}:{shot_id}:{input_sha256}"
    )

    def recorded_result(tx: object) -> KeyframePreflightResult | None:
        for event in list_events(tx, result_id):
            payload = dict(event.payload)
            if payload.get("input_sha256") == input_sha256:
                return KeyframePreflightResult.from_payload(payload)
        return None

    with db.transaction(readonly=True) as tx:
        recorded = recorded_result(tx)
    if recorded is not None:
        return recorded

    frames: list[FrameCheck] = []
    if not frame_specs:
        status = KeyframePreflightStatus.NOT_APPLICABLE
    else:
        for role, subject, asset_id, asset_version, asset_sha256 in frame_specs:
            role_facts = facts_by_role[role]
            if inspector is None or read_frame_bytes is None:
                frames.append(
                    _blocked_frame(
                        role,
                        subject,
                        asset_id,
                        asset_version,
                        asset_sha256,
                        role_facts,
                        bytes_checksum_verified=None,
                        outcome=FrameOutcome.UNKNOWN,
                        note="still-frame inspector or frame byte reader was not provided",
                    )
                )
                continue
            frame_bytes = read_frame_bytes(asset_id, asset_version, asset_sha256)
            if sha256_hex(frame_bytes) != asset_sha256:
                frames.append(
                    _blocked_frame(
                        role,
                        subject,
                        asset_id,
                        asset_version,
                        asset_sha256,
                        role_facts,
                        bytes_checksum_verified=False,
                        outcome=FrameOutcome.BLOCKED,
                        note="frame bytes failed the binding checksum; observation refused",
                    )
                )
                continue
            observation = inspector.observe(
                FrameAsset(
                    asset_id=asset_id,
                    asset_version=asset_version,
                    asset_sha256=asset_sha256,
                    payload=frame_bytes,
                )
            )
            findings = compare_still_frame(observation, role_facts, inspector)
            frames.append(
                FrameCheck(
                    role=role,
                    subject_id=subject,
                    asset_id=asset_id,
                    asset_version=asset_version,
                    asset_sha256=asset_sha256,
                    bytes_checksum_verified=True,
                    outcome=_frame_outcome(findings),
                    observation_sha256=observation.observation_sha256(),
                    findings=findings,
                )
            )
        outcomes = {frame.outcome for frame in frames}
        if FrameOutcome.BLOCKED in outcomes:
            status = KeyframePreflightStatus.BLOCKED
        elif FrameOutcome.UNKNOWN in outcomes:
            status = KeyframePreflightStatus.UNKNOWN
        else:
            status = KeyframePreflightStatus.PASS

    result = KeyframePreflightResult(
        result_id=result_id,
        episode_id=episode_id,
        shot_id=shot_id,
        status=status,
        input_sha256=input_sha256,
        prompt_manifest_sha256=manifest.content_sha256,
        route_template_id=template.template_id,
        route_semantic_template_sha256=route_semantic_sha256,
        route_supports_still_frames=still_route,
        required_frame_roles=frozenset(required_frame_roles),
        evaluator_id=None if inspector is None else inspector.evaluator_id,
        evaluator_version=None if inspector is None else inspector.evaluator_version,
        evaluator_source_label=None if inspector is None else inspector.source_label,
        capability_sha256=None if inspector is None else inspector.capability_sha256(),
        evaluated_at=at,
        frames=tuple(frames),
    )
    # Single-flight durable append: no DB lock is held over the inspector. The
    # write transaction serialises on a transaction-scoped advisory lock keyed
    # by the deterministic aggregate id and rechecks for a committed result, so
    # the concurrency loser returns the committed winner's evidence instead of
    # appending a duplicate.
    with db.transaction() as tx:
        tx.execute(
            f"SELECT pg_advisory_xact_lock(hashtextextended(%s, {_PREFLIGHT_LOCK_SEED}))",
            (f"keyframe-preflight:{result_id}",),
        )
        committed = recorded_result(tx)
        if committed is None:
            append_event(
                tx,
                aggregate_type=KEYFRAME_AGGREGATE_TYPE,
                aggregate_id=result_id,
                event_type=KEYFRAME_PREFLIGHT_EVENT,
                payload=result.as_payload(),
                correlation_id=result_id,
                occurred_at=at,
            )
    return committed if committed is not None else result


def ensure_keyframe_preflight_allows_dispatch(result: KeyframePreflightResult) -> None:
    """Gate a routed attempt on the recorded pre-motion verdict.

    ``PASS`` and ``NOT_APPLICABLE`` proceed; a known mismatch (``BLOCKED``) or
    an unverified/uncalibrated check (``UNKNOWN``) blocks before any budget
    hold. A keyframe ``PASS`` still certifies still frames only — never a
    motion certification.
    """
    if result.status in (
        KeyframePreflightStatus.PASS,
        KeyframePreflightStatus.NOT_APPLICABLE,
    ):
        return
    raise KeyframePreflightFailed(
        "pre-motion keyframe preflight blocked the routed attempt before any budget hold",
        **result.summary(),
    )


__all__ = [
    "KEYFRAME_AGGREGATE_TYPE",
    "KEYFRAME_PREFLIGHT_EVENT",
    "KEYFRAME_SCOPE",
    "FRAME_ROLES",
    "DimensionFinding",
    "DimensionOutcome",
    "ExpectedKeyframeFacts",
    "FrameAsset",
    "FrameCheck",
    "FrameOutcome",
    "KeyframeDimension",
    "KeyframePreflightFailed",
    "KeyframePreflightResult",
    "KeyframePreflightStatus",
    "StillFrameObservation",
    "StillMediaInspector",
    "build_expected_keyframe_facts",
    "compare_still_frame",
    "ensure_keyframe_preflight_allows_dispatch",
    "keyframe_preflight_input_sha256",
    "route_supports_still_frames",
    "run_keyframe_preflight",
]
