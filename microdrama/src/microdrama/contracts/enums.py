"""Closed enumerations shared across modules. Contract-guardian owned."""

from __future__ import annotations

from enum import StrEnum


class ExecutionMode(StrEnum):
    OFFLINE_MOCK = "OFFLINE_MOCK"
    PAID_BENCHMARK = "PAID_BENCHMARK"
    CONTROLLED_ACCOUNT_TEST = "CONTROLLED_ACCOUNT_TEST"
    PRODUCTION = "PRODUCTION"


class EffectKind(StrEnum):
    PAID_REQUEST = "PAID_REQUEST"
    CLOUD_RESOURCE = "CLOUD_RESOURCE"
    PUBLIC_ACTION = "PUBLIC_ACTION"
