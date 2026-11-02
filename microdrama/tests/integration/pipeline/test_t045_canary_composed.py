"""T045 composed acceptance (R11): the whole canary through ``canary execute``.

Real PostgreSQL, real registries and budget service; fixture Runpod/ComfyUI
transports only (no network — the offline guard blocks anything else). The full
run: reserve -> owned-name Pod create -> /object_info gate -> bounded prompt ->
output copy + checksum -> stop -> terminate -> verified read-back -> janitor
ingest; then ``canary invoice`` matches the period and the BILLED settlement
releases the exact remainder. Replays add no money; a mismatch keeps the hold and
gives DISPUTED; the deadline path terminates; a node-schema mismatch submits
nothing; a create timeout that actually created the Pod reconciles to the same
Pod; a worker crash mid-run leaves the janitor to stop and terminate.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.persistence import Database
from microdrama.pipeline.canary import (
    compose_canary_world,
    run_execute,
    run_invoice,
)
from microdrama.pipeline.canary_authorization import CANARY_EPISODE_ID, prompt_pin
from microdrama.rendering.leases import PodLeaseClaimRequest
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.fakes.comfy import FAKE_NODE_CLASSES, VIDEO_OUTPUT_MS
from microdrama.testing.media import render_clip_bytes
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "unit" / "pipeline"))
from test_live_world import _seed_registries  # noqa: E402

T0 = datetime(2026, 11, 2, 12, tzinfo=UTC)
NS = "canary1"
TAG = f"microdrama-owned:{NS}"
ACCOUNT = "acct:runpod-canary"
POD = "pod-canary-1"
#: T045-FIX B-B2: the authorization pins the FULL image reference; create sends it as-is.
IMAGE_REF = "registry.example/microdrama/drama-canary@sha256:" + "a" * 64
#: The Comfy base URL late-bound from the created Pod (B-B2).
POD_COMFY_ENDPOINT = f"https://{POD}-8188.proxy.runpod.net"
QUOTE_PER_HOUR = 504_000
GPU_BUCKET = 50_000
CPU_BUCKET = 10_000
DISK_BUCKET = 10_000
#: Real probeable media (the output path verifies and checksums complete media).
OUTPUT_BYTES = render_clip_bytes(VIDEO_OUTPUT_MS)
WINDOW_END = T0 + timedelta(hours=1)


# --- fixture transports ---------------------------------------------------------------


@dataclass
class _Response:
    status: int
    body: bytes


class RunpodCanaryTransport:
    """A scripted Runpod v2 surface: create/read/stop/terminate/billing."""

    def __init__(
        self,
        *,
        create_timeout_once: bool = False,
        image: str | None = None,
        no_comfy_port: bool = False,
        failing_delete: bool = False,
    ) -> None:
        self.state = "RUNNING" if not create_timeout_once else "ABSENT"
        self.create_calls = 0
        self.create_timeout_once = create_timeout_once
        self.out_of_band_created = create_timeout_once
        self.image = image or IMAGE_REF
        self.no_comfy_port = no_comfy_port
        self.failing_delete = failing_delete
        #: T045-FIX B-B2: the image reference the create REQUEST actually carried.
        self.created_image: str | None = None
        self.calls: list[tuple[str, str]] = []

    def _pod_json(self, name: str) -> dict[str, Any]:
        ports = [] if self.no_comfy_port else [{"private": 8188, "public": 8188, "type": "http"}]
        return {
            "id": POD,
            "name": name,
            "image": self.image,
            "status": self.state,
            "cost": f"{QUOTE_PER_HOUR / 1_000_000:.6f}",
            "createdAt": T0.isoformat().replace("+00:00", "Z"),
            "gpu": {"id": "A40", "count": 1, "memory": 48},
            "runtime": {"ports": ports},
        }

    def request(
        self, method: str, url: str, *, headers: Any, body: bytes | None = None
    ) -> _Response:
        from microdrama.rendering.runpod_transport import pod_name

        self.calls.append((method, url))
        if method == "POST" and url.endswith("/v2/pods"):
            self.create_calls += 1
            self.created_image = json.loads(body or b"{}").get("image")
            # The fixture Pod reports exactly the image the create request carried.
            self.image = self.created_image or self.image
            if self.create_timeout_once:
                self.create_timeout_once = False
                # The create "timed out" but actually created the Pod out of band.
                self.state = "RUNNING"
                self.last_name = json.loads(body or b"{}")["name"]
                return _Response(503, b"")
            self.last_name = json.loads(body or b"{}")["name"]
            self.state = "RUNNING"
            return _Response(200, json.dumps(self._pod_json(self.last_name)).encode())
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods?"):
            pods = []
            if self.out_of_band_created and self.state in ("RUNNING", "EXITED"):
                name = getattr(self, "last_name", "") or pod_name(NS, "seed")
                pods.append(self._pod_json(name))
            return _Response(200, json.dumps({"pods": pods, "pagination": {}}).encode())
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods/"):
            if self.state in ("ABSENT", "GONE"):
                return _Response(404, b"")
            return _Response(
                200, json.dumps(self._pod_json(getattr(self, "last_name", "x"))).encode()
            )
        if method == "POST" and url.endswith("/action"):
            assert body is not None and json.loads(body)["action"] == "stop"
            self.state = "EXITED"
            return _Response(200, b"{}")
        if method == "DELETE":
            if self.failing_delete:
                return _Response(503, b"")
            self.state = "GONE"
            return _Response(200, b"{}")
        if "/billing/pods" in url:
            return _Response(200, self._billing_json())
        raise AssertionError(f"unexpected fixture Runpod call: {method} {url}")

    def _billing_json(self) -> bytes:
        total = GPU_BUCKET + CPU_BUCKET + DISK_BUCKET
        return json.dumps(
            {
                "records": [
                    {
                        "podId": POD,
                        "startTime": T0.isoformat().replace("+00:00", "Z"),
                        "endTime": WINDOW_END.isoformat().replace("+00:00", "Z"),
                        "totalAmount": f"{total / 1_000_000:.6f}",
                        "gpuAmount": f"{GPU_BUCKET / 1_000_000:.6f}",
                        "cpuAmount": f"{CPU_BUCKET / 1_000_000:.6f}",
                        "diskAmount": f"{DISK_BUCKET / 1_000_000:.6f}",
                    }
                ],
                "metadata": {
                    "query": {
                        "startTime": T0.isoformat().replace("+00:00", "Z"),
                        "endTime": WINDOW_END.isoformat().replace("+00:00", "Z"),
                    }
                },
            }
        ).encode()


class ComfyCanaryTransport:
    """A scripted ComfyUI surface: object_info/prompt/history/queue/view."""

    def __init__(
        self,
        *,
        drop_node: str | None = None,
        never_completes: bool = False,
        malformed_history: bool = False,
    ) -> None:
        self.drop_node = drop_node
        self.never_completes = never_completes
        self.malformed_history = malformed_history
        self.calls: list[tuple[str, str]] = []
        self.prompt_id = "canary-prompt-1"

    def _object_info(self) -> dict[str, Any]:
        catalog: dict[str, Any] = {}
        for name, info in FAKE_NODE_CLASSES.items():
            if self.drop_node is not None and name == self.drop_node:
                continue
            catalog[name] = {
                "input": {
                    "required": {key: {} for key in info.required_inputs},
                    "optional": {key: {} for key in info.optional_inputs},
                },
                "output": list(info.output_types),
            }
        return catalog

    def request(self, method: str, url: str, *, headers: Any, body: bytes | None = None) -> bytes:
        self.calls.append((method, url))
        if method == "GET" and url.endswith("/object_info"):
            return json.dumps(self._object_info()).encode()
        if method == "POST" and url.endswith("/prompt"):
            return json.dumps({"prompt_id": self.prompt_id, "number": 1}).encode()
        if method == "GET" and "/history/" in url:
            if self.malformed_history:
                return b"{not json"
            if self.never_completes:
                return b"{}"
            return json.dumps(
                {
                    self.prompt_id: {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "9": {
                                "video": [
                                    {
                                        "filename": "canary_out.mp4",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                }
            ).encode()
        if method == "GET" and url.endswith("/queue"):
            return json.dumps(
                {"queue_running": [[0, self.prompt_id]], "queue_pending": []}
            ).encode()
        if method == "GET" and "/view" in url:
            return OUTPUT_BYTES
        raise AssertionError(f"unexpected fixture ComfyUI call: {method} {url}")


# --- shared helpers -------------------------------------------------------------------


def _live_settings() -> Settings:
    return Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )


def _prompt() -> dict[str, Any]:
    return {
        "text": "FIXTURE PROMPT canary: one wide night-market shot, static camera.",
        "seed": 20261102,
        "negative": "",
    }


def _authorization_document(**overrides: Any) -> dict[str, Any]:
    from test_t045_canary_runner import _real_pins

    document: dict[str, Any] = {
        "operator": "operator@example.invalid",
        "change_ref": "change-composed-1",
        "episode_id": CANARY_EPISODE_ID,
        "hard_stop_utc": (T0 + timedelta(hours=2)).isoformat(),
        "max_wall_seconds": 600,
        "quote": {
            "quote_id": "quote-canary-composed",
            "currency": "USD",
            "captured_at": (T0 - timedelta(minutes=5)).isoformat(),
            "expires_at": (T0 + timedelta(hours=4)).isoformat(),
            "compute_micro_usd_per_hour": QUOTE_PER_HOUR,
            "container_disk_gb": 20,
            "container_storage_micro_usd_per_gb_month": 100_000,
            "persistent_volume_gb": 5,
            "persistent_storage_micro_usd_per_gb_month": 200_000,
            "max_storage_exposure_micro_usd": 1_200_000,
            "allowed_gpu_types": ["A40"],
            "host_ram_gb_by_gpu": {"A40": 64},
            "maximum_runtime_ms": 600_000,
            "maximum_exposure_micro_usd": 2_000_000,
        },
        "caps": {
            "max_spend_micro_usd": 2_000_000,
            "max_storage_gb": 5,
            "max_prompts": 1,
            "max_attempts": 2,
        },
        "rights": {
            "rights_route_id": "route-video-fake",
            "rights_subject_ref": "model-output:qualified",
            "rights_subject_kind": "MODEL_OUTPUT",
            "rights_version": 1,
            "territories": ["TH"],
            "rights_evidence_id": "rights-evidence-canary",
            "eligible_until": (T0 + timedelta(hours=2)).isoformat(),
        },
        "pins": _real_pins(),
        "runpod_credential_ref": "credref:runpod-canary",
        "comfy_credential_ref": "credref:comfy-canary",
        "namespace": NS,
        "provider_account_ref": ACCOUNT,
        "prompt_sha256": [prompt_pin(_prompt())],
        "reference_sha256": [],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(document.get(key), dict):
            document[key] = {**document[key], **value}
        else:
            document[key] = value
    return document


def _seed_everything(db: Database) -> None:
    from microdrama.pipeline.canary_authorization import CANARY_EPISODE_ID

    _seed_registries(
        db, _live_settings(), recorded_at=T0 - timedelta(minutes=1), live_evidence=True
    )
    with db.transaction() as tx:
        season = seed_season(tx)
        seeded = seed_episode(tx, season)
        # T045-FIX B-S9: the deterministic episode the authorization pins.
        episode = uuid.UUID(CANARY_EPISODE_ID)
        tx.execute("UPDATE episodes SET id=%s WHERE id=%s", (episode, seeded))
        account = uuid.uuid4()
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
            "INSERT INTO budget_category_allocations (account_id, category, allocated_micro_usd, "
            "protected) VALUES (%s, 'GPU_GENERATION', 9000000, true)",
            (account,),
        )


def _write_authorization(tmp_path: Path, **overrides: Any) -> Path:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_authorization_document(**overrides), indent=2))
    return path


def _write_prompts(tmp_path: Path) -> Path:
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps([_prompt()]))
    return path


def _execute(
    db: Database,
    tmp_path: Path,
    *,
    clock: FakeClock,
    runpod_transport: RunpodCanaryTransport,
    comfy_transport: ComfyCanaryTransport,
    **overrides: Any,
):
    from microdrama.persistence.object_store import FilesystemObjectStore

    path = _write_authorization(tmp_path, **overrides)
    from microdrama.pipeline.canary_authorization import load_canary_authorization

    _, digest = load_canary_authorization(path)
    return run_execute(
        path,
        expected_sha256=digest,
        settings=_live_settings(),
        db=db,
        store=FilesystemObjectStore(tmp_path / "objects"),
        prompts_path=_write_prompts(tmp_path),
        clock=clock,
        ids=SequentialIds("composed"),
        credential_resolver=lambda _ref: "fixture-dummy-value",
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
        evidence_dir=tmp_path / "records",
        sleep=lambda seconds: clock.advance(ms=int(seconds * 1000)),
    )


def _reservation_of_lease(db: Database) -> dict[str, Any]:
    with db.transaction(readonly=True) as tx:
        return tx.fetchone(
            "SELECT r.* FROM reservations r JOIN pod_leases l ON l.reservation_id = r.id "
            "WHERE l.provider = 'runpod' AND l.provider_account_ref = %s",
            (ACCOUNT,),
        )


def _account_counters(db: Database) -> dict[str, int]:
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT * FROM budget_accounts a JOIN pod_leases l "
            "ON a.episode_id = l.owner_episode_id WHERE l.provider = 'runpod' LIMIT 1"
        )
    assert row is not None
    return {
        "reserved": row["reserved_outstanding_micro_usd"],
        "accrued": row["accrued_micro_usd"],
        "settled": row["settled_micro_usd"],
    }


def _charge_total(db: Database) -> int:
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall("SELECT amount_micro_usd FROM charges")
    return sum(row["amount_micro_usd"] for row in rows)


def _prompt_reservation(db: Database) -> dict[str, Any]:
    """The comfy.queue_prompt hold (T045-FIX B-B1: it must settle at zero charge)."""
    with db.transaction(readonly=True) as tx:
        return tx.fetchone("SELECT * FROM reservations WHERE operation_kind='comfy.queue_prompt'")


def _provider_reported_total(db: Database) -> int:
    """The provider-reported charges (ACCRUAL/ADJUSTMENT): what the provider billed.

    The lease SETTLEMENT finalizes the accrual it covers - the account counters net
    the two rows - so this is the charge-table sum comparable to the invoice.
    """
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT amount_micro_usd FROM charges WHERE kind IN ('ACCRUAL','ADJUSTMENT')"
        )
    return sum(row["amount_micro_usd"] for row in rows)


# --- the composed canary --------------------------------------------------------------


def test_full_canary_bills_and_releases_the_exact_remainder(db: Database, tmp_path: Path) -> None:
    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport()
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    record = result.record
    assert record["pod_id"] == POD
    # T045-FIX B-B2: the create request carried the full pinned image reference as-is.
    assert runpod_transport.created_image == IMAGE_REF
    assert record["prompt_ids"] == [comfy_transport.prompt_id]
    assert record["output_objects"] and record["output_objects"][0]["sha256"]
    assert record["terminate_verified_at"] is not None
    assert record["node_schema_mismatch"] is False
    # Billing readiness is honest: pending until the invoice is verified.
    assert record["billing_state"] == "PENDING_PROVIDER_FINALITY"
    assert record["billing_readiness"][0]["state"] in (
        "PENDING_PROVIDER_FINALITY",
        "AWAITING_INVOICE",
    )
    hold = _reservation_of_lease(db)
    assert hold["state"] == "ACTIVE"  # the pending hold is kept

    # The janitor ingests the terminated (absent) Pod's billing after the backoff.
    clock.advance(seconds=2 * 3600 + 1800)
    world = _world_for_sweep(db, tmp_path, clock, runpod_transport, comfy_transport, seq="sweep-1")
    first_sweep = world.janitor.sweep()
    assert first_sweep.failures == []
    assert any(a.outcome == "INGESTED" for a in first_sweep.billing_ingests)
    readiness = world.billing_readiness()
    assert readiness[0].state == "AWAITING_INVOICE"

    # canary invoice: the operator's period evidence matches the stored buckets.
    evidence = tmp_path / "invoice-fixture.pdf"
    evidence.write_bytes(b"fixture operator invoice")
    summary = run_invoice(
        settings=_live_settings(),
        db=db,
        provider_account_ref=ACCOUNT,
        pod_id=POD,
        period_start=T0,
        period_end=WINDOW_END,
        amount_micro_usd=GPU_BUCKET + CPU_BUCKET + DISK_BUCKET,
        evidence_path=evidence,
        source="INVOICE",
        observed_at=T0 + timedelta(hours=3),
    )
    assert "invoice MATCHED" in summary

    # The next sweep reaches BILLED and the settlement releases the exact remainder.
    clock.advance(seconds=600)
    settled_world = _world_for_sweep(
        db, tmp_path, clock, runpod_transport, comfy_transport, seq="sweep-2"
    )
    settled_world.janitor.sweep()
    reservation = _reservation_of_lease(db)
    assert reservation["state"] == "SETTLED"
    assert reservation["settled_micro_usd"] == GPU_BUCKET
    assert reservation["reserved_micro_usd"] == 92_400  # 140 micro-USD/s * (600s + 60s margin)
    # exactly the GPU bucket settled; the 42_400 remainder was released
    # T045-FIX B-B1: the Pod lease's BILLED settlement is the ONLY GPU cost. The
    # account total and the sum of all charges equal the invoice total exactly -
    # the Comfy prompt hold settled at zero charge, on top of the run and the replay.
    invoice_total = GPU_BUCKET + CPU_BUCKET + DISK_BUCKET
    assert _account_counters(db)["settled"] == invoice_total
    counters = _account_counters(db)
    assert counters["accrued"] == 0  # nothing is left pending on the books
    assert _provider_reported_total(db) == invoice_total
    prompt_hold = _prompt_reservation(db)
    assert prompt_hold is not None
    assert prompt_hold["state"] == "SETTLED"
    assert prompt_hold["settled_micro_usd"] == 0

    # Replaying every step adds no money.
    settled_before = reservation["settled_micro_usd"]
    charges_before = _charge_total(db)
    replay = run_invoice(
        settings=_live_settings(),
        db=db,
        provider_account_ref=ACCOUNT,
        pod_id=POD,
        period_start=T0,
        period_end=WINDOW_END,
        amount_micro_usd=GPU_BUCKET + CPU_BUCKET + DISK_BUCKET,
        evidence_path=evidence,
        source="INVOICE",
        observed_at=T0 + timedelta(hours=4),
    )
    assert "replayed" in replay
    clock.advance(seconds=600)
    _world_for_sweep(
        db, tmp_path, clock, runpod_transport, comfy_transport, seq="sweep-3"
    ).janitor.sweep()
    replayed = _reservation_of_lease(db)
    assert replayed["settled_micro_usd"] == settled_before
    assert _charge_total(db) == charges_before
    assert _account_counters(db)["settled"] == invoice_total
    assert _provider_reported_total(db) == invoice_total
    assert _prompt_reservation(db)["settled_micro_usd"] == 0


def _world_for_sweep(
    db: Database,
    tmp_path: Path,
    clock: FakeClock,
    runpod_transport: RunpodCanaryTransport,
    comfy_transport: ComfyCanaryTransport,
    *,
    seq: str,
) -> _SweepWorld:
    """A janitor-only composition over the same durable state and fixture transport.

    The janitor is independently invokable in production (its own module main) and
    does not re-run the attested live_world gates; this mirrors that composition.
    """
    from microdrama.budget import BudgetService
    from microdrama.pipeline.canary import canary_attestation, canary_pod_config
    from microdrama.pipeline.canary_authorization import load_canary_authorization
    from microdrama.rendering import RunpodInvoiceFinality, build_janitor
    from microdrama.rendering.runpod_billing import durable_pod_ownership_probe
    from microdrama.rendering.runpod_transport import RunpodRestProvider

    authorization, _ = load_canary_authorization(_write_authorization(tmp_path))
    settings = _live_settings()
    provider = RunpodRestProvider(
        settings,
        credential_ref="credref:runpod-canary",
        credential_resolver=lambda _ref: "fixture-dummy-value",
        attestation=canary_attestation(authorization),
        now=clock.now,
        reservation_guard=lambda _request, _attestation: None,
        cleanup_guard=lambda _operation, _pod_id: None,
        absent_pod_ownership_probe=durable_pod_ownership_probe(
            db, owned_tag=TAG, provider_account_ref=ACCOUNT
        ),
        transport=runpod_transport,
    )
    budget = BudgetService(db, clock, SequentialIds(seq), settings)
    janitor = build_janitor(
        db,
        budget,
        provider,
        clock,
        SequentialIds(seq),
        settings,
        canary_pod_config(authorization),
        RunpodInvoiceFinality(db, budget_service=budget),
    )
    return _SweepWorld(janitor=janitor, db=db)


def _full_world(
    db: Database,
    tmp_path: Path,
    clock: FakeClock,
    runpod_transport: RunpodCanaryTransport,
    comfy_transport: ComfyCanaryTransport,
    *,
    seq: str,
):
    """The full composed canary world at the current (un-expired) clock."""
    from microdrama.budget import BudgetService
    from microdrama.persistence.object_store import FilesystemObjectStore
    from microdrama.pipeline.canary_authorization import load_canary_authorization

    authorization, _ = load_canary_authorization(_write_authorization(tmp_path))
    settings = _live_settings()
    return compose_canary_world(
        authorization,
        settings=settings,
        db=db,
        budget=BudgetService(db, clock, SequentialIds(seq), settings),
        store=FilesystemObjectStore(tmp_path / "objects"),
        clock=clock,
        ids=SequentialIds(seq),
        credential_resolver=lambda _ref: "fixture-dummy-value",
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )


@dataclass
class _SweepWorld:
    janitor: Any
    db: Database

    def billing_readiness(self) -> list[Any]:
        from microdrama.budget.billing import lease_billing_readiness

        with self.db.transaction(readonly=True) as tx:
            rows = tx.fetchall(
                "SELECT id FROM pod_leases WHERE provider='runpod' ORDER BY created_at"
            )
        return [lease_billing_readiness(self.db, row["id"]) for row in rows]


def test_a_mismatched_invoice_keeps_the_hold_and_disputes(db: Database, tmp_path: Path) -> None:
    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport()
    _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    clock.advance(seconds=2 * 3600 + 1800)
    world = _world_for_sweep(
        db, tmp_path, clock, runpod_transport, comfy_transport, seq="mismatch-1"
    )
    world.janitor.sweep()
    evidence = tmp_path / "invoice-wrong.pdf"
    evidence.write_bytes(b"fixture wrong invoice")
    run_invoice(
        settings=_live_settings(),
        db=db,
        provider_account_ref=ACCOUNT,
        pod_id=POD,
        period_start=T0,
        period_end=WINDOW_END,
        amount_micro_usd=GPU_BUCKET + CPU_BUCKET + DISK_BUCKET - 1,  # off by one
        evidence_path=evidence,
        source="INVOICE",
        observed_at=T0 + timedelta(hours=3),
    )
    readiness = world.billing_readiness()
    assert readiness[0].state == "DISPUTED"
    assert _reservation_of_lease(db)["state"] in ("ACTIVE", "EXPIRED")  # the hold is kept


def test_a_hard_stop_deadline_stops_and_terminates(db: Database, tmp_path: Path) -> None:
    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport(never_completes=True)
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
        max_wall_seconds=2,
    )
    record = result.record
    assert record["deadline_hit"] is True
    assert record["output_objects"] == []
    assert record["terminate_verified_at"] is not None
    assert runpod_transport.state == "GONE"  # stopped AND terminated at the provider


def test_an_object_info_mismatch_submits_nothing(db: Database, tmp_path: Path) -> None:
    from microdrama.rendering.workflows import MOCK_VIDEO_TEMPLATE

    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    dropped = sorted(MOCK_VIDEO_TEMPLATE.node_classes)[0]
    comfy_transport = ComfyCanaryTransport(drop_node=dropped)
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    record = result.record
    assert record["node_schema_mismatch"] is True
    assert record["prompt_ids"] == []
    assert record["output_objects"] == []
    assert not any(
        method == "POST" and url.endswith("/prompt") for method, url in comfy_transport.calls
    )
    # The Pod was still stopped and terminated.
    assert record["terminate_verified_at"] is not None
    assert runpod_transport.state == "GONE"


def test_a_create_timeout_that_created_the_pod_reconciles_to_the_same_pod(
    db: Database, tmp_path: Path
) -> None:
    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport(create_timeout_once=True)
    comfy_transport = ComfyCanaryTransport()
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    assert result.record["pod_id"] == POD
    assert runpod_transport.create_calls == 1  # no duplicate create was sent
    with db.transaction(readonly=True) as tx:
        leases = tx.fetchall("SELECT pod_id FROM pod_leases WHERE provider='runpod'")
    assert [row["pod_id"] for row in leases] == [POD]


def test_a_worker_crash_mid_run_leaves_the_janitor_to_stop_and_terminate(
    db: Database, tmp_path: Path
) -> None:
    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport()
    # The worker claims the lease and creates the Pod, then dies (no shutdown).
    world = _full_world(db, tmp_path, clock, runpod_transport, comfy_transport, seq="crash-1")
    handle = world.leases.claim(
        PodLeaseClaimRequest(
            episode_id=_canary_episode(db),
            semantic_key="canary:change-composed-1",
            gpu_type="A40",
            host_ram_gb=64,
        )
    )
    world.leases.ensure_pod(handle.lease.lease_id)
    assert runpod_transport.state == "RUNNING"

    clock.advance(seconds=3600)  # the heartbeat/lease expires; the janitor takes over
    sweep = _world_for_sweep(db, tmp_path, clock, runpod_transport, comfy_transport, seq="crash-2")
    report = sweep.janitor.sweep()
    assert report.failures == []
    assert runpod_transport.state == "GONE"  # stopped and terminated
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT lease_state, terminate_verified_at, reservation_id FROM pod_leases "
            "WHERE provider='runpod'"
        )
    assert row["terminate_verified_at"] is not None
    with db.transaction(readonly=True) as tx:
        reservation = tx.fetchone(
            "SELECT state FROM reservations WHERE id = %s", (row["reservation_id"],)
        )
    assert reservation["state"] == "ACTIVE"  # the hold is kept for billing finality


def _canary_episode(db: Database) -> uuid.UUID:
    with db.transaction(readonly=True) as tx:
        return tx.fetchval(
            "SELECT e.id FROM episodes e JOIN budget_accounts a "
            "ON a.episode_id = e.id AND a.scope_kind='EPISODE' ORDER BY e.created_at LIMIT 1"
        )


def test_a_pod_whose_comfy_endpoint_is_not_its_own_refuses_before_object_info(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-B2: the Comfy base URL is late-bound from the created Pod and must
    equal https://<pod_id>-8188.proxy.runpod.net. A Pod that exposes no 8188 port
    (endpoint_url None) refuses before any ComfyUI call - the bearer token never
    leaves for an unvalidated host."""
    import json as _json

    from microdrama.pipeline.canary import CanaryRunNotClean

    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport(no_comfy_port=True)
    comfy_transport = ComfyCanaryTransport()
    # A Pod that exposes no 8188 port (endpoint_url None) refuses either at the pod
    # verification or at the endpoint binding - both before any ComfyUI call. The run
    # had already sent effects, so it ends NOT CLEAN with a record (T045-FIX B-S3).
    with pytest.raises(CanaryRunNotClean, match="endpoint"):
        _execute(
            db,
            tmp_path,
            clock=clock,
            runpod_transport=runpod_transport,
            comfy_transport=comfy_transport,
        )
    assert comfy_transport.calls == []  # nothing reached ComfyUI
    assert not any("/object_info" in url for _method, url in comfy_transport.calls)
    records = sorted((tmp_path / "records").glob("*-canary.json"))
    assert records, "a run that sent effects must leave its record"
    record = _json.loads(records[-1].read_text())
    assert record["outcome"] == "NOT_CLEAN"
    assert record["not_clean_reason"]
    assert record["reservation_ids"]  # the claim's hold is in the record


def test_the_comfy_calls_go_to_the_pods_own_proxy_url(db: Database, tmp_path: Path) -> None:
    """T045-FIX B-B2: every ComfyUI request URL is the leased Pod's own proxy URL -
    no CLI flag or config can point the client anywhere else."""
    from microdrama.testing.media import render_clip_bytes  # noqa: F401 - re-exported

    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport()
    _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    assert comfy_transport.calls, "the fixture transport saw no ComfyUI traffic"
    for _method, url in comfy_transport.calls:
        assert url.startswith(POD_COMFY_ENDPOINT), url


def test_a_wall_clock_longer_than_the_quoted_runtime_is_refused_at_load(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-S2: max_wall_seconds*1000 must be <= quote.maximum_runtime_ms."""
    from microdrama.contracts.errors import SchemaInvalid
    from microdrama.pipeline.canary_authorization import load_canary_authorization

    path = _write_authorization(tmp_path, max_wall_seconds=1800)  # quote allows 600_000 ms
    with pytest.raises(SchemaInvalid, match="maximum_runtime_ms"):
        load_canary_authorization(path)


def test_holds_above_the_spend_cap_refuse_before_any_reservation_or_transport(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-S2: lease hold + prompt holds + storage ceiling + shutdown margin
    must fit caps.max_spend_micro_usd; the refusal happens with zero transport calls."""
    from microdrama.contracts.errors import PolicyDenied

    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport()
    # 84_000 lease + 84_000 prompt + 1_200_000 storage + 8_400 shutdown = 1_376_400
    # against a 1_000_000 cap (still <= the quote's 2_000_000 exposure).
    with pytest.raises(PolicyDenied, match="spend cap"):
        _execute(
            db,
            tmp_path,
            clock=clock,
            runpod_transport=runpod_transport,
            comfy_transport=comfy_transport,
            caps={"max_spend_micro_usd": 1_000_000},
        )
    assert runpod_transport.calls == []
    assert comfy_transport.calls == []
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM reservations") == 0


def test_the_rights_eligible_until_bounds_the_deadline(db: Database, tmp_path: Path) -> None:
    """T045-FIX B-N3: deadline = min(hard_stop, start+max_wall_seconds, eligible_until)."""
    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport(never_completes=True)
    eligible_until = T0 + timedelta(seconds=5)
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
        max_wall_seconds=60,
        rights={"eligible_until": eligible_until.isoformat()},
    )
    record = result.record
    assert record["deadline_hit"] is True
    assert record["deadline_utc"] == eligible_until.isoformat()
    assert record["terminate_verified_at"] is not None


def test_execute_refuses_a_database_with_two_budget_episodes(db: Database, tmp_path: Path) -> None:
    """T045-FIX B-S9: the run may charge exactly one episode - a database with two
    episodes that have budget accounts refuses before any reservation or transport."""
    from microdrama.contracts.errors import NotFound

    _seed_everything(db)
    with db.transaction() as tx:
        season = seed_season(tx)
        seed_episode(tx, season, number=2)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000)",
            (account, season, seed_episode(tx, season, number=3)),
        )
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport()
    with pytest.raises(NotFound, match="more than one episode"):
        _execute(
            db,
            tmp_path,
            clock=FakeClock(T0),
            runpod_transport=runpod_transport,
            comfy_transport=comfy_transport,
        )
    assert runpod_transport.calls == []


def test_execute_refuses_a_mismatched_pinned_episode(db: Database, tmp_path: Path) -> None:
    """T045-FIX B-S9: the authorization's pinned episode must be this database's."""
    from microdrama.contracts.errors import NotFound

    _seed_everything(db)
    other = str(uuid.uuid4())
    runpod_transport = RunpodCanaryTransport()
    with pytest.raises(NotFound, match="pinned episode"):
        _execute(
            db,
            tmp_path,
            clock=FakeClock(T0),
            runpod_transport=runpod_transport,
            comfy_transport=ComfyCanaryTransport(),
            episode_id=other,
        )
    assert runpod_transport.calls == []
    with db.transaction(readonly=True) as tx:
        assert tx.fetchval("SELECT count(*) FROM reservations") == 0


def test_the_dsn_must_be_loopback() -> None:
    """T045-FIX B-S9: a non-loopback DSN is refused before any reservation, transport
    call or database query - never staging or production."""
    from microdrama.contracts.errors import EffectDenied
    from microdrama.pipeline.canary import refuse_non_loopback_dsn

    for host in ("db.example.com", "10.0.0.5", "staging.internal"):
        with pytest.raises(EffectDenied, match="loopback"):
            refuse_non_loopback_dsn(f"postgresql://user@{host}:5432/postgres")
    refuse_non_loopback_dsn("postgresql://user@127.0.0.1:5544/postgres")
    refuse_non_loopback_dsn("postgresql://user@localhost:5544/postgres")


def test_a_failed_shutdown_still_writes_the_record_with_the_pod(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-S3: a DELETE that returns 503 during shutdown leaves a record with
    outcome NOT_CLEAN and the created Pod's id - never a silent 'refused'."""
    import json as _json

    from microdrama.pipeline.canary import CanaryRunNotClean

    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport(failing_delete=True)
    comfy_transport = ComfyCanaryTransport()
    with pytest.raises(CanaryRunNotClean) as exc:
        _execute(
            db,
            tmp_path,
            clock=clock,
            runpod_transport=runpod_transport,
            comfy_transport=comfy_transport,
        )
    record = _json.loads(exc.value.record_path.read_text())
    assert record["pod_id"] == POD
    assert record["client_tokens"]
    assert record["reservation_ids"]
    assert record["outcome"] == "NOT_CLEAN"


def test_a_malformed_comfy_body_still_leaves_a_record(db: Database, tmp_path: Path) -> None:
    """T045-FIX B-S3: a non-Microdrama exception (malformed ComfyUI JSON) is recorded
    too - the shutdown path runs and the record is written before the re-raise."""
    import json as _json

    from microdrama.pipeline.canary import CanaryRunNotClean

    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport(malformed_history=True)
    with pytest.raises(CanaryRunNotClean):
        _execute(
            db,
            tmp_path,
            clock=clock,
            runpod_transport=runpod_transport,
            comfy_transport=comfy_transport,
        )
    records = sorted((tmp_path / "records").glob("*-canary.json"))
    assert records
    record = _json.loads(records[-1].read_text())
    assert record["outcome"] == "NOT_CLEAN"
    assert "Error" in record["not_clean_reason"]  # a non-Microdrama exception
    # The Pod was still stopped and terminated by the shutdown path.
    assert runpod_transport.state == "GONE"
