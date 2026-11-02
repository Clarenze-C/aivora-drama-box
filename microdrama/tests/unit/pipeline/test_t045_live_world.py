"""T045 R9 (G8): live_world is wired to durable billing instead of failing closed.

Red-first: ``build_live_benchmark_world`` ended in an unconditional ``PolicyDenied``
after every fail-closed check, had no ``BillingRepository`` and reported a constant
``billing_state``. The built world must now carry the repository, compose the lease
service and janitor behind ``RunpodInvoiceFinality``, compute billing state from lease
readiness — and still perform no DNS, credential resolution or request at construction
(proved by transports that fail the test on any call).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_live_world import _attestation, _evidence, _seed_registries

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.cost import PriceQuote
from microdrama.contracts.enums import (
    ExecutionMode,
    PriceUnit,
)
from microdrama.contracts.errors import EffectDenied, PolicyDenied
from microdrama.persistence import Database
from microdrama.persistence.object_store import FilesystemObjectStore
from microdrama.pipeline.live_world import build_live_benchmark_world
from microdrama.rendering.comfy_jobs import ComfyRenderConfig
from microdrama.rendering.finality import RunpodInvoiceFinality, SyntheticUsageFinality
from microdrama.rendering.leases import PodLeaseConfig
from microdrama.testing.fakes import FakeClock, SequentialIds

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 2, 12, tzinfo=UTC)


class _FailingTransport:
    """Any call is a test failure: construction must not reach the network."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError(f"{self.name} transport was called during world composition")


def _live_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    values.update(overrides)
    return Settings(**values)


def _t0_attestation():
    """The shared fixture attestation, re-windowed around the frozen test clock."""
    return replace(
        _attestation(),
        quote_as_of=T0 - timedelta(seconds=1),
        expires_at=T0 + timedelta(minutes=10),
    )


def _live_pod_config() -> PodLeaseConfig:
    return PodLeaseConfig(
        owned_tag="microdrama-owned:mdtest",
        allowed_gpu_types=frozenset({"A40"}),
        min_host_ram_gb=32,
        container_image="registry.example/render@sha256:" + "a" * 64,
        max_hourly_price_micro_usd=600_000,
        price=PriceQuote(
            currency="USD",
            unit=PriceUnit.GPU_SECOND,
            unit_price_micro_usd=139,
            source="PROVIDER_QUOTE",
            price_table_version="operator-quote-t031",
            as_of=T0,
        ),
        provider_account_ref="acct:runpod-t031",
    )


def _live_render_config(*, lease_covered: bool = True) -> ComfyRenderConfig:
    # T045-FIX B-B1: a live world renders on a leased Runpod Pod, so its render is
    # lease-covered (the Pod invoice is the only GPU cost).
    return ComfyRenderConfig(
        price=PriceQuote(
            currency="USD",
            unit=PriceUnit.GPU_SECOND,
            unit_price_micro_usd=139,
            source="PROVIDER_QUOTE",
            price_table_version="operator-quote-t031",
            as_of=T0,
        ),
        lease_covered=lease_covered,
    )


def _build(
    db: Database,
    tmp_path: Path,
    *,
    settings: Settings | None = None,
    attestation: Any | None = None,
    evidence: Any | None = None,
    billing: Any | None = None,
    pod_config: PodLeaseConfig | None = None,
    runpod_transport: Any | None = None,
    comfy_transport: Any | None = None,
    render_config: ComfyRenderConfig | None = None,
    credential_resolver: Any | None = None,
    runpod_credential_ref: str = "credref:runpod-canary",
    comfy_credential_ref: str = "credref:comfy-canary",
) -> Any:
    attestation = attestation or _t0_attestation()
    live_settings = settings or _live_settings()
    budget = BudgetService(db, FakeClock(T0), SequentialIds("t045-live"), live_settings)
    return build_live_benchmark_world(
        live_settings,
        db,
        budget,
        FilesystemObjectStore(tmp_path / "objects"),
        attestation=attestation,
        evidence=evidence or _evidence(attestation),
        billing=billing
        if billing is not None
        else RunpodInvoiceFinality(db, budget_service=budget),
        runpod_credential_ref=runpod_credential_ref,
        comfy_credential_ref=comfy_credential_ref,
        credential_resolver=credential_resolver
        or (
            lambda _ref: (_ for _ in ()).throw(
                AssertionError("credential values must never resolve during composition")
            )
        ),
        pod_config=pod_config or _live_pod_config(),
        render_config=render_config or _live_render_config(),
        clock=FakeClock(T0),
        ids=SequentialIds("t045-live"),
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )


def test_a_fully_valid_build_returns_a_world_with_zero_transport_calls(
    db: Database, tmp_path: Path
) -> None:
    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )
    runpod_transport = _FailingTransport("runpod")
    comfy_transport = _FailingTransport("comfy")
    world = _build(
        db,
        tmp_path,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
        credential_resolver=lambda _ref: (_ for _ in ()).throw(
            AssertionError("credentials must not resolve during composition")
        ),
    )
    assert runpod_transport.calls == 0
    assert comfy_transport.calls == 0
    assert isinstance(world.billing, RunpodInvoiceFinality)
    # billing_state is computed from lease readiness (R9), not a constant: with no
    # runpod lease yet nothing has reached provider finality.
    assert world.billing_state == "PENDING_PROVIDER_FINALITY"
    assert world.billing_readiness() == []


def test_a_world_built_with_a_synthetic_finality_is_refused(db: Database, tmp_path: Path) -> None:
    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )
    offline = Settings()
    synthetic = SyntheticUsageFinality(offline, provider_id="runpod")
    with pytest.raises(PolicyDenied, match="BillingRepository"):
        _build(db, tmp_path, billing=synthetic)


def test_a_plain_repository_is_accepted_and_wrapped_in_the_invoice_finality(
    db: Database, tmp_path: Path
) -> None:
    from microdrama.budget.billing import BillingRepository

    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )
    budget = BudgetService(db, FakeClock(T0), SequentialIds("b"), _live_settings())
    plain = BillingRepository(db, budget_service=budget)
    world = _build(db, tmp_path, billing=plain)
    assert world.billing is plain
    assert isinstance(world.leases._finality, RunpodInvoiceFinality)
    assert isinstance(world.janitor._finality, RunpodInvoiceFinality)


def test_each_earlier_gate_still_denies_in_order(db: Database, tmp_path: Path) -> None:
    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )
    attestation = _t0_attestation()

    # Offline mode still refuses before touching any dependency.
    with pytest.raises(EffectDenied, match="PAID_BENCHMARK"):
        _build(db, tmp_path, settings=Settings(), attestation=attestation)
    # Missing explicit paid flag still refuses.
    with pytest.raises(EffectDenied, match="PAID_REQUEST"):
        _build(
            db,
            tmp_path,
            settings=_live_settings(paid_requests_enabled=False),
            attestation=attestation,
        )
    # Public actions still refuse: PAID_BENCHMARK may not even enable the flag.
    with pytest.raises(ValueError, match="public_actions_enabled"):
        _live_settings(public_actions_enabled=True)
    # A non-credref credential name still refuses.
    with pytest.raises(EffectDenied, match="credref"):
        _build(db, tmp_path, runpod_credential_ref="sk-secret-value")
    # A stale attestation still refuses.
    stale = replace(
        attestation,
        quote_as_of=attestation.quote_as_of - timedelta(hours=2),
        expires_at=attestation.expires_at - timedelta(hours=2),
    )
    with pytest.raises(PolicyDenied, match="stale|not current"):
        _build(db, tmp_path, attestation=stale)
    # The namespace pin still refuses a foreign owned tag.
    with pytest.raises(PolicyDenied, match="namespace"):
        _build(
            db, tmp_path, pod_config=replace(_live_pod_config(), owned_tag="microdrama-owned:other")
        )
    # The account label pin (R10) still refuses a mismatched config label.
    with pytest.raises(PolicyDenied, match="account"):
        _build(
            db,
            tmp_path,
            pod_config=replace(_live_pod_config(), provider_account_ref="acct:runpod-someone-else"),
        )
    # The image pin still refuses.
    with pytest.raises(PolicyDenied, match="image"):
        _build(
            db,
            tmp_path,
            pod_config=replace(
                _live_pod_config(),
                container_image="registry.example/other@sha256:" + "b" * 64,
            ),
        )
    # The GPU allowlist pin still refuses.
    with pytest.raises(PolicyDenied, match="GPU"):
        _build(
            db,
            tmp_path,
            pod_config=replace(_live_pod_config(), allowed_gpu_types=frozenset({"H100"})),
        )
    # An exposure cap above the episode cap still refuses.
    expensive = _t0_attestation()
    evidence = _evidence(expensive)
    over_cap = replace(
        evidence,
        maximum_exposure_micro_usd=11_000_000,
        quote=replace(evidence.quote, maximum_exposure_micro_usd=11_000_000),
    )
    with pytest.raises(PolicyDenied, match="episode budget cap|exposure"):
        _build(db, tmp_path, attestation=expensive, evidence=over_cap)


def test_billing_state_reflects_lease_readiness(db: Database, tmp_path: Path) -> None:
    """After a lease exists, billing_state is the worst per-lease readiness (R7/R9)."""
    import uuid

    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )
    season, episode = _seed_episode(db)
    # A durable runpod lease with an open compute window: readiness must report
    # PENDING_PROVIDER_FINALITY and the world's aggregate must be honest about it.
    with db.transaction() as tx:
        account, reservation, lease = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
            (account, season, episode),
        )
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, request_hash, "
            "category, queue, provider, operation_kind, price, ceilings, reserved_micro_usd, "
            "state, expires_at) VALUES (%s, %s, %s, %s, %s, 'GPU_GENERATION', 'production', "
            "'runpod', 'pod.lease', '{}', '{}', 900000, 'ACTIVE', %s)",
            (reservation, account, uuid.uuid4(), f"t045live:{lease}", "0" * 64, T0),
        )
        tx.execute(
            "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
            "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
            "hourly_price_micro_usd, lease_expires_at, create_requested_at, "
            "compute_window_start_at, provider_account_ref) VALUES (%s, 'runpod', 'pod-live-1', "
            "'microdrama-owned:mdtest', %s, %s, %s, 'RELEASED', 'TERMINATED', "
            "'NVIDIA A40', 500000, %s, %s, %s, 'acct:runpod-t031')",
            (
                lease,
                f"tok-{lease}",
                episode,
                reservation,
                T0 + timedelta(hours=1),
                T0,
                T0,
            ),
        )
    world = _build(db, tmp_path)
    states = world.billing_readiness()
    assert [s.state for s in states] == ["PENDING_PROVIDER_FINALITY"]
    assert world.billing_state == "PENDING_PROVIDER_FINALITY"


def _seed_episode(db: Database):
    from microdrama.testing.seed import seed_episode, seed_season

    with db.transaction() as tx:
        season = seed_season(tx)
        return season, seed_episode(tx, season)


def test_a_charging_render_config_is_refused_for_a_leased_runpod_pod(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-B1: a world whose Comfy endpoint is the leased Runpod Pod refuses a
    render config that would settle measured GPU-seconds - the Pod lease's BILLED
    settlement is the only GPU cost."""
    from microdrama.contracts.errors import PolicyDenied

    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )
    with pytest.raises(PolicyDenied, match="lease-covered"):
        _build(
            db,
            tmp_path,
            runpod_transport=_FailingTransport("runpod"),
            comfy_transport=_FailingTransport("comfy"),
            render_config=_live_render_config(lease_covered=False),
        )


def test_a_reservation_bound_to_one_job_cannot_be_spent_under_another(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-N6: the Comfy guard checks the reservation's job binding - a
    mismatched job id is refused before any request leaves."""
    import uuid as _uuid

    from microdrama.contracts.errors import EffectDenied
    from microdrama.testing.seed import seed_episode, seed_season

    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )
    world = _build(
        db,
        tmp_path,
        runpod_transport=_FailingTransport("runpod"),
        comfy_transport=_FailingTransport("comfy"),
    )
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        account = _uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
            (account, season, episode),
        )
        for category in (
            "RESEARCH_SCRIPT_PROMPTS_METADATA",
            "REFERENCES_DIALOGUE",
            "QA_CAPTIONS",
            "CPU_STORAGE_TRANSFER",
            "RECOVERY_HEADROOM",
            "METERED_MANAGEMENT",
        ):
            tx.execute(
                "INSERT INTO budget_category_allocations (account_id, category, "
                "allocated_micro_usd, protected) VALUES (%s, %s, 0, %s)",
                (account, category, "false" if category == "METERED_MANAGEMENT" else "true"),
            )
        tx.execute(
            "INSERT INTO budget_category_allocations (account_id, category, "
            "allocated_micro_usd, protected) VALUES (%s, 'GPU_GENERATION', 9000000, true)",
            (account,),
        )
        from microdrama.testing.seed import seed_job

        job_a = seed_job(tx, semantic_key="n6:job-a", job_type="render.shot")
        job_b = seed_job(tx, semantic_key="n6:job-b", job_type="render.shot")
        reservation = _uuid.uuid4()
        tx.execute(
            "INSERT INTO reservations (id, account_id, episode_id, request_id, semantic_key, "
            "request_hash, category, queue, provider, operation_kind, price, ceilings, "
            "job_id, reserved_micro_usd, state, expires_at) VALUES (%s, %s, %s, "
            "%s, %s, %s, 'GPU_GENERATION', 'production', 'comfyui', 'comfy.queue_prompt', "
            "'{}', '{}', %s, 1000, 'ACTIVE', %s)",
            (
                reservation,
                account,
                episode,
                _uuid.uuid4(),
                f"n6:{reservation}",
                "0" * 64,
                job_a,
                T0 + timedelta(hours=1),
            ),
        )
    world.comfy_client.bind_pod_endpoint("pod-n6", "https://pod-n6-8188.proxy.runpod.net")
    with pytest.raises(EffectDenied, match="differs from the reservation's job"):
        with world.comfy_client.authorization_scope(
            reservation_id=reservation, episode_id=episode, job_id=job_b, operation_id=None
        ):
            world.comfy_client.object_info()
