"""Local immutable inputs for the private T031 experiment; no provider effects."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictInt,
    field_validator,
    model_validator,
)

from microdrama.contracts.errors import PolicyDenied, SchemaInvalid

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
SCREEN_SAMPLE_IDS = ("S01-R1", "S03-R1", "S07-R1")
SHA256_PATTERN = r"^[0-9a-f]{64}$"
IMAGE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$"
CREDREF_PATTERN = r"^credref:[A-Za-z0-9][A-Za-z0-9._:-]*$"
_ALLOWED_GPUS = {
    "NVIDIA A40",
    "A40",
    "NVIDIA RTX A6000",
    "NVIDIA L40",
    "NVIDIA L40S",
    "NVIDIA RTX 6000 Ada Generation",
}
# H-6 (2026-11-10, GLM harness review): the published CPU/no-weights runtime
# attestation (microdrama/deployment/pika-h3-flex/schema-attestation.cpu.json,
# evidence_kind ACTUAL_RUNTIME_CPU_NO_WEIGHTS) and the offline fixture hash to
# the SAME mapped schema hash. A seal built from that JSON is self-consistent,
# so only a machine check can keep it from being relabelled LIVE_PROVIDER: the
# hash is a constant pin and can never authorize live benchmark work.
DENIED_LIVE_SCHEMA_SHA256 = frozenset(
    {"339021b1e3106ee0648b264f0ef1ddc8e1bb68c0374d8d6c7c1a6b0f375ba9ae"}
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return value


def _json_value(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON numbers are not allowed")
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise ValueError("JSON object keys must be strings")
        for item in value.values():
            _json_value(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item)


def canonical_document_bytes(value: BaseModel | dict[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    _json_value(payload)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def document_sha256(value: BaseModel | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_document_bytes(value)).hexdigest()


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _integer_literals(cls, value: Any):
        if isinstance(value, dict):
            for key in ("schema_version", "max_samples", "max_attempts_per_sample"):
                if key in value and type(value[key]) is not int:
                    raise ValueError("version and count fields must be integers")
        return value

    @model_validator(mode="after")
    def _finite_json(self):
        _json_value(self.model_dump(mode="python"))
        return self


class BenchmarkSample(_Document):
    sample_id: str = Field(pattern=r"^S0[1-8]-R[1-3]$")
    shot_id: str = Field(pattern=r"^S0[1-8]$")
    repeat: StrictInt = Field(ge=1, le=3)
    seed: StrictInt = Field(ge=0, le=2**63 - 1)
    input: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _identity(self):
        if self.sample_id != f"{self.shot_id}-R{self.repeat}":
            raise ValueError("sample identity does not match its shot and repeat")
        return self


class BenchmarkPlan(_Document):
    schema_version: Literal[1] = 1
    experiment_id: UUID
    episode_id: UUID
    experiment_nonce: str = Field(default="", max_length=128)
    configuration_id: str = "pika-flex-ref2va-480p-candidate"
    runtime_profile_sha256: str = Field(pattern=SHA256_PATTERN)
    shots: list[dict[str, Any]] = Field(min_length=8, max_length=8)
    samples: list[BenchmarkSample] = Field(min_length=24, max_length=24)
    screen_sample_ids: tuple[str, ...] = SCREEN_SAMPLE_IDS
    logical_reference_slots: list[dict[str, Any]] = Field(default_factory=list)
    max_new_exposure_micro_usd: StrictInt = Field(gt=0, le=8_000_000)
    max_gpu_ms: StrictInt = Field(gt=0, le=14_400_000)
    max_samples: Literal[24] = 24
    max_attempts_per_sample: Literal[1] = 1

    @model_validator(mode="after")
    def _matrix(self):
        shot_ids = [s.get("shot_id") for s in self.shots]
        if any(not isinstance(item, str) for item in shot_ids) or set(shot_ids) != {
            f"S0{i}" for i in range(1, 9)
        }:
            raise ValueError("the eight fixed shot identities are required")
        expected = {f"S0{i}-R{r}" for i in range(1, 9) for r in range(1, 4)}
        if {s.sample_id for s in self.samples} != expected:
            raise ValueError("the exact 24 fixed samples are required")
        if len({s.seed for s in self.samples}) != 24:
            raise ValueError("sample seeds must be distinct")
        if self.screen_sample_ids != SCREEN_SAMPLE_IDS:
            raise ValueError("the three screening sample identities are fixed")
        if any(
            not isinstance(s.get("thai_line"), str) or not s["thai_line"].strip()
            for s in self.shots
        ):
            raise ValueError("each shot requires an explicit Thai test line")
        if any(
            not isinstance(s.get("role"), str) or not isinstance(s.get("subject_id"), str)
            for s in self.logical_reference_slots
        ):
            raise ValueError("logical slot role and subject must be strings")
        keys = [(s.get("role"), s.get("subject_id")) for s in self.logical_reference_slots]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate logical reference slot")
        return self

    @property
    def plan_sha256(self) -> str:
        return document_sha256(self.model_dump(mode="json", exclude={"experiment_id"}))


class BenchmarkSeal(_Document):
    schema_version: Literal[1] = 1
    experiment_id: UUID
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    references: list[dict[str, Any]] = Field(min_length=1)
    port_map: list[dict[str, Any]] = Field(min_length=1)
    runtime_profile: dict[str, Any]
    image_ref: str = Field(pattern=IMAGE_PATTERN)
    node_schema_sha256: str = Field(pattern=SHA256_PATTERN)
    schema_evidence: Literal[
        "UNVERIFIED", "OFFLINE_FIXTURE_ONLY", "LIVE_PROVIDER", "PREDICTED_FROM_PINNED_IMAGE"
    ] = "UNVERIFIED"
    schema_attestation_source: Literal[
        "SELF_ASSERTED", "INDEPENDENT_RUNTIME_CAPTURE", "MANIFEST_PLACEHOLDER_CAPTURE"
    ] = "SELF_ASSERTED"
    # T031 R5c: the prediction tool's capture record (registry manifest digest
    # only - a local image ID is forbidden - placeholder names, tool version,
    # UTC). Required for PREDICTED_FROM_PINNED_IMAGE seals.
    schema_capture: dict[str, Any] = Field(default_factory=dict)
    raw_object_info: dict[str, Any] = Field(default_factory=dict)
    width: StrictInt = 480
    height: StrictInt = 832
    frames: StrictInt = 124
    fps: StrictInt = 24
    rights_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    territories: list[str] = Field(min_length=1)
    eligible_until: datetime
    hard_stop_utc: datetime
    evaluator_policy: dict[str, Any] = Field(default_factory=dict)

    _dates = field_validator("eligible_until", "hard_stop_utc")(_aware)

    @model_validator(mode="after")
    def _bindings(self):
        if (self.width, self.height, self.frames, self.fps) != (480, 832, 124, 24):
            raise ValueError("only the fixed 480p portrait configuration is permitted")
        if self.hard_stop_utc > self.eligible_until:
            raise ValueError("execution deadline exceeds rights eligibility")
        if len(set(self.territories)) != len(self.territories):
            raise ValueError("duplicate territory")
        allowed = {"character_identity", "outfit", "location", "prop", "style", "voice"}
        references = set()
        for item in self.references:
            if (
                item.get("role") not in allowed
                or not isinstance(item.get("subject_id"), str)
                or not item["subject_id"]
            ):
                raise ValueError("unsupported reference role or absent subject")
            try:
                asset = str(UUID(str(item["asset_id"])))
            except (KeyError, TypeError, ValueError):
                raise ValueError("reference asset UUID is required") from None
            version = item.get("asset_version")
            if type(version) is not int or version < 1:
                raise ValueError("asset version must be a positive integer")
            digest = item.get("asset_sha256")
            if not isinstance(digest, str) or not re.fullmatch(SHA256_PATTERN, digest):
                raise ValueError("reference byte hash is required")
            key = (item["role"], item["subject_id"], asset, version, digest)
            if key in references:
                raise ValueError("duplicate sealed reference")
            references.add(key)
        groups = {}
        mapped = set()
        for port in self.port_map:
            if (
                not isinstance(port.get("role"), str)
                or not isinstance(port.get("subject_id"), str)
                or not isinstance(port.get("asset_sha256"), str)
                or type(port.get("asset_version")) is not int
            ):
                raise ValueError("port identity fields have invalid types")
            key = (
                port.get("role"),
                port.get("subject_id"),
                str(port.get("asset_id")),
                port.get("asset_version"),
                port.get("asset_sha256"),
            )
            if key not in references:
                raise ValueError("port has no exact sealed asset/version/hash binding")
            scope = port.get("shot_id")
            if scope is not None and (
                not isinstance(scope, str) or scope not in {f"S0{i}" for i in range(1, 9)}
            ):
                raise ValueError("unknown shot-specific port scope")
            groups.setdefault(scope, []).append(port)
            mapped.add(key)
        if None in groups and len(groups) != 1:
            raise ValueError("shared and shot-specific port maps cannot be mixed")
        if None not in groups and set(groups) != {f"S0{i}" for i in range(1, 9)}:
            raise ValueError("shot-specific ports must cover all eight shots")
        if mapped != references:
            raise ValueError("every sealed asset must have an explicit destination")
        for ports in groups.values():
            destinations = []
            semantic = []
            for port in ports:
                destination = port.get("destination_slot", "")
                if not isinstance(destination, str) or not re.fullmatch(
                    r"ref_(?:images\.ref_image_[0-8]|audios\.ref_audio_[0-2])", destination
                ):
                    raise ValueError("unsupported reference destination")
                audio = destination.startswith("ref_audios.")
                if (port["role"] == "voice") != audio or port.get("media_kind") != (
                    "audio" if audio else "image"
                ):
                    raise ValueError("reference role/media/destination disagree")
                destinations.append(destination)
                semantic.append((port["role"], port["subject_id"]))
            if len(set(destinations)) != len(destinations) or len(set(semantic)) != len(semantic):
                raise ValueError("duplicate destination or multiple anchors for one role/subject")
            if len(ports) > 12 or not any(d.startswith("ref_images.") for d in destinations):
                raise ValueError("reference mode needs an image and at most twelve inputs")
            for prefix in ("ref_images.ref_image_", "ref_audios.ref_audio_"):
                indexes = sorted(
                    int(d.rsplit("_", 1)[1]) for d in destinations if d.startswith(prefix)
                )
                if indexes != list(range(len(indexes))):
                    raise ValueError("reference destinations must use contiguous ordinals")
        return self

    @property
    def sealed_sha256(self) -> str:
        return document_sha256(self)


class AcquisitionQuote(_Document):
    schema_version: Literal[1] = 1
    quote_id: str = Field(min_length=1, max_length=256)
    captured_at: datetime
    expires_at: datetime
    currency: Literal["USD"] = "USD"
    gpu_type: str = "NVIDIA A40"
    host_ram_gb: StrictInt = Field(ge=64)
    compute_micro_usd_per_hour: StrictInt = Field(gt=0)
    container_disk_gb: StrictInt = Field(gt=0)
    persistent_volume_gb: StrictInt = Field(ge=0)
    container_storage_micro_usd_per_gb_month: StrictInt = Field(gt=0)
    persistent_storage_micro_usd_per_gb_month: StrictInt = Field(gt=0)
    max_storage_exposure_micro_usd: StrictInt = Field(gt=0)
    maximum_runtime_ms: StrictInt = Field(gt=0, le=14_400_000)
    source_evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    _dates = field_validator("captured_at", "expires_at")(_aware)

    @model_validator(mode="after")
    def _quote(self):
        if self.expires_at <= self.captured_at or self.expires_at - self.captured_at > timedelta(
            hours=2
        ):
            raise ValueError("quote must have a positive validity window of at most two hours")
        if self.gpu_type not in _ALLOWED_GPUS or self.gpu_type == "A40":
            raise ValueError("quote requires an allowed exact GPU catalog ID")
        if self.compute_micro_usd_per_hour % 3600:
            raise ValueError("quote rate must represent whole micro-USD per GPU-second")
        return self

    @property
    def quote_sha256(self) -> str:
        return document_sha256(self)

    @property
    def allowed_gpu_types(self) -> list[str]:
        return [self.gpu_type]

    @property
    def host_ram_gb_by_gpu(self) -> dict[str, int]:
        return {self.gpu_type: self.host_ram_gb}


class BenchmarkAuthorization(_Document):
    schema_version: Literal[1] = 1
    operator: str = Field(min_length=1, max_length=256)
    change_ref: str = Field(min_length=1, max_length=256)
    experiment_id: UUID
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    sealed_sha256: str = Field(pattern=SHA256_PATTERN)
    episode_id: UUID
    provider_account_ref: str = Field(pattern=r"^acct:[a-z0-9][a-z0-9._-]{1,120}$")
    max_new_exposure_micro_usd: StrictInt = Field(gt=0, le=8_000_000)
    max_gpu_ms: StrictInt = Field(gt=0, le=14_400_000)
    max_samples: Literal[24] = 24
    max_attempts_per_sample: Literal[1] = 1
    hard_stop_utc: datetime
    allowed_gpu_types: list[str] = Field(min_length=1)
    minimum_host_ram_gb: StrictInt = Field(ge=64)
    max_hourly_micro_usd: StrictInt = Field(gt=0, le=860_000)
    max_storage_exposure_micro_usd: StrictInt = Field(gt=0)
    container_disk_gb: StrictInt = Field(gt=0)
    persistent_volume_gb: StrictInt = Field(ge=0)
    shutdown_reserve_micro_usd: StrictInt = Field(gt=0)
    namespace: str = Field(pattern=r"^[a-z0-9]{4,12}$")
    runpod_credential_ref: str = Field(pattern=CREDREF_PATTERN)
    comfy_credential_ref: str = Field(pattern=CREDREF_PATTERN)
    rights_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    _source_sha256: str | None = PrivateAttr(default=None)

    _dates = field_validator("hard_stop_utc")(_aware)

    @model_validator(mode="after")
    def _envelope(self):
        if (
            len(set(self.allowed_gpu_types)) != len(self.allowed_gpu_types)
            or not set(self.allowed_gpu_types) <= _ALLOWED_GPUS
        ):
            raise ValueError("authorization GPU allowlist is invalid")
        if self.allowed_gpu_types[0] == "A40":
            raise ValueError("first allowed GPU must be the exact provider catalog ID")
        if (
            self.shutdown_reserve_micro_usd + self.max_storage_exposure_micro_usd
            >= self.max_new_exposure_micro_usd
        ):
            raise ValueError("storage and shutdown leave no allowance for compute")
        return self

    @property
    def authorization_sha256(self) -> str:
        return self._source_sha256 or document_sha256(self)

    def validate_for(
        self,
        plan: BenchmarkPlan,
        seal: BenchmarkSeal,
        *,
        now: datetime,
        quote: AcquisitionQuote | None = None,
    ) -> None:
        _aware(now)
        if (
            self.experiment_id != plan.experiment_id
            or seal.experiment_id != self.experiment_id
            or self.episode_id != plan.episode_id
        ):
            raise PolicyDenied("benchmark authorization does not name this experiment/account")
        if (
            self.plan_sha256 != plan.plan_sha256
            or seal.plan_sha256 != plan.plan_sha256
            or self.sealed_sha256 != seal.sealed_sha256
        ):
            raise PolicyDenied("benchmark authorization does not match the sealed plan")
        if (
            self.max_new_exposure_micro_usd > plan.max_new_exposure_micro_usd
            or self.max_gpu_ms > plan.max_gpu_ms
        ):
            raise PolicyDenied("benchmark authorization exceeds the prepared envelope")
        if self.hard_stop_utc > seal.hard_stop_utc or now >= min(
            self.hard_stop_utc, seal.eligible_until
        ):
            raise PolicyDenied("benchmark authorization or rights deadline has expired")
        if self.rights_evidence_hash != seal.rights_evidence_hash:
            raise PolicyDenied("benchmark rights evidence differs from the seal")
        if seal.schema_evidence == "PREDICTED_FROM_PINNED_IMAGE":
            # T031 R5c: a predicted schema from the pinned image, accepted only
            # with ALL THREE machine checks (the guarded live comparison at
            # readiness stays mandatory and decisive before every upload).
            if seal.schema_attestation_source != "MANIFEST_PLACEHOLDER_CAPTURE":
                raise PolicyDenied("a predicted schema requires the placeholder capture source")
            capture = seal.schema_capture or {}
            digest = capture.get("manifest_digest")
            if not isinstance(digest, str) or not re.fullmatch(SHA256_PATTERN, digest):
                raise PolicyDenied(
                    "the capture record must carry the registry manifest digest "
                    "(a local image ID is forbidden)"
                )
            if digest != seal.image_ref.rsplit("@sha256:", 1)[-1]:
                raise PolicyDenied("the predicted capture was taken from a different image")
            if seal.node_schema_sha256 in DENIED_LIVE_SCHEMA_SHA256:
                raise PolicyDenied(
                    "the published CPU/no-weights schema hash can never authorize live work"
                )
            if not predicted_enums_match_manifest(seal.raw_object_info):
                raise PolicyDenied(
                    "the predicted schema's model-name enums differ from the pinned "
                    "models.json file names"
                )
        elif seal.schema_evidence == "LIVE_PROVIDER":
            if seal.schema_attestation_source != "INDEPENDENT_RUNTIME_CAPTURE":
                raise PolicyDenied("LIVE schema evidence is only a self-asserted label")
            # H-6: the CPU/no-weights attestation hash is machine-denied for LIVE
            # seals regardless of the label - a self-asserted relabel of the
            # published CPU schema can never qualify a live run.
            if seal.node_schema_sha256 in DENIED_LIVE_SCHEMA_SHA256:
                raise PolicyDenied(
                    "the published CPU/no-weights schema hash can never authorize live work"
                )
        else:
            raise PolicyDenied("fixture or unverified schema cannot authorize live benchmark work")
        if quote is not None:
            if not quote.captured_at <= now < quote.expires_at:
                raise PolicyDenied("benchmark acquisition quote is not current")
            if (
                quote.gpu_type not in self.allowed_gpu_types
                or quote.host_ram_gb < self.minimum_host_ram_gb
            ):
                raise PolicyDenied("benchmark quote hardware is outside the authorized profile")
            if quote.compute_micro_usd_per_hour > self.max_hourly_micro_usd:
                raise PolicyDenied("benchmark quote rate exceeds the authorization ceiling")
            if (
                quote.container_disk_gb > self.container_disk_gb
                or quote.persistent_volume_gb > self.persistent_volume_gb
            ):
                raise PolicyDenied("benchmark quote storage exceeds the authorization")
            if (
                quote.max_storage_exposure_micro_usd > self.max_storage_exposure_micro_usd
                or quote.maximum_runtime_ms > self.max_gpu_ms
            ):
                raise PolicyDenied("benchmark quote exposure exceeds the authorized envelope")


#: T031 R5c: how each pinned models.json folder surfaces in the schema's
#: loader-node enums (folder -> (node, input field)). "pixel_space" and other
#: baked non-file entries are exempt from membership (CON-N4).
SCHEMA_MODEL_FOLDERS: dict[str, tuple[str, str]] = {
    "diffusion_models": ("UNETLoader", "unet_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "vae": ("VAELoader", "vae_name"),
    "loras": ("LoraLoaderModelOnly", "lora_name"),
}


def pinned_model_folders() -> dict[str, list[str]]:
    """The image's models.json folder -> pinned file names (repo deployment copy)."""
    manifest_path = (
        Path(__file__).resolve().parents[3] / "deployment" / "pika-h3-flex" / "models.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    folders: dict[str, list[str]] = {}
    for record in manifest["files"]:
        folder, _, name = record["path"].rpartition("/")
        folders.setdefault(folder, []).append(name)
    return folders


def _enum_values(raw: dict[str, Any], node: str, field: str) -> list[str] | None:
    entry = raw.get(node)
    if not isinstance(entry, dict):
        return None
    spec = entry.get("input", {}).get("required", {}).get(field)
    if not isinstance(spec, list) or not spec or not isinstance(spec[0], list):
        return None
    return [str(item) for item in spec[0]]


def predicted_enums_match_manifest(raw: dict[str, Any]) -> bool:
    """R5c (CON-N4): the model-name enums in ``raw_object_info`` carry every
    pinned models.json file name per folder. Per-folder listing MEMBERSHIP -
    the weight-free schema's baked non-file entries (e.g. ``pixel_space``)
    are exempt."""
    try:
        folders = pinned_model_folders()
    except (OSError, ValueError, KeyError):
        return False
    for folder, (node, field) in SCHEMA_MODEL_FOLDERS.items():
        enum = _enum_values(raw, node, field)
        if enum is None:
            return False
        for name in folders.get(folder, []):
            if name not in enum:
                return False
    return True


def load_document(path: str | Path, model: type[_Document]) -> _Document:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise SchemaInvalid("benchmark input must be a bounded regular JSON file")
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError("benchmark input exceeds its size limit")
        return model.model_validate_json(raw)
    except (ValueError, UnicodeDecodeError):
        # Never include input values: an operator may have pasted a secret in place
        # of a credref. Validation errors are themselves not safe diagnostic text.
        raise SchemaInvalid(
            "benchmark document failed validation", document_kind=model.__name__
        ) from None


def load_benchmark_authorization(path: str | Path) -> tuple[BenchmarkAuthorization, str]:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise SchemaInvalid("benchmark authorization must be a bounded regular file")
    raw = path.read_bytes()
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise SchemaInvalid("benchmark authorization exceeds its size limit")
    try:
        model = BenchmarkAuthorization.model_validate_json(raw)
    except ValueError:
        raise SchemaInvalid("benchmark authorization failed validation") from None
    digest = hashlib.sha256(raw).hexdigest()
    model._source_sha256 = digest
    return model, digest
