"""T031 H-2 HCF round 4, R1: HD-1 - the RECOVERY recoverability probe in
``resolve_sample`` is BOUND to the owning acquisition before it runs.

The world factory returns INDEPENDENTLY CONSTRUCTED, INITIALLY UNBOUND
clients for every mode (what production composes: a fresh PikaHttpClient per
world). A local composition or binding failure of the probe - or a live read
the composition refuses (EffectDenied) - is never evidence that the work is
unrecoverable, so it refuses the resolution EVEN WITH --force-unrecoverable.
Only the evidence R7 names may reach the force path: a probe that reached the
source and found the history empty/missing/ambiguous (NeedsReconciliation),
or an INDETERMINATE source."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from test_benchmark_experiments import _OfflineFinalityWorld
from test_t031_h2b_p1_modes import _paid_settings
from test_t031_h2b_p3_ambiguity import _crash_state, _valid_fake_graph

from microdrama.contracts.errors import Conflict, EffectDenied, PolicyDenied
from microdrama.persistence import Database
from microdrama.pipeline.benchmark_service import BenchmarkService
from microdrama.pipeline.experimental_world import CanonicalExperimentWorld
from microdrama.rendering.comfy_jobs import ComfyRenderService, render_client_id
from microdrama.testing.fakes.comfy import FakeComfyClient

pytestmark = pytest.mark.db

# Attributes that are not live HTTP effects: the authorization scope is a
# context manager (PikaHttpClient refuses at request time, not scope entry),
# and bind_pod_endpoint is the binding itself.
_PASS_THROUGH = {"authorization_scope", "bind_pod_endpoint"}


class _UnboundUntilBoundFake:
    """A fresh fake client that refuses every live effect until
    ``bind_pod_endpoint`` binds it - the production ``PikaHttpClient``'s
    unbound refusal (comfy_transport.py: "the Comfy endpoint is not bound; it
    is derived from the leased Pod"), which the old probe's broad except
    swallowed as evidence of unrecoverability."""

    def __init__(self, state) -> None:
        self._inner = FakeComfyClient(state)
        self.bound_pod_endpoint: tuple[str, str | None] | None = None

    def bind_pod_endpoint(self, pod_id: str, endpoint_url: str | None) -> None:
        self.bound_pod_endpoint = (pod_id, endpoint_url)
        self._inner.bind_pod_endpoint(pod_id, endpoint_url)

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if (
            callable(attr)
            and self.bound_pod_endpoint is None
            and not name.startswith("_")
            and name not in _PASS_THROUGH
        ):

            def refused(*_args, **_kwargs):
                raise EffectDenied(
                    "the Comfy endpoint is not bound; it is derived from the leased Pod"
                )

            return refused
        return attr


class _FreshOfflineWorld(_OfflineFinalityWorld, CanonicalExperimentWorld):
    pass


def _fresh_probe_world(comfy, world, adapter, *, probe_binding: str | None = None):
    """An independently constructed world: a NEW client (initially unbound),
    a NEW render service and a NEW world adapter over the SAME durable db,
    lease manager, jobs, budget and pod-side server state.

    ``probe_binding`` shapes the probe's own bind_for_recovery for the
    bind-failure proofs: ``None`` is the honest canonical implementation;
    ``"RAISE"`` makes it raise; any other value is returned verbatim."""
    service = comfy.service
    client = _UnboundUntilBoundFake(comfy.server)
    fresh_service = ComfyRenderService(
        service._db,
        service._budget,
        client,
        service._clock,
        service._ids,
        service._settings,
        service._config,
        service._store,
    )
    fresh = _FreshOfflineWorld(
        db=world.db,
        jobs=comfy.jobs,
        leases=world.leases,
        comfy=fresh_service,
        budget=adapter.budget,
        request_factory=adapter.request_factory,
    )
    if probe_binding is None:
        return fresh

    def _bind(acquisition_id: UUID) -> str:
        if probe_binding == "RAISE":
            raise RuntimeError("the probe's lease manager is unreachable (fixture)")
        return probe_binding

    fresh.bind_for_recovery = _bind
    return fresh


def _factory(comfy, world, adapter, modes: list[str], *, probe_binding: str | None = None):
    def factory(
        *,
        experiment_id,
        budget,
        authorization=None,
        quote=None,
        mode="EXECUTE",
        acquisition_id=None,
    ):
        modes.append(mode)
        # Only the RECOVERY probe's own binding is shaped; the CLEANUP world
        # keeps the honest canonical binder (its binding must still be BOUND).
        shaped = probe_binding if mode == "RECOVERY" else None
        return _fresh_probe_world(comfy, world, adapter, probe_binding=shaped)

    return factory


def _resolve_args(slot):
    return dict(
        sample_id=slot["sample_id"],
        actor_ref="operator-console",
        reason="provider console evidence",
        evidence_sha256="7" * 64,
    )


def _acquisition_id(db: Database, experiment_id: UUID, sample_id: str) -> UUID:
    with db.transaction(readonly=True) as tx:
        return tx.fetchval(
            "SELECT acquisition_id FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (experiment_id, sample_id),
        )


def _sample_state(db: Database, experiment_id: UUID, sample_id: str):
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT state FROM benchmark_samples WHERE experiment_id=%s AND sample_id=%s",
            (experiment_id, sample_id),
        )
    assert row is not None
    return row["state"]


# ---------------------------------------------------------------------------
# (a) Recoverable work refuses force - through a fresh, initially unbound
#     RECOVERY client that only a real binding can make legible.
# ---------------------------------------------------------------------------


def test_hd1_recoverable_work_refuses_force_through_fresh_unbound_probe(
    db: Database, tmp_path: Path
):
    """HD-1: the worker's POST landed under the DETERMINISTIC client id while
    the operation stayed UNKNOWN without external_id. The probe composes a
    FRESH RECOVERY world (an initially unbound client, exactly the production
    composition); the old code swallowed the unbound client's EffectDenied as
    "unrecoverable" and force discarded positively recoverable work. Binding
    the probe first makes the accepted prompt discoverable - and positively
    recoverable work refuses resolution EVEN WITH force."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=False)
    )
    experiment_id = plan.experiment_id
    key = f"benchmark:{experiment_id}:sample:{slot['sample_id']}:a1"
    FakeComfyClient(comfy.server).queue_prompt(_valid_fake_graph(), client_id=render_client_id(key))
    comfy.clock.advance(seconds=5)
    acquisition_id = _acquisition_id(db, experiment_id, slot["sample_id"])
    assert adapter.bind_for_recovery(acquisition_id) == "BOUND"  # live pod, endpoint

    modes: list[str] = []
    svc = BenchmarkService(
        db,
        _paid_settings(),
        clock=comfy.clock,
        ids=world.ids,
        world_factory=_factory(comfy, world, adapter, modes),
    )
    with pytest.raises(Conflict, match="recoverable"):
        svc.resolve_sample(experiment_id, **_resolve_args(slot), force_unrecoverable=True)
    # The recoverability decision ran through its OWN RECOVERY composition -
    # and that probe was bound before it probed.
    assert "RECOVERY" in modes
    assert _sample_state(db, experiment_id, slot["sample_id"]) != "FAILED", (
        "positively recoverable work must never be resolved away by force"
    )


# ---------------------------------------------------------------------------
# (b) A RECOVERY probe bind failure refuses even with force.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("probe_binding", ["RAISE", "INDETERMINATE"])
def test_hd1_recovery_probe_bind_failure_refuses_force(
    db: Database, tmp_path: Path, probe_binding: str
):
    """HD-1: the probe's own binding failing - raising, or not returning
    BOUND - is a fact about the probe, never about the work. The old code
    never bound the probe at all: the unbound client's EffectDenied read as
    "unrecoverable" and force resolved the sample. Both failure shapes must
    refuse EVEN WITH force."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=False)
    )
    experiment_id = plan.experiment_id
    acquisition_id = _acquisition_id(db, experiment_id, slot["sample_id"])
    assert adapter.bind_for_recovery(acquisition_id) == "BOUND"

    svc = BenchmarkService(
        db,
        _paid_settings(),
        clock=comfy.clock,
        ids=world.ids,
        world_factory=_factory(comfy, world, adapter, [], probe_binding=probe_binding),
    )
    with pytest.raises(Conflict, match="probe"):
        svc.resolve_sample(experiment_id, **_resolve_args(slot), force_unrecoverable=True)
    assert _sample_state(db, experiment_id, slot["sample_id"]) != "FAILED"


# ---------------------------------------------------------------------------
# (c) Reachable, genuinely unrecoverable work still resolves with force.
# ---------------------------------------------------------------------------


def test_hd1_bound_unrecoverable_still_resolves_with_force(db: Database, tmp_path: Path):
    """HD-1 control: with the probe BOUND and the source answering, an
    UNKNOWN submit whose deterministic client id matches NO prompt on the
    server is genuinely reachable-but-unrecoverable history (R7's evidence:
    empty/missing history stays ambiguous). It still refuses without force
    and resolves with force - the fix never widens the refusal past R7."""
    world, ep, plan, service, comfy, adapter, slot, operation, authorization, digest, raw = (
        _crash_state(db, tmp_path, operation_state="UNKNOWN", with_prompt=False)
    )
    experiment_id = plan.experiment_id
    acquisition_id = _acquisition_id(db, experiment_id, slot["sample_id"])
    assert adapter.bind_for_recovery(acquisition_id) == "BOUND"

    svc = BenchmarkService(
        db,
        _paid_settings(),
        clock=comfy.clock,
        ids=world.ids,
        world_factory=_factory(comfy, world, adapter, []),
    )
    args = _resolve_args(slot)
    with pytest.raises(PolicyDenied, match="force-unrecoverable"):
        svc.resolve_sample(experiment_id, **args)
    resolved = svc.resolve_sample(experiment_id, **args, force_unrecoverable=True)
    assert resolved["execution_outcome"] == "FAILED"
    assert _sample_state(db, experiment_id, slot["sample_id"]) == "FAILED"
