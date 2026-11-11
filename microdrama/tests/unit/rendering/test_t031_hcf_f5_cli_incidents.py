"""T031 H-2 HCF round, F5: HC-11 (the CLI resume never lets a generation-
argument problem - e.g. a non-ASCII ``--authorization-sha256`` whose
``hmac.compare_digest`` raises ``TypeError`` - crash or refuse BEFORE the
durable recovery has run; unusable arguments become admission blockers on the
recovered status) and HC-12 (the §6.4 contradiction incident - attestation,
actor, evidence, contradicted pod and the reopened liability's current
finality - is a durable record in ``status()``/``export()`` that survives
finalization, where the transient U5 description disappears)."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest
from test_benchmark_experiments import _composed_world
from test_t031_h2b_p1_modes import _authorization_pair, _offline_settings
from test_t031_h2b_p2_gate import _item_kinds
from test_t031_h2b_p4_resolution import _service
from test_t031_hcf_f3_finality import _bill_lease_to_billed, _contradicted_discovery

from microdrama.persistence import Database
from microdrama.pipeline.benchmark import main
from microdrama.pipeline.benchmark_service import BenchmarkService

pytestmark = pytest.mark.db


def test_hc11_non_ascii_sha_resume_recovers_first(db: Database, tmp_path: Path) -> None:
    """HC-11: a resume with a pending UNKNOWN recovery and a poisoned
    ``--authorization-sha256`` (non-ASCII - ``hmac.compare_digest`` raises
    ``TypeError`` on it, which the CLI's outer handler does not catch) must
    still complete the durable recovery: exit 0, the accepted prompt adopted
    and completed through reconciliation, the poisoned argument reported as an
    admission blocker on the recovered status, zero new sends."""
    from rendering_support import RenderWorld
    from test_t031_h2b_p1_modes import _enter_submit_ambiguity

    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    _enter_submit_ambiguity(db, world, comfy, adapter, plan, tmp_path)
    submissions_before = len(comfy.server.submissions)
    with db.transaction(readonly=True) as tx:
        sample_id = tx.fetchval(
            "SELECT s.sample_id FROM benchmark_dispatch_slots d "
            "JOIN benchmark_samples s ON s.experiment_id=d.experiment_id "
            "AND s.sample_id=d.sample_id WHERE d.experiment_id=%s",
            (plan.experiment_id,),
        )
    _, authorization, digest, raw = _authorization_pair(world, plan, tmp_path)
    auth_path = tmp_path / "hc11-authorization.json"
    auth_path.write_bytes(raw)

    settings = _offline_settings(tmp_path / "hc11-store", db)

    def offline_service_factory(db, settings, store, injection):
        return BenchmarkService(
            db,
            settings,
            store=store,
            clock=comfy.clock,
            ids=world.ids,
            world_factory=lambda **_kwargs: adapter,
        )

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(
            [
                "resume",
                "--experiment-id",
                str(plan.experiment_id),
                "--authorization",
                str(auth_path),
                "--authorization-sha256",
                "₿" * 64,
            ],
            _injection={
                "db": db,
                "settings": settings,
                "service_factory": offline_service_factory,
            },
        )
    assert code == 0
    payload = json.loads(buffer.getvalue())
    # The poisoned argument is an admission blocker on the RECOVERED status.
    assert payload["admission"]["permitted"] is False
    assert any(
        "64-character hex ASCII" in blocker for blocker in payload["admission"]["blockers"]
    ), payload["admission"]["blockers"]
    # The durable recovery completed anyway: the accepted prompt was adopted
    # by its deterministic client id and the sample completed.
    states = {s["sample_id"]: s["state"] for s in payload["samples"]}
    assert states[sample_id] == "SUCCEEDED"
    assert len(comfy.server.submissions) == submissions_before  # zero new sends


def test_hc12_incident_record_survives_finalization(db: Database, tmp_path: Path) -> None:
    """HC-12: the contradicted no-create attestation is a DURABLE incident
    record - attestation, actor, evidence, contradicted pod and the reopened
    liability's current finality - in status() and export(). It is reported
    while the liability is open (finality False, U5 still blocking) and it
    REMAINS after the invoice tail and the finalizing sweep clear U5."""
    fixed = _contradicted_discovery(db, tmp_path)
    plan = fixed["plan"]
    comfy = fixed["comfy"]
    service = _service(fixed)

    first = service.status(plan.experiment_id)
    assert [i["kind"] for i in first["incidents"]] == ["CONTRADICTED_NO_CREATE_ATTESTATION"]
    incident = first["incidents"][0]
    assert incident["attestation"] == "NO_CREATE_PROVEN"
    assert incident["actor_ref"] == "operator-console"
    assert incident["evidence_sha256"] == "a" * 64
    assert incident["pod_id"] == "late-f3-pod"
    assert incident["contradicted_at"] is not None
    assert incident["reopened_liability_final"] is False
    assert "U5" in _item_kinds(db, plan.experiment_id, comfy.clock)

    # The canonical invoice tail completes and the sweep finalizes: U5
    # disappears, but the incident record stays - now reporting finality.
    _bill_lease_to_billed(db, fixed["world"], lease_id=fixed["lease_id"], amount_micro_usd=900_250)
    service.sweep(plan.experiment_id)
    assert "U5" not in _item_kinds(db, plan.experiment_id, comfy.clock)

    final = service.status(plan.experiment_id)
    assert [i["kind"] for i in final["incidents"]] == ["CONTRADICTED_NO_CREATE_ATTESTATION"]
    kept = final["incidents"][0]
    assert kept["actor_ref"] == "operator-console"
    assert kept["evidence_sha256"] == "a" * 64
    assert kept["pod_id"] == "late-f3-pod"
    assert kept["reopened_liability_final"] is True

    exported = service.export(plan.experiment_id)
    assert exported["incidents"] == final["incidents"]


def test_hc12_uncontradicted_resolution_has_no_incident(db: Database, tmp_path: Path) -> None:
    """HC-12: an UNcontradicted no-create resolution (no pod ever appeared)
    is uninterrupted protection - no incident record is invented for it."""
    from test_t031_h2b_p4_resolution import _at6_context

    fixed = _at6_context(db, tmp_path)
    plan = fixed["plan"]
    service = _service(fixed)
    service.resolve_create(
        plan.experiment_id,
        acquisition_id=fixed["acquisition_id"],
        actor_ref="operator-console",
        reason="provider console shows no pod for the owned token",
        evidence_sha256="b" * 64,
    )
    status = service.status(plan.experiment_id)
    assert status["incidents"] == []
    assert service.export(plan.experiment_id)["incidents"] == []
