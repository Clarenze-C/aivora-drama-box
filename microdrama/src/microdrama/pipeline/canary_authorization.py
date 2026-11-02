"""The T045/R11 canary authorization document (schema exactly per the R11 list).

The authorization is the operator's signed-off plan for one bounded paid benchmark:
operator/change reference, hard stop and wall clock, the quote with every R10 field,
spend/storage/prompt/attempt caps, the rights route, the pins (the full image
reference, workflow, node schema, output controls, preset), ``credref:`` names only,
the namespace and provider account label, and the prompt/reference inputs as content
hashes.

It never carries secret values and never carries prompt text — only the sha256 of the
canonical prompt objects, which ``execute`` verifies before anything is submitted.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from microdrama.contracts.errors import SchemaInvalid

_NAMESPACE_RE = re.compile(r"[a-z0-9]{4,12}")
_ACCOUNT_REF_RE = re.compile(r"acct:[a-z0-9][a-z0-9._\-]{1,120}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
#: T045-FIX B-B2: a full image reference — an explicit registry host (so it can never
#: resolve to docker.io/library), at least one repository path segment, and a sha256
#: digest pinned by digest (never a mutable tag).
_IMAGE_REF_RE = re.compile(
    r"[a-z0-9][a-z0-9._\-]*\.[a-z0-9._\-]*(:[0-9]{1,5})?"
    r"(/[a-z0-9][a-z0-9._\-]*)+"
    r"@sha256:[0-9a-f]{64}"
)


def _credref(value: str) -> str:
    if not value.startswith("credref:") or len(value) <= len("credref:"):
        raise ValueError("credential must be a credref: name, never a secret value")
    return value


def _sha256(value: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError("content pins must be lowercase sha256 hex digests")
    return value


class CanaryQuote(BaseModel):
    """The operator quote snapshot; USD only, every R10 field present."""

    quote_id: str = Field(min_length=1)
    currency: str
    captured_at: datetime
    expires_at: datetime
    compute_micro_usd_per_hour: int
    container_disk_gb: int
    container_storage_micro_usd_per_gb_month: int
    persistent_volume_gb: int
    persistent_storage_micro_usd_per_gb_month: int
    max_storage_exposure_micro_usd: int
    allowed_gpu_types: list[str] = Field(min_length=1)
    host_ram_gb_by_gpu: dict[str, int] = Field(min_length=1)
    maximum_runtime_ms: int
    maximum_exposure_micro_usd: int

    @model_validator(mode="after")
    def _quote_rules(self) -> CanaryQuote:
        if self.currency != "USD":
            raise ValueError("the canary quote must be denominated in USD")
        if self.expires_at <= self.captured_at:
            raise ValueError("the quote window must be non-empty")
        positive = (
            self.compute_micro_usd_per_hour,
            self.container_disk_gb,
            self.container_storage_micro_usd_per_gb_month,
            self.persistent_storage_micro_usd_per_gb_month,
            self.maximum_runtime_ms,
            self.maximum_exposure_micro_usd,
            self.max_storage_exposure_micro_usd,
        )
        if min(positive) <= 0 or self.persistent_volume_gb < 0:
            raise ValueError("quote compute/storage rates and exposure bounds must be positive")
        if any(gpu not in self.host_ram_gb_by_gpu for gpu in self.allowed_gpu_types):
            raise ValueError("every allowed GPU needs an attested host-RAM profile")
        return self


class CanaryCaps(BaseModel):
    """Hard caps: spend includes storage exposure and the shutdown reserve."""

    max_spend_micro_usd: int
    max_storage_gb: int
    max_prompts: int
    max_attempts: int

    @model_validator(mode="after")
    def _cap_rules(self) -> CanaryCaps:
        if min(self.max_spend_micro_usd, self.max_storage_gb, self.max_prompts) <= 0:
            raise ValueError("spend/storage/prompt caps must be positive")
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("attempts are capped at three per prompt by the render contract")
        return self


class CanaryRights(BaseModel):
    """The exact rights route the canary runs under."""

    rights_route_id: str = Field(min_length=1)
    rights_subject_ref: str = Field(min_length=1)
    rights_subject_kind: str
    rights_version: int
    territories: list[str] = Field(min_length=1)
    rights_evidence_id: str = Field(min_length=1)
    eligible_until: datetime


class CanaryPins(BaseModel):
    """The pinned contract the run may not drift from (R10 limitation recorded)."""

    image_ref: str
    workflow_sha256: str
    node_schema_sha256: str
    output_controls_sha256: str
    preset_id: str
    preset_version: int
    required_controls: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _pin_rules(self) -> CanaryPins:
        # T045-FIX B-B2: the pin is the FULL image reference exactly as create must
        # send it — <registry>/<repo>@sha256:<64 hex>. The runner never invents a
        # repository name, so a fictional default image can never satisfy the pin.
        if not _IMAGE_REF_RE.fullmatch(self.image_ref):
            raise ValueError(
                "image_ref must be the full reference <registry>/<repo>@sha256:<64 hex>"
            )
        for field in (
            "workflow_sha256",
            "node_schema_sha256",
            "output_controls_sha256",
        ):
            _sha256(getattr(self, field))
        if not self.preset_id or self.preset_version < 1:
            raise ValueError("the canary pins one enabled preset id and version")
        return self


class CanaryAuthorization(BaseModel):
    """One operator-authorized canary run (R11). USD-only, credref-only, hash-pinned."""

    operator: str = Field(min_length=1)
    change_ref: str = Field(min_length=1)
    hard_stop_utc: datetime
    max_wall_seconds: int
    quote: CanaryQuote
    caps: CanaryCaps
    rights: CanaryRights
    pins: CanaryPins
    runpod_credential_ref: str
    comfy_credential_ref: str
    namespace: str
    provider_account_ref: str
    prompt_sha256: list[str] = Field(min_length=1)
    reference_sha256: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _authorization_rules(self) -> CanaryAuthorization:
        if self.max_wall_seconds <= 0:
            raise ValueError("max_wall_seconds must be positive")
        # T045-FIX B-S2: the wall clock is bounded by the runtime the quote's exposure
        # ceiling was proven for - a longer run was never priced.
        if self.max_wall_seconds * 1000 > self.quote.maximum_runtime_ms:
            raise ValueError(
                "max_wall_seconds exceeds the quote's maximum_runtime_ms; the quote "
                "never priced a run that long"
            )
        if not _NAMESPACE_RE.fullmatch(self.namespace):
            raise ValueError("namespace must be 4-12 lowercase alphanumerics")
        if not _ACCOUNT_REF_RE.fullmatch(self.provider_account_ref):
            raise ValueError("provider_account_ref must be an acct: label (non-secret)")
        self.runpod_credential_ref = _credref(self.runpod_credential_ref)
        self.comfy_credential_ref = _credref(self.comfy_credential_ref)
        for pin in self.prompt_sha256:
            _sha256(pin)
        for pin in self.reference_sha256:
            _sha256(pin)
        if len(set(self.prompt_sha256)) != len(self.prompt_sha256):
            raise ValueError("duplicate prompt content pin")
        # The caps bound the quote: the whole spend cap can never exceed the quoted
        # exposure ceiling, and the storage cap bounds the quoted volume.
        if self.caps.max_spend_micro_usd > self.quote.maximum_exposure_micro_usd:
            raise ValueError("the spend cap exceeds the quote's maximum exposure")
        if self.caps.max_storage_gb < self.quote.persistent_volume_gb:
            raise ValueError("the storage cap is below the quoted persistent volume")
        return self


def authorization_sha256(path: str | Path) -> str:
    """sha256 of the authorization file bytes — the value execute must be shown."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_canary_authorization(path: str | Path) -> tuple[CanaryAuthorization, str]:
    """Parse and validate the authorization; returns (model, file sha256).

    Raises ``SchemaInvalid`` for anything that is not exactly a valid authorization
    document — never a Python traceback, and no secret is ever read.
    """
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaInvalid("canary authorization is not valid JSON") from exc
    if not isinstance(document, dict):
        raise SchemaInvalid("canary authorization must be a JSON object")
    try:
        return CanaryAuthorization.model_validate(document), digest
    except ValueError as exc:
        raise SchemaInvalid(f"canary authorization is invalid: {exc}") from exc


def prompt_pin(prompt: dict[str, Any]) -> str:
    """The content hash of one canonical prompt object (what the pins name)."""
    from microdrama.contracts.hashing import canonical_hash

    return canonical_hash(prompt)


__all__ = [
    "CanaryAuthorization",
    "CanaryCaps",
    "CanaryPins",
    "CanaryQuote",
    "CanaryRights",
    "authorization_sha256",
    "load_canary_authorization",
    "prompt_pin",
]
