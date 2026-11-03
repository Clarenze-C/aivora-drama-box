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
    CanaryRunNotClean,
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
        late_port_reads: int = 0,
        never_port_reads: bool = False,
    ) -> None:
        self.state = "RUNNING" if not create_timeout_once else "ABSENT"
        self.create_calls = 0
        self.create_timeout_once = create_timeout_once
        self.out_of_band_created = create_timeout_once
        self.image = image or IMAGE_REF
        self.no_comfy_port = no_comfy_port
        self.failing_delete = failing_delete
        #: T045-FIX RR-N5: read-backs may lag the create response on the runtime port.
        self.late_port_reads = late_port_reads
        self.never_port_reads = never_port_reads
        self.get_reads = 0
        #: T045-FIX B-B2: the image reference the create REQUEST actually carried.
        self.created_image: str | None = None
        self.calls: list[tuple[str, str]] = []

    def _ports_visible(self, *, on_create: bool) -> list[dict[str, Any]]:
        port = [{"private": 8188, "public": 8188, "type": "http"}]
        if self.no_comfy_port or (on_create is False and self.never_port_reads):
            return []
        if on_create is False and self.late_port_reads and self.get_reads <= self.late_port_reads:
            return []
        return port

    def _pod_json(self, name: str, *, on_create: bool = False) -> dict[str, Any]:
        return {
            "id": POD,
            "name": name,
            "image": self.image,
            "status": self.state,
            "cost": f"{QUOTE_PER_HOUR / 1_000_000:.6f}",
            "createdAt": T0.isoformat().replace("+00:00", "Z"),
            "gpu": {"id": "A40", "count": 1, "memory": 48},
            "runtime": {"ports": self._ports_visible(on_create=on_create)},
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
            return _Response(
                200, json.dumps(self._pod_json(self.last_name, on_create=True)).encode()
            )
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods?"):
            pods = []
            if self.out_of_band_created and self.state in ("RUNNING", "EXITED"):
                name = getattr(self, "last_name", "") or pod_name(NS, "seed")
                pods.append(self._pod_json(name))
            return _Response(200, json.dumps({"pods": pods, "pagination": {}}).encode())
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods/"):
            if self.state in ("ABSENT", "GONE"):
                return _Response(404, b"")
            self.get_reads += 1
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
        pending_polls: int = 0,
        fail_first_submit: bool = False,
        reconcile_on_submit: bool = False,
    ) -> None:
        self.drop_node = drop_node
        self.never_completes = never_completes
        self.malformed_history = malformed_history
        #: T045-FIX B-S1: the first N history polls report nothing yet.
        self.pending_polls = pending_polls
        #: T045-FIX B-S10: attempt 1 FAILS, attempt 2 succeeds.
        self.fail_first_submit = fail_first_submit
        self.submit_calls = 0
        #: T045-FIX B-S10: the first submit's outcome is unknown (NeedsReconciliation).
        self.reconcile_on_submit = reconcile_on_submit
        self.history_polls = 0
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
        from microdrama.contracts.errors import NeedsReconciliation

        self.calls.append((method, url))
        if method == "GET" and url.endswith("/object_info"):
            return json.dumps(self._object_info()).encode()
        if method == "POST" and url.endswith("/prompt"):
            self.submit_calls += 1
            if self.reconcile_on_submit and self.submit_calls == 1:
                raise NeedsReconciliation(
                    "fixture: the submit's outcome is unknown (provider restart)"
                )
            if self.fail_first_submit:
                self.prompt_id = f"canary-prompt-{self.submit_calls}"
            else:
                self.prompt_id = "canary-prompt-1"
            return json.dumps({"prompt_id": self.prompt_id, "number": 1}).encode()
        if method == "GET" and "/history/" in url:
            if self.malformed_history:
                return b"{not json"
            self.history_polls += 1
            if self.pending_polls and self.history_polls <= self.pending_polls:
                return b"{}"
            if self.never_completes:
                return b"{}"
            failed = self.fail_first_submit and url.rsplit("/", 1)[-1] == "canary-prompt-1"
            status = (
                {"completed": False, "status_str": "error"}
                if failed
                else {
                    "completed": True,
                    "status_str": "success",
                }
            )
            outputs = (
                {}
                if failed
                else {
                    "9": {
                        "video": [
                            {
                                "filename": "canary_out.mp4",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            )
            return json.dumps({self.prompt_id: {"status": status, "outputs": outputs}}).encode()
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
    sleep: Any = None,
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
        sleep=sleep
        if sleep is not None
        else (lambda seconds: clock.advance(ms=int(seconds * 1000))),
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


def test_every_dsn_form_is_parsed_for_its_real_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """T045-FIX RR-S1: the loopback guard reads every DSN form through libpq's own
    parser - the postgres:// scheme, keyword/value DSNs, a query-string host override,
    multi-host lists, service definitions and a hostless DSN's PG* fallback all name
    their real host. Unparseable input is refused, and the accepted forms are loopback
    hosts and absolute unix-socket directories."""
    from microdrama.contracts.errors import EffectDenied
    from microdrama.pipeline.canary import refuse_non_loopback_dsn

    refused = [
        "postgres://u@prod.example.com/db",  # libpq's other URL scheme
        "host=prod.example.com dbname=x",  # keyword/value form
        "postgresql://127.0.0.1/db?host=prod.example.com",  # query host overrides the URL host
        "postgresql:///db?host=prod.example.com",
        "postgresql://u@127.0.0.1,prod.example.com/db",  # multi-host with one remote
        "postgresql://u@prod.example.com,127.0.0.1/db",
        "postgresql://127.0.0.1/db?hostaddr=10.0.0.5",  # hostaddr must be loopback too
        "service=x",  # a service file can name any host
        "hostaddr=10.0.0.5",
        "postgresql://u:p@127.0.0.1/db?host=prod.example.com&password=x",  # never a password leak
    ]
    for dsn in refused:
        with pytest.raises(EffectDenied, match="loopback|service"):
            refuse_non_loopback_dsn(dsn)
    with pytest.raises(EffectDenied, match="parse"):
        refuse_non_loopback_dsn("not a dsn at all ://")
    # A hostless DSN falls back to PGHOST/PGHOSTADDR/PGSERVICE - the same rule applies.
    for var in ("PGHOST", "PGHOSTADDR"):
        monkeypatch.setenv(var, "prod.example.com")
        with pytest.raises(EffectDenied, match="loopback"):
            refuse_non_loopback_dsn("postgres://")
        monkeypatch.delenv(var)
    monkeypatch.setenv("PGSERVICE", "staging")
    with pytest.raises(EffectDenied, match="service"):
        refuse_non_loopback_dsn("postgres://")
    monkeypatch.delenv("PGSERVICE")
    # Accepted: loopback hosts, IPv6 loopback, socket directories, a loopback PGHOST.
    for dsn in (
        "postgresql://127.0.0.1/db",
        "postgresql://localhost:5544/postgres",
        "postgresql://[::1]/db",
        "host=/var/run/postgresql dbname=x",
        # a multi-host list of nothing but loopback (the keyword form carries IPv6)
        "host=127.0.0.1,::1,localhost dbname=x",
    ):
        refuse_non_loopback_dsn(dsn)
    monkeypatch.setenv("PGHOST", "/var/run/postgresql")
    refuse_non_loopback_dsn("postgres://")
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    refuse_non_loopback_dsn("postgres://")
    monkeypatch.delenv("PGHOST")


def test_the_dsn_guard_checks_pghostaddr_and_pgservice_even_with_a_named_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T045-FIX F-5: a DSN that names host=localhost is not enough - libpq prefers
    PGHOSTADDR when both are set, and a service file can name anything. PGHOSTADDR
    must pass the loopback rule unless the DSN pins its own hostaddr; PGSERVICE is
    refused whenever it is set."""
    from microdrama.contracts.errors import EffectDenied
    from microdrama.pipeline.canary import refuse_non_loopback_dsn

    monkeypatch.setenv("PGHOSTADDR", "10.1.1.1")
    with pytest.raises(EffectDenied, match="loopback") as exc_info:
        refuse_non_loopback_dsn("postgresql://user@localhost/db")
    assert exc_info.value.details.get("named_by") == "PGHOSTADDR"
    assert exc_info.value.details.get("host") == "10.1.1.1"
    monkeypatch.delenv("PGHOSTADDR")

    monkeypatch.setenv("PGSERVICE", "prod")
    with pytest.raises(EffectDenied, match="service"):
        refuse_non_loopback_dsn("postgresql://user@localhost/db")
    monkeypatch.delenv("PGSERVICE")

    # A loopback PGHOSTADDR with a named host passes, and a DSN-pinned hostaddr
    # makes the environment value inert.
    monkeypatch.setenv("PGHOSTADDR", "127.0.0.1")
    refuse_non_loopback_dsn("postgresql://user@localhost/db")
    monkeypatch.setenv("PGHOSTADDR", "10.1.1.1")
    refuse_non_loopback_dsn("postgresql://user@localhost/db?hostaddr=127.0.0.1")
    monkeypatch.delenv("PGHOSTADDR")


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


# --- T045-FIX B-S1: a runnable CLI ------------------------------------------------------


def test_the_poll_loop_waits_at_least_two_seconds_between_polls(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-S1: the real time.sleep is the default and every provider poll
    waits at least the 2-second floor - the loop can never hot-loop the provider."""
    _seed_everything(db)
    clock = FakeClock(T0)
    waits: list[float] = []

    def recording_sleep(seconds: float) -> None:
        waits.append(seconds)
        clock.advance(ms=int(seconds * 1000))

    comfy = ComfyCanaryTransport(pending_polls=2)
    _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=RunpodCanaryTransport(),
        comfy_transport=comfy,
        sleep=recording_sleep,
    )
    assert comfy.history_polls >= 3  # two pending polls, then the completed one
    assert waits, "the poll loop must have waited between polls"
    assert all(wait >= 2.0 for wait in waits), waits


def test_the_sweep_subcommand_terminates_an_owned_stray_pod_and_keeps_the_hold(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T045-FIX B-S1: `canary sweep --authorization ... --authorization-sha256 ...`
    composes the same attested world and runs ONE janitor pass through main(argv):
    an orphaned owned Pod is stopped and terminated, and the lease hold stays
    (billing finality is still pending)."""
    from microdrama.pipeline import canary as canary_module
    from microdrama.pipeline.canary_authorization import load_canary_authorization
    from microdrama.rendering.runpod_transport import pod_name

    _seed_everything(db)
    token = "md-pod-sweep-fixture-token"
    transport = RunpodCanaryTransport()
    transport.out_of_band_created = True
    transport.state = "RUNNING"
    transport.last_name = pod_name(NS, token)
    episode = uuid.UUID(CANARY_EPISODE_ID)
    reservation = uuid.uuid4()
    lease = uuid.uuid4()
    with db.transaction() as tx:
        season = tx.fetchval("SELECT season_id FROM episodes WHERE id=%s", (episode,))
        account = tx.fetchval("SELECT id FROM budget_accounts WHERE episode_id=%s", (episode,))
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, "
            "request_hash, category, queue, provider, operation_kind, price, ceilings, "
            "reserved_micro_usd, state, expires_at) VALUES (%s, %s, %s, %s, %s, "
            "'GPU_GENERATION', 'production', 'runpod', 'pod.lease', '{}', '{}', 92400, "
            "'ACTIVE', %s)",
            (
                reservation,
                account,
                uuid.uuid4(),
                f"sweep:{reservation}",
                "0" * 64,
                T0 + timedelta(hours=4),
            ),
        )
        tx.execute(
            "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
            "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
            "hourly_price_micro_usd, lease_expires_at, create_requested_at, "
            "provider_account_ref) VALUES (%s, 'runpod', NULL, %s, %s, %s, %s, "
            "'CLAIMED', 'REQUESTED', 'A40', %s, %s, %s, %s)",
            (
                lease,
                f"microdrama-owned:{NS}",
                token,
                episode,
                reservation,
                QUOTE_PER_HOUR,
                T0 - timedelta(minutes=1),
                T0,
                ACCOUNT,
            ),
        )
        del season
    authorization = _write_authorization(tmp_path)
    _, digest = load_canary_authorization(authorization)
    monkeypatch.setenv("MICRODRAMA_DATABASE_URL", db.dsn)
    # main() builds its own Database from the env DSN; tests hand it the open fixture.
    monkeypatch.setattr(canary_module, "Database", lambda _dsn: db)
    monkeypatch.setenv("MICRODRAMA_EXECUTION_MODE", "PAID_BENCHMARK")
    monkeypatch.setenv("MICRODRAMA_PAID_REQUESTS_ENABLED", "true")
    monkeypatch.setenv("MICRODRAMA_CLOUD_RESOURCES_ENABLED", "true")
    # T045-FIX O-1: sweep requires an explicit object-store root.
    monkeypatch.setenv("MICRODRAMA_OBJECT_STORE_ROOT", str(tmp_path / "canary-objects"))
    clock = FakeClock(T0 + timedelta(minutes=30))
    rc = canary_module.main(
        [
            "sweep",
            "--authorization",
            str(authorization),
            "--authorization-sha256",
            digest,
        ],
        _injection={
            "runpod_transport": transport,
            "comfy_transport": ComfyCanaryTransport(),
            "clock": clock,
            "ids": SequentialIds("sweep-cli"),
            "credential_resolver": lambda _ref: "fixture-dummy-value",
        },
    )
    assert rc == 0
    # The stray owned Pod was stopped AND terminated by the one janitor pass.
    assert transport.state == "GONE"
    assert any(call[0] == "DELETE" for call in transport.calls)
    # The hold is kept: billing finality is pending, nothing was released.
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT state, reserved_micro_usd FROM reservations WHERE id=%s", (reservation,)
        )
        lease_row = tx.fetchone(
            "SELECT pod_id, terminate_verified_at FROM pod_leases WHERE id=%s", (lease,)
        )
    assert row is not None and row["state"] == "ACTIVE"
    assert row["reserved_micro_usd"] == 92_400
    assert lease_row is not None
    assert lease_row["pod_id"] == POD
    assert lease_row["terminate_verified_at"] is not None


def test_the_sweep_refuses_to_stop_a_pod_the_cleanup_guard_does_not_accept(
    db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T045-FIX F-3: the sweep composes the shared durable cleanup guard - never a
    no-op. An owned-NAME Pod with no durable lease row anywhere (a name collision,
    or a Pod from a lost database) is refused: no stop, no terminate, zero
    POST /action and DELETE calls, the failure recorded for the operator. Owned
    Pods with lease rows still go through the janitor rulings (the B-S1 sweep test
    above)."""
    from microdrama.pipeline import canary as canary_module
    from microdrama.pipeline.canary_authorization import load_canary_authorization
    from microdrama.rendering.runpod_transport import pod_name

    _seed_everything(db)
    transport = RunpodCanaryTransport()
    transport.out_of_band_created = True
    transport.state = "RUNNING"
    transport.last_name = pod_name(NS, "ghost-token-with-no-lease")
    _main_env(monkeypatch, db, tmp_path)
    authorization = _write_authorization(tmp_path)
    _, digest = load_canary_authorization(authorization)
    rc = canary_module.main(
        ["sweep", "--authorization", str(authorization), "--authorization-sha256", digest],
        _injection={
            "runpod_transport": transport,
            "comfy_transport": ComfyCanaryTransport(),
            "clock": FakeClock(T0 + timedelta(minutes=30)),
            "ids": SequentialIds("sweep-guard"),
            "credential_resolver": lambda _ref: "fixture-dummy-value",
        },
    )
    assert rc == 0
    effect_calls = [
        c for c in transport.calls if (c[0] == "POST" and "/action" in c[1]) or c[0] == "DELETE"
    ]
    assert effect_calls == []  # F-3: the guard refused before any stop/terminate call
    assert transport.state == "RUNNING"  # the Pod is untouched
    out = capsys.readouterr().out
    assert "stop_orphan" in out and "failed" in out  # the refusal is surfaced


def test_sigterm_during_polling_runs_the_shutdown_path(db: Database, tmp_path: Path) -> None:
    """T045-FIX B-S1: SIGTERM while a prompt is pending raises into the shutdown
    path - the owned Pod is stopped and terminated and the record is written."""
    import os as _os
    import signal as _signal

    _seed_everything(db)
    clock = FakeClock(T0)
    comfy = ComfyCanaryTransport(never_completes=True)
    delivered: list[bool] = []

    def sleep_and_interrupt(seconds: float) -> None:
        clock.advance(ms=int(seconds * 1000))
        if not delivered:
            delivered.append(True)
            _os.kill(_os.getpid(), _signal.SIGTERM)

    transport = RunpodCanaryTransport()
    with pytest.raises(CanaryRunNotClean):
        _execute(
            db,
            tmp_path,
            clock=clock,
            runpod_transport=transport,
            comfy_transport=comfy,
            sleep=sleep_and_interrupt,
        )
    assert transport.state == "GONE"  # stopped AND terminated by the shutdown path
    assert any(call[0] == "DELETE" for call in transport.calls)
    records = sorted((tmp_path / "records").glob("*.json"))
    assert records, "the canary record must exist even after SIGTERM"
    record = json.loads(records[-1].read_text())
    assert record["outcome"] == "NOT_CLEAN"
    assert "SIGTERM" in record["not_clean_reason"]


# --- T045-FIX F-2: signal handlers across the shutdown path ------------------------------


class SigtermOnStopTransport(RunpodCanaryTransport):
    """Delivers a second SIGTERM when the shutdown path first stops the Pod."""

    def __init__(self) -> None:
        super().__init__()
        self.delivered = False

    def request(self, method: str, url: str, *, headers: Any, body: bytes | None = None) -> Any:
        import os as _os
        import signal as _signal

        if method == "POST" and url.endswith("/action") and not self.delivered:
            self.delivered = True
            _os.kill(_os.getpid(), _signal.SIGTERM)
        return super().request(method, url, headers=headers, body=body)


def test_a_second_sigterm_during_shutdown_does_not_kill_the_run(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX F-2: a SIGTERM delivered WHILE the shutdown runs (here: when the
    stop request goes out) is ignored and logged - the previous handlers are
    restored only after the record is written, so the default action never fires:
    stop/terminate still complete and the record exists."""
    import os as _os
    import signal as _signal

    _seed_everything(db)
    clock = FakeClock(T0)
    comfy = ComfyCanaryTransport(never_completes=True)
    transport = SigtermOnStopTransport()
    delivered: list[bool] = []

    def sleep_and_interrupt(seconds: float) -> None:
        clock.advance(ms=int(seconds * 1000))
        if not delivered:
            delivered.append(True)
            _os.kill(_os.getpid(), _signal.SIGTERM)

    with pytest.raises(CanaryRunNotClean):
        _execute(
            db,
            tmp_path,
            clock=clock,
            runpod_transport=transport,
            comfy_transport=comfy,
            sleep=sleep_and_interrupt,
        )
    # The shutdown path survived the second signal: stopped AND terminated.
    assert transport.delivered, "the second SIGTERM must arrive during the shutdown"
    assert transport.state == "GONE"
    assert any(call[0] == "DELETE" for call in transport.calls)
    records = sorted((tmp_path / "records").glob("*.json"))
    assert records, "the canary record must exist even after the second SIGTERM"
    record = json.loads(records[-1].read_text())
    assert record["terminate_verified_at"] is not None
    assert record["ignored_interrupts"] == ["ignored SIGTERM during shutdown"]


def test_sigint_takes_the_same_path_as_sigterm(db: Database, tmp_path: Path) -> None:
    """T045-FIX F-2: SIGINT raises into the same shutdown path as SIGTERM - the
    owned Pod is stopped and terminated and the record is written."""
    import os as _os
    import signal as _signal

    _seed_everything(db)
    clock = FakeClock(T0)
    comfy = ComfyCanaryTransport(never_completes=True)
    delivered: list[bool] = []

    def sleep_and_interrupt(seconds: float) -> None:
        clock.advance(ms=int(seconds * 1000))
        if not delivered:
            delivered.append(True)
            _os.kill(_os.getpid(), _signal.SIGINT)

    transport = RunpodCanaryTransport()
    with pytest.raises(CanaryRunNotClean):
        _execute(
            db,
            tmp_path,
            clock=clock,
            runpod_transport=transport,
            comfy_transport=comfy,
            sleep=sleep_and_interrupt,
        )
    assert transport.state == "GONE"
    assert any(call[0] == "DELETE" for call in transport.calls)
    records = sorted((tmp_path / "records").glob("*.json"))
    record = json.loads(records[-1].read_text())
    assert record["outcome"] == "NOT_CLEAN"
    assert "SIGINT" in record["not_clean_reason"]


def test_a_refused_execute_leaves_the_previous_handlers_in_place(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX F-2: a refusal that raises before the run body (a sha mismatch) must
    not leak the canary interrupt handlers - the previous handlers are still
    installed afterwards."""
    import signal as _signal

    from microdrama.contracts.errors import MicrodramaError
    from microdrama.persistence.object_store import FilesystemObjectStore
    from microdrama.pipeline import canary as canary_module
    from microdrama.pipeline.canary_authorization import load_canary_authorization

    _seed_everything(db)
    authorization = _write_authorization(tmp_path)
    _, digest = load_canary_authorization(authorization)
    before = (_signal.getsignal(_signal.SIGTERM), _signal.getsignal(_signal.SIGINT))
    with pytest.raises(MicrodramaError):
        canary_module.run_execute(
            authorization,
            expected_sha256="0" * 64,  # never the real digest: refused
            settings=_live_settings(),
            db=db,
            store=FilesystemObjectStore(tmp_path / "objects"),
            prompts_path=_write_prompts(tmp_path),
            clock=FakeClock(T0),
            ids=SequentialIds("f2-refused"),
            credential_resolver=lambda _ref: "fixture-dummy-value",
            runpod_transport=RunpodCanaryTransport(),
            comfy_transport=ComfyCanaryTransport(),
            evidence_dir=tmp_path / "records",
        )
    after = (_signal.getsignal(_signal.SIGTERM), _signal.getsignal(_signal.SIGINT))
    assert after == before


# --- T045-FIX RR-N5: wait for the created Pod's runtime port before binding ---------------


def test_a_pod_that_reports_its_port_late_still_proceeds(db: Database, tmp_path: Path) -> None:
    """T045-FIX RR-N5: a Pod whose read-backs report no 8188 port for the first two
    reads (a RUNNING pod whose runtime block is not populated yet) is polled - the run
    proceeds once the port appears."""
    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport(late_port_reads=2)
    comfy_transport = ComfyCanaryTransport()
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    assert runpod_transport.get_reads >= 3  # two portless reads, then the port
    assert any("/object_info" in url for _method, url in comfy_transport.calls)
    assert result.record["outcome"] == "COMPLETE"


def test_a_pod_that_never_reports_ports_stops_at_the_deadline_with_zero_comfy_calls(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX RR-N5: a Pod whose read-backs never expose the 8188 port stops at the
    run deadline - stopped, terminated, NOT CLEAN - with zero ComfyUI calls."""
    import json as _json

    from microdrama.pipeline.canary import CanaryRunNotClean

    _seed_everything(db)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport(never_port_reads=True)
    comfy_transport = ComfyCanaryTransport()
    with pytest.raises(CanaryRunNotClean, match="no Comfy endpoint"):
        _execute(
            db,
            tmp_path,
            clock=clock,
            runpod_transport=runpod_transport,
            comfy_transport=comfy_transport,
        )
    assert comfy_transport.calls == []  # the bearer token never left for the Pod
    assert runpod_transport.state == "GONE"  # stopped AND terminated at the deadline
    assert any(call[0] == "DELETE" for call in runpod_transport.calls)
    records = sorted((tmp_path / "records").glob("*.json"))
    assert records
    record = _json.loads(records[-1].read_text())
    assert record["outcome"] == "NOT_CLEAN"
    assert record["deadline_hit"] is True


# --- T045-FIX B-S10: the composed flow through main(argv) --------------------------------


def _main_env(monkeypatch: pytest.MonkeyPatch, db: Database, tmp_path: Path) -> None:
    from microdrama.pipeline import canary as canary_module

    monkeypatch.setenv("MICRODRAMA_DATABASE_URL", db.dsn)
    monkeypatch.setenv("MICRODRAMA_EXECUTION_MODE", "PAID_BENCHMARK")
    monkeypatch.setenv("MICRODRAMA_PAID_REQUESTS_ENABLED", "true")
    monkeypatch.setenv("MICRODRAMA_CLOUD_RESOURCES_ENABLED", "true")
    # T045-FIX O-1: every main(argv) test sets the object-store root under its
    # own tmp_path - the CLI has no cwd-relative default any more.
    monkeypatch.setenv("MICRODRAMA_OBJECT_STORE_ROOT", str(tmp_path / "canary-objects"))
    monkeypatch.setattr(canary_module, "Database", lambda _dsn: db)


def test_the_full_composed_flow_runs_through_main_argv(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T045-FIX B-S10: execute -> sweep -> invoice -> sweep, all through main(argv)
    with the test-only injection seam. The account total and the charge sum equal
    the invoice, and the finalization rows exist."""
    from microdrama.pipeline import canary as canary_module
    from microdrama.pipeline.canary_authorization import load_canary_authorization

    _seed_everything(db)
    _main_env(monkeypatch, db, tmp_path)
    clock = FakeClock(T0)
    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport()
    authorization = _write_authorization(tmp_path)
    _, digest = load_canary_authorization(authorization)
    injection = {
        "runpod_transport": runpod_transport,
        "comfy_transport": comfy_transport,
        "clock": clock,
        "ids": SequentialIds("main-argv"),
        "credential_resolver": lambda _ref: "fixture-dummy-value",
        "evidence_dir": tmp_path / "records",
        "sleep": lambda seconds: clock.advance(ms=int(seconds * 1000)),
    }
    rc = canary_module.main(
        [
            "execute",
            "--authorization",
            str(authorization),
            "--authorization-sha256",
            digest,
            "--prompts",
            str(_write_prompts(tmp_path)),
        ],
        _injection=injection,
    )
    assert rc == 0
    assert runpod_transport.state == "GONE"

    clock.advance(seconds=2 * 3600 + 1800)
    assert (
        canary_module.main(
            ["sweep", "--authorization", str(authorization), "--authorization-sha256", digest],
            _injection=injection,
        )
        == 0
    )
    evidence = tmp_path / "invoice-main.pdf"
    evidence.write_bytes(b"fixture operator invoice")
    invoice_total = GPU_BUCKET + CPU_BUCKET + DISK_BUCKET
    rc = canary_module.main(
        [
            "invoice",
            "--authorization",
            str(authorization),
            "--pod-id",
            POD,
            "--period-start",
            T0.isoformat(),
            "--period-end",
            WINDOW_END.isoformat(),
            "--amount-micro-usd",
            str(invoice_total),
            "--evidence",
            str(evidence),
            "--source",
            "INVOICE",
            "--observed-at",
            (T0 + timedelta(hours=3)).isoformat(),
        ],
        _injection=injection,
    )
    assert rc == 0
    clock.advance(seconds=600)
    assert (
        canary_module.main(
            ["sweep", "--authorization", str(authorization), "--authorization-sha256", digest],
            _injection=injection,
        )
        == 0
    )
    # The account total and the provider-reported charge sum equal the invoice (the
    # lease SETTLEMENT finalizes the accrual it covers - the raw charge-table sum
    # double-counts by ledger design, as recorded for B-B1); the ledger side of the
    # verification left its finalization rows.
    assert _account_counters(db)["settled"] == invoice_total
    assert _provider_reported_total(db) == invoice_total
    charges_before_replay = _charge_total(db)
    with db.transaction(readonly=True) as tx:
        finalizations = tx.fetchval("SELECT count(*) FROM runpod_billing_budget_finalizations")
        reservation_state = tx.fetchval(
            "SELECT state FROM reservations WHERE operation_kind='pod.lease'"
        )
    assert finalizations >= 1
    assert reservation_state == "SETTLED"
    # A replayed sweep after the verified invoice adds no money.
    clock.advance(seconds=600)
    assert (
        canary_module.main(
            ["sweep", "--authorization", str(authorization), "--authorization-sha256", digest],
            _injection=injection,
        )
        == 0
    )
    assert _charge_total(db) == charges_before_replay
    assert _account_counters(db)["settled"] == invoice_total


def test_preflight_makes_zero_transport_and_zero_resolver_calls(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T045-FIX B-S10: preflight is a pure plan - no transport call, no credential
    resolution, before anything is refused or run. T045-FIX O-1: preflight reads and
    writes no object store, so it must not create one either."""
    from microdrama.pipeline import canary as canary_module

    _seed_everything(db)
    _main_env(monkeypatch, db, tmp_path)
    monkeypatch.delenv("MICRODRAMA_OBJECT_STORE_ROOT", raising=False)
    # O-1: with the old cwd-relative default a preflight call mkdir'd
    # ./canary-objects right where the operator stood - it must not anymore.
    monkeypatch.chdir(tmp_path)
    resolver_calls: list[str] = []

    def resolver(ref: str) -> str | None:
        resolver_calls.append(ref)
        return "fixture-dummy-value"

    runpod_transport = RunpodCanaryTransport()
    comfy_transport = ComfyCanaryTransport()
    authorization = _write_authorization(tmp_path)
    rc = canary_module.main(
        ["preflight", "--authorization", str(authorization)],
        _injection={
            "runpod_transport": runpod_transport,
            "comfy_transport": comfy_transport,
            "clock": FakeClock(T0),
            "credential_resolver": resolver,
        },
    )
    assert rc == 0
    assert runpod_transport.calls == []
    assert comfy_transport.calls == []
    assert resolver_calls == []
    assert not (tmp_path / "canary-objects").exists()  # O-1: no store created


def test_a_failed_attempt_then_success_reuses_the_hold_and_keeps_the_failed_charge(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-S10: attempt 1 fails, attempt 2 succeeds within max_attempts. One
    prompt hold is REUSED by the retry, and the failed attempt keeps its settlement
    row (R1: the execution seconds were spent) - lease-covered, so at zero charge."""
    _seed_everything(db)
    clock = FakeClock(T0)
    comfy_transport = ComfyCanaryTransport(fail_first_submit=True)
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=RunpodCanaryTransport(),
        comfy_transport=comfy_transport,
    )
    record = result.record
    assert comfy_transport.submit_calls == 2
    assert record["attempts_used"] == 2
    step_names = [step["step"] for step in record["steps"]]
    assert "prompt_failed" in step_names and "prompt_succeeded" in step_names
    # ONE prompt reservation, reused by both attempts: the failed attempt left the
    # shared hold ACTIVE for the retry (B-S10), and the success settled it at zero.
    with db.transaction(readonly=True) as tx:
        holds = tx.fetchall(
            "SELECT id, state, settled_micro_usd FROM reservations "
            "WHERE operation_kind='comfy.queue_prompt'"
        )
        attempt_settlements = tx.fetchall(
            "SELECT c.amount_micro_usd FROM charges c "
            "JOIN reservations r ON r.id = c.reservation_id "
            "WHERE r.operation_kind='comfy.queue_prompt' AND c.kind='SETTLEMENT'"
        )
        failed_operations = tx.fetchval(
            "SELECT count(*) FROM provider_operations WHERE state='FAILED'"
        )
        succeeded_operations = tx.fetchval(
            "SELECT count(*) FROM provider_operations WHERE state='SUCCEEDED'"
        )
    assert len(holds) == 1
    assert holds[0]["state"] == "SETTLED"  # settled at prompt end
    assert holds[0]["settled_micro_usd"] == 0  # lease-covered (B-B1)
    assert len(attempt_settlements) == 1
    assert attempt_settlements[0]["amount_micro_usd"] == 0
    # R1: the failed attempt stays charged - its operation row is durably FAILED
    # (never erased, never refunded) and its GPU seconds live in the lease invoice.
    assert failed_operations == 1 and succeeded_operations == 1


def test_a_failed_final_attempt_settles_the_prompt_hold(db: Database, tmp_path: Path) -> None:
    """T045-FIX F-4: with max_attempts=1 and a failing attempt no retry follows, so
    the prompt's shared hold must not stay reserved past the run - it settles at zero
    and the account carries nothing outstanding for it."""
    _seed_everything(db)
    clock = FakeClock(T0)
    comfy_transport = ComfyCanaryTransport(fail_first_submit=True)
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=RunpodCanaryTransport(),
        comfy_transport=comfy_transport,
        caps={"max_attempts": 1},
    )
    record = result.record
    assert comfy_transport.submit_calls == 1  # the cap allowed exactly one attempt
    with db.transaction(readonly=True) as tx:
        hold = tx.fetchone(
            "SELECT id, state, settled_micro_usd FROM reservations "
            "WHERE operation_kind='comfy.queue_prompt'"
        )
        other_outstanding = tx.fetchval(
            "SELECT COALESCE(SUM(reserved_micro_usd), 0) FROM reservations "
            "WHERE state = 'ACTIVE' AND operation_kind <> 'comfy.queue_prompt'"
        )
        account = tx.fetchone("SELECT reserved_outstanding_micro_usd FROM budget_accounts LIMIT 1")
    assert hold is not None
    assert hold["state"] == "SETTLED"  # F-4: not left ACTIVE with no retry to reuse it
    assert hold["settled_micro_usd"] == 0  # lease-covered: zero charge (B-B1)
    assert any(
        s["step"] == "prompt_hold_settled" and s["detail"]["reservation_id"] == str(hold["id"])
        for s in record["steps"]
    )
    # The account carries nothing outstanding for the prompt hold.
    assert account["reserved_outstanding_micro_usd"] == other_outstanding


def test_a_needs_reconciliation_during_submit_stops_for_a_human(
    db: Database, tmp_path: Path
) -> None:
    """T045-FIX B-S10: a submit whose outcome is unknown stops the run for a human -
    no blind retry, no second create, and the shutdown path still runs."""
    _seed_everything(db)
    clock = FakeClock(T0)
    comfy_transport = ComfyCanaryTransport(reconcile_on_submit=True)
    runpod_transport = RunpodCanaryTransport()
    result = _execute(
        db,
        tmp_path,
        clock=clock,
        runpod_transport=runpod_transport,
        comfy_transport=comfy_transport,
    )
    record = result.record
    assert comfy_transport.submit_calls == 1  # never resubmitted blind
    assert record["attempts_used"] == 1
    assert record["ambiguous"], "the ambiguity must be recorded for the human"
    assert "ambiguous submit/poll stopped for a human" in record["blocked_or_uncertain"]
    # The shutdown path ran: the owned Pod was stopped and terminated.
    assert runpod_transport.state == "GONE"
    assert any(call[0] == "DELETE" for call in runpod_transport.calls)
    assert record["terminate_verified_at"] is not None


# --- T045-FIX B-N7: max_attempts is a global cap across all prompts ----------------------


def test_max_attempts_is_a_global_cap_across_all_prompts(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T045-FIX B-N7: the cap counts submit attempts across ALL prompts of the run -
    when prompt 1 exhausts it, prompt 2 is never submitted - and the authorization
    field says exactly that."""
    import json as _json

    from microdrama.persistence.object_store import FilesystemObjectStore
    from microdrama.pipeline import canary as canary_module
    from microdrama.pipeline.canary_authorization import (
        CanaryCaps,
        load_canary_authorization,
    )

    _seed_everything(db)
    prompts = [_prompt(), _prompt() | {"seed": 20261103}]
    document = _authorization_document(
        caps={"max_prompts": 2, "max_attempts": 2},
        prompt_sha256=[prompt_pin(item) for item in prompts],
    )
    prompts_path = tmp_path / "prompts-two.json"
    prompts_path.write_text(_json.dumps(prompts))
    authorization = tmp_path / "canary-two.json"
    authorization.write_text(_json.dumps(document, indent=2))
    _, digest = load_canary_authorization(authorization)
    comfy_transport = ComfyCanaryTransport(fail_first_submit=True)
    clock = FakeClock(T0)
    result = canary_module.run_execute(
        authorization,
        expected_sha256=digest,
        settings=_live_settings(),
        db=db,
        store=FilesystemObjectStore(tmp_path / "objects"),
        prompts_path=prompts_path,
        clock=clock,
        ids=SequentialIds("b-n7"),
        credential_resolver=lambda _ref: "fixture-dummy-value",
        runpod_transport=RunpodCanaryTransport(),
        comfy_transport=comfy_transport,
        evidence_dir=tmp_path / "records",
        sleep=lambda seconds: clock.advance(ms=int(seconds * 1000)),
    )
    # Prompt 1 burned both allowed attempts (fail, then succeed); prompt 2 got none.
    assert comfy_transport.submit_calls == 2
    assert result.record["attempts_used"] == 2
    assert "attempt cap reached" in result.record["blocked_or_uncertain"]
    steps = [step for step in result.record["steps"] if step["step"] == "prompts"]
    assert steps and steps[0]["detail"]["submitted"] == 1
    # The authorization field description states the global semantics.
    description = str(CanaryCaps.model_fields["max_attempts"].description)
    assert "GLOBAL" in description and "across ALL prompts" in description
