"""Runtime configuration and the external-effect switchboard.

Default execution mode is OFFLINE_MOCK (SPEC §12): paid requests, cloud resource
creation and public actions are disabled and *cannot* be enabled in that mode.
Any code path that would cause such an effect must call
``Settings.require_effect`` first; it raises ``EffectDenied`` unless the mode
and the explicit switch both allow it.

Settings never carry secret values. Credentials are referenced by name through
the credential-reference registry (T006) and resolved only at the edge.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from microdrama.contracts.enums import EffectKind, ExecutionMode
from microdrama.contracts.errors import EffectDenied

ENV_PREFIX = "MICRODRAMA_"

_EFFECT_FLAG = {
    EffectKind.PAID_REQUEST: "paid_requests_enabled",
    EffectKind.CLOUD_RESOURCE: "cloud_resources_enabled",
    EffectKind.PUBLIC_ACTION: "public_actions_enabled",
}

# Which effects each non-mock mode may ever enable. Enabling still requires the
# explicit switch; the mode only bounds what the switch may turn on.
_MODE_ALLOWS: dict[ExecutionMode, frozenset[EffectKind]] = {
    ExecutionMode.OFFLINE_MOCK: frozenset(),
    ExecutionMode.PAID_BENCHMARK: frozenset({EffectKind.PAID_REQUEST, EffectKind.CLOUD_RESOURCE}),
    ExecutionMode.CONTROLLED_ACCOUNT_TEST: frozenset({EffectKind.PUBLIC_ACTION}),
    ExecutionMode.PRODUCTION: frozenset(EffectKind),
}


class Settings(BaseModel):
    """Process configuration. Immutable once constructed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_mode: ExecutionMode = ExecutionMode.OFFLINE_MOCK
    paid_requests_enabled: bool = False
    cloud_resources_enabled: bool = False
    public_actions_enabled: bool = False

    database_url: str | None = None
    redis_url: str | None = None
    object_store_root: Path | None = None
    # Name of a credential reference (never a secret value) used to sign
    # review-session cookies; resolved by the credential store at startup.
    session_secret_ref: str = "credref:review-session-hmac"

    episode_cap_micro_usd: int = Field(default=10_000_000, ge=0, strict=True)

    @model_validator(mode="after")
    def _effects_bounded_by_mode(self) -> Settings:
        allowed = _MODE_ALLOWS[self.execution_mode]
        for effect, flag in _EFFECT_FLAG.items():
            if getattr(self, flag) and effect not in allowed:
                raise ValueError(
                    f"{flag}=true is not permitted in execution_mode={self.execution_mode.value}"
                )
        if self.episode_cap_micro_usd > 10_000_000:
            raise ValueError(
                "episode cap may not exceed the confirmed US$10 (10,000,000 micro-USD)"
            )
        return self

    @property
    def is_offline_mock(self) -> bool:
        return self.execution_mode is ExecutionMode.OFFLINE_MOCK

    def effect_allowed(self, effect: EffectKind) -> bool:
        return effect in _MODE_ALLOWS[self.execution_mode] and bool(
            getattr(self, _EFFECT_FLAG[effect])
        )

    def require_effect(self, effect: EffectKind, *, what: str) -> None:
        """Raise ``EffectDenied`` unless ``effect`` is explicitly enabled."""
        if not self.effect_allowed(effect):
            raise EffectDenied(
                f"{effect.value} denied for {what!r} in execution_mode={self.execution_mode.value}"
            )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ

        def flag(name: str) -> bool:
            raw = env.get(ENV_PREFIX + name, "false").strip().lower()
            if raw not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError(f"{ENV_PREFIX}{name} must be a boolean, got {raw!r}")
            return raw in {"true", "1", "yes"}

        values: dict[str, object] = {
            "execution_mode": env.get(ENV_PREFIX + "EXECUTION_MODE", ExecutionMode.OFFLINE_MOCK),
            "paid_requests_enabled": flag("PAID_REQUESTS_ENABLED"),
            "cloud_resources_enabled": flag("CLOUD_RESOURCES_ENABLED"),
            "public_actions_enabled": flag("PUBLIC_ACTIONS_ENABLED"),
        }
        for key in ("DATABASE_URL", "REDIS_URL", "OBJECT_STORE_ROOT", "SESSION_SECRET_REF"):
            if (value := env.get(ENV_PREFIX + key)) is not None:
                values[key.lower()] = value
        return cls.model_validate(values)
