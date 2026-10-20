from __future__ import annotations

import pytest
from pydantic import ValidationError

from microdrama.config import Settings
from microdrama.contracts.enums import EffectKind, ExecutionMode
from microdrama.contracts.errors import EffectDenied


def test_defaults_are_offline_with_every_effect_disabled() -> None:
    s = Settings()
    assert s.execution_mode is ExecutionMode.OFFLINE_MOCK
    assert s.is_offline_mock
    for effect in EffectKind:
        assert not s.effect_allowed(effect)
        with pytest.raises(EffectDenied):
            s.require_effect(effect, what="test")


def test_from_env_with_empty_environment_is_offline() -> None:
    s = Settings.from_env({})
    assert s.execution_mode is ExecutionMode.OFFLINE_MOCK
    assert not any(s.effect_allowed(e) for e in EffectKind)


@pytest.mark.parametrize(
    "flag", ["paid_requests_enabled", "cloud_resources_enabled", "public_actions_enabled"]
)
def test_offline_mode_cannot_enable_any_effect(flag: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{flag: True})


def test_env_cannot_enable_effects_in_offline_mode() -> None:
    with pytest.raises(ValidationError):
        Settings.from_env({"MICRODRAMA_PAID_REQUESTS_ENABLED": "true"})


def test_mode_bounds_which_switches_may_turn_on() -> None:
    # A paid benchmark may not post publicly even if the switch is set.
    with pytest.raises(ValidationError):
        Settings(execution_mode=ExecutionMode.PAID_BENCHMARK, public_actions_enabled=True)
    s = Settings(execution_mode=ExecutionMode.PAID_BENCHMARK)
    # Mode alone does not enable anything; the explicit switch is still required.
    assert not s.effect_allowed(EffectKind.PAID_REQUEST)


def test_invalid_boolean_env_value_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings.from_env({"MICRODRAMA_PUBLIC_ACTIONS_ENABLED": "maybe"})


def test_episode_cap_cannot_exceed_ten_dollars() -> None:
    with pytest.raises(ValidationError):
        Settings(episode_cap_micro_usd=10_000_001)
    with pytest.raises(ValidationError):
        Settings(episode_cap_micro_usd=10.0)  # floats are never accepted for money
