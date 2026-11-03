"""T045 R9 (G10/G14): janitor billing ingestion over fixture Runpod transports.

Red-first: nothing mapped ``RunpodBillingRecord`` to ``RunpodBillingBucketObservation``
and the janitor never pulled provider billing, so a terminated Pod's cost could never
be read back (its billing history was refused once the Pod was absent at the
provider).

All tests run on real PostgreSQL with a scripted Runpod transport: no network, no
credential value beyond a constant fixture dummy, no provider outside the loopback
test guard.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from microdrama.budget import BudgetService
from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.persistence import Database
from microdrama.rendering import RunpodInvoiceFinality, build_janitor
from microdrama.rendering.janitor import Janitor
from microdrama.rendering.leases import PodLeaseConfig
from microdrama.rendering.runpod_billing import durable_pod_ownership_probe
from microdrama.rendering.runpod_transport import (
    RunpodQuoteAttestation,
    RunpodRestProvider,
)
from microdrama.testing.fakes import FakeClock, SequentialIds
from microdrama.testing.seed import seed_episode, seed_season

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 2, 12, tzinfo=UTC)
NS = "t045a"
TAG = f"microdrama-owned:{NS}"
ACCOUNT = "acct:runpod-t045"
POD = "pod-t045-bill"
IMAGE = "registry.example/comfy@sha256:" + "a" * 64
WINDOW_START = T0
WINDOW_END = T0 + timedelta(hours=1)
SWEEP_AT = T0 + timedelta(hours=2, minutes=30)  # past the 15-minute settle lag


@dataclass
class _Response:
    status: int
    body: bytes


class ScriptedBillingTransport:
    """Serves Pod reads (or 404) plus a mutable billing response."""

    def __init__(self, *, records: list[dict[str, Any]], pod_present: bool) -> None:
        self.records = records
        self.pod_present = pod_present
        self.calls: list[tuple[str, str]] = []

    def billing_json(self) -> bytes:
        return json.dumps(
            {
                "records": self.records,
                "metadata": {
                    "query": {
                        "startTime": WINDOW_START.isoformat().replace("+00:00", "Z"),
                        "endTime": WINDOW_END.isoformat().replace("+00:00", "Z"),
                    }
                },
            }
        ).encode()

    def request(
        self, method: str, url: str, *, headers: Any, body: bytes | None = None
    ) -> _Response:
        self.calls.append((method, url))
        if method == "GET" and url.startswith("https://api.runpod.io/v2/pods?"):
            return _Response(200, json.dumps({"pods": [], "pagination": {}}).encode())
        if url.startswith("https://api.runpod.io/v2/pods/") and method == "GET":
            if not self.pod_present:
                return _Response(404, b"")
            return _Response(200, _pod_json().encode())
        if "/billing/pods" in url:
            return _Response(200, self.billing_json())
        if method == "DELETE":
            self.pod_present = False
            return _Response(200, b"{}")
        raise AssertionError(f"unexpected fixture call: {method} {url}")


def _pod_json() -> str:
    return json.dumps(
        {
            "id": POD,
            "name": f"md-{NS}-" + "0" * 32,
            "image": IMAGE,
            "status": "TERMINATED",
            "cost": "0.504000",
            "createdAt": WINDOW_START.isoformat().replace("+00:00", "Z"),
            "gpu": {"id": "NVIDIA A40", "count": 1, "memory": 48},
            "runtime": {},
        }
    )


def _attestation() -> RunpodQuoteAttestation:
    return RunpodQuoteAttestation(
        namespace=NS,
        quote_id="quote-t045-ingest",
        currency="USD",
        provider_account_ref=ACCOUNT,
        quote_micro_usd_per_hour=504_000,
        quote_as_of=T0 - timedelta(minutes=1),
        expires_at=T0 + timedelta(hours=6),
        container_disk_gb=1,
        container_storage_micro_usd_per_gb_month=100_000,
        persistent_volume_gb=5,
        persistent_storage_micro_usd_per_gb_month=200_000,
        max_storage_exposure_micro_usd=1_200_000,
        pinned_image=IMAGE,
        allowed_gpu_types=frozenset({"NVIDIA A40"}),
        host_ram_gb_by_gpu={"NVIDIA A40": 64},
        rights_evidence_id="rights-t045",
        preset_evidence_id="preset-t045",
        activation_enabled=True,
    )


def _provider(transport: ScriptedBillingTransport, db: Database) -> RunpodRestProvider:
    settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    return RunpodRestProvider(
        settings,
        credential_ref="credref:runpod-fixture",
        credential_resolver=lambda _ref: "fixture-dummy-value",
        attestation=_attestation(),
        now=lambda: SWEEP_AT,
        reservation_guard=lambda _request, _attestation: None,
        cleanup_guard=lambda _operation, _pod_id: None,
        absent_pod_ownership_probe=durable_pod_ownership_probe(
            db, owned_tag=TAG, provider_account_ref=ACCOUNT
        ),
        transport=transport,
    )


def _record(
    *,
    gpu: str = "0.400000",
    cpu: str = "0.050000",
    disk: str = "0.050000",
    total: str | None = None,
) -> dict[str, Any]:
    return {
        "podId": POD,
        "startTime": WINDOW_START.isoformat().replace("+00:00", "Z"),
        "endTime": WINDOW_END.isoformat().replace("+00:00", "Z"),
        "totalAmount": total
        if total is not None
        else f"{float(gpu) + float(cpu) + float(disk):.6f}",
        "gpuAmount": gpu,
        "cpuAmount": cpu,
        "diskAmount": disk,
    }


def _seed_terminated_lease(
    db: Database,
    *,
    reservation_state: str = "ACTIVE",
    pod_id: str = POD,
    terminate: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An episode, account, active hold and a terminated runpod lease over the window."""
    reservation = uuid.uuid4()
    lease = uuid.uuid4()
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, "
            "cap_micro_usd, reserved_outstanding_micro_usd) "
            "VALUES (%s, 'EPISODE', %s, %s, 10000000, 504000)",
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
            "allocated_micro_usd, reserved_outstanding_micro_usd, protected) "
            "VALUES (%s, 'GPU_GENERATION', 9000000, 504000, true)",
            (account,),
        )
        tx.execute(
            "INSERT INTO reservations (id, account_id, request_id, semantic_key, "
            "request_hash, category, queue, provider, operation_kind, price, ceilings, "
            "reserved_micro_usd, state, expires_at) VALUES (%s, %s, %s, %s, %s, "
            "'GPU_GENERATION', 'production', 'runpod', 'pod.lease', '{}', '{}', 504000, "
            "%s, %s)",
            (
                reservation,
                account,
                uuid.uuid4(),
                f"t045i:{reservation}",
                "0" * 64,
                reservation_state,
                T0 + timedelta(hours=6),
            ),
        )
        tx.execute(
            "INSERT INTO pod_leases (id, provider, pod_id, owned_tag, client_token, "
            "owner_episode_id, reservation_id, lease_state, pod_state, gpu_type, "
            "hourly_price_micro_usd, lease_expires_at, create_requested_at, "
            "compute_window_start_at, compute_window_end_at, stop_verified_at, "
            "terminate_verified_at, provider_account_ref) "
            "VALUES (%s, 'runpod', %s, %s, %s, %s, %s, 'RELEASED', 'TERMINATED', "
            "'NVIDIA A40', 504000, %s, %s, %s, %s, %s, %s, %s)",
            (
                lease,
                pod_id,
                TAG,
                f"tok-{lease}",
                episode,
                reservation,
                T0 + timedelta(hours=2),
                WINDOW_START,
                WINDOW_START,
                WINDOW_END,
                WINDOW_END,
                WINDOW_END if terminate else None,
                ACCOUNT,
            ),
        )
    return lease, reservation, account


def _charge_amounts(db: Database) -> list[int]:
    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall("SELECT amount_micro_usd FROM charges ORDER BY created_at, id")
    return [row["amount_micro_usd"] for row in rows]


def _janitor(
    db: Database,
    provider: RunpodRestProvider,
    *,
    now: datetime = SWEEP_AT,
    seq: str = "t045-ingest",
) -> Janitor:
    settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    budget = BudgetService(db, FakeClock(now), SequentialIds(seq), settings)
    config = PodLeaseConfig(
        owned_tag=TAG,
        allowed_gpu_types=frozenset({"NVIDIA A40"}),
        min_host_ram_gb=32,
        container_image=IMAGE,
        max_hourly_price_micro_usd=600_000,
        price=None,
        provider_account_ref=ACCOUNT,
    )
    return build_janitor(
        db,
        budget,
        provider,
        FakeClock(now),
        SequentialIds(seq),
        settings,
        config,
        RunpodInvoiceFinality(db, budget_service=budget),
    )


def _counts(db: Database) -> dict[str, int]:
    with db.transaction(readonly=True) as tx:
        return {
            table: tx.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608
            for table in (
                "runpod_billing_queries",
                "runpod_billing_buckets",
                "runpod_billing_allocations",
                "charges",
            )
        }


# --- the fixture tests the R9 fixture list names --------------------------------------


def test_mapping_preserves_exact_micro_usd_from_lexical_amounts(db: Database) -> None:
    """0.000001-precision amounts survive mapping as exact integers (G10)."""
    _seed_terminated_lease(db)
    transport = ScriptedBillingTransport(
        records=[_record(gpu="0.000001", cpu="0.000002", disk="0.000003")],
        pod_present=False,
    )
    report = _janitor(db, _provider(transport, db)).sweep()
    assert report.failures == []
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT total_amount_micro_usd, gpu_amount_micro_usd, cpu_amount_micro_usd, "
            "disk_amount_micro_usd, finality_state FROM runpod_billing_buckets"
        )
    assert row is not None
    assert row["gpu_amount_micro_usd"] == 1
    assert row["cpu_amount_micro_usd"] == 2
    assert row["disk_amount_micro_usd"] == 3
    assert row["total_amount_micro_usd"] == 6
    assert row["finality_state"] == "ALLOCATED_PROVIDER_REPORTED"


def test_a_total_error_is_stored_as_disputed_and_disputes_the_lease(db: Database) -> None:
    from microdrama.budget.billing import lease_billing_readiness

    lease, _, _ = _seed_terminated_lease(db)
    transport = ScriptedBillingTransport(
        records=[_record(total="0.900000")],  # total != gpu + cpu + disk
        pod_present=False,
    )
    report = _janitor(db, _provider(transport, db)).sweep()
    assert report.failures == []
    with db.transaction(readonly=True) as tx:
        row = tx.fetchone(
            "SELECT finality_state, payload->>'dispute_reason' AS dispute_reason "
            "FROM runpod_billing_buckets"
        )
    assert row["finality_state"] == "DISPUTED"
    assert "GPU + CPU + disk" in row["dispute_reason"]
    # The covering DISPUTED bucket makes the lease's readiness DISPUTED (R7).
    assert lease_billing_readiness(db, lease).state == "DISPUTED"


def test_an_empty_response_is_recorded_as_unknown_never_zero(db: Database) -> None:
    _seed_terminated_lease(db)
    transport = ScriptedBillingTransport(records=[], pod_present=False)
    report = _janitor(db, _provider(transport, db)).sweep()
    assert report.failures == []
    with db.transaction(readonly=True) as tx:
        query = tx.fetchone(
            "SELECT result_state, payload->>'unknown_reason' AS reason FROM runpod_billing_queries"
        )
        buckets = tx.fetchval("SELECT count(*) FROM runpod_billing_buckets")
    assert query["result_state"] == "UNKNOWN"
    assert query["reason"]
    assert buckets == 0


def test_an_exact_replay_of_the_same_response_adds_nothing(db: Database) -> None:
    _seed_terminated_lease(db)
    transport = ScriptedBillingTransport(records=[_record()], pod_present=False)
    provider = _provider(transport, db)
    first = _janitor(db, provider).sweep()
    assert first.failures == []
    after_first = _counts(db)
    assert after_first["runpod_billing_buckets"] == 1
    # Clear the backoff the first pending settle scheduled, then sweep again (the
    # ingest's own 5-minute backoff has expired by +30 minutes).
    with db.transaction() as tx:
        tx.execute("UPDATE pod_leases SET next_finality_check_at = NULL")
    second = _janitor(
        db, provider, now=SWEEP_AT + timedelta(minutes=30), seq="t045-ingest-replay"
    ).sweep()
    assert second.failures == []
    assert _counts(db) == after_first
    # T045-FIX B-S4: a nothing-new response is reported REPLAYED (was REPLAY).
    replayed = [a for a in second.billing_ingests if a.outcome == "REPLAYED"]
    assert replayed and replayed[0].subject == f"pod:{POD}"


def test_a_revised_response_posts_only_the_delta(db: Database) -> None:
    _seed_terminated_lease(db)
    transport = ScriptedBillingTransport(records=[_record(gpu="0.400000")], pod_present=False)
    provider = _provider(transport, db)
    assert _janitor(db, provider).sweep().failures == []
    first_charges = _charge_amounts(db)
    assert first_charges.count(400_000) == 1  # the full first-observation GPU amount
    # The provider revises the same bucket upward by 0.100000 USD.
    transport.records = [_record(gpu="0.500000")]
    with db.transaction() as tx:
        tx.execute("UPDATE pod_leases SET next_finality_check_at = NULL")
    report = _janitor(
        db, provider, now=SWEEP_AT + timedelta(minutes=30), seq="t045-ingest-revise"
    ).sweep()
    assert report.failures == []
    with db.transaction(readonly=True) as tx:
        revisions = tx.fetchall("SELECT revision FROM runpod_billing_buckets ORDER BY revision")
    assert [r["revision"] for r in revisions] == [1, 2]
    # Only the +100_000 micro-USD delta posts; the full GPU amount is never repeated.
    assert sorted(_charge_amounts(db)) == sorted(first_charges + [100_000])


def test_ingestion_reads_an_absent_pod_through_the_durable_ownership_proof(
    db: Database,
) -> None:
    """The terminated Pod is absent (404); billing still flows via the DB proof."""
    _seed_terminated_lease(db)
    transport = ScriptedBillingTransport(records=[_record()], pod_present=False)
    report = _janitor(db, _provider(transport, db)).sweep()
    assert report.failures == []
    assert _counts(db)["runpod_billing_buckets"] == 1


def test_without_the_ownership_proof_an_absent_pod_billing_read_is_refused(
    db: Database,
) -> None:
    lease, _, _ = _seed_terminated_lease(db, pod_id="pod-never-terminated", terminate=False)
    with db.transaction() as tx:
        tx.execute("UPDATE pod_leases SET pod_id = %s WHERE id = %s", (POD, lease))
    transport = ScriptedBillingTransport(records=[_record()], pod_present=False)
    provider = _provider(transport, db)
    report = _janitor(db, provider).sweep()
    # No durable proof for this pod id (different pod, no verified terminate): the
    # provider refuses the billing read and the janitor records the failure.
    assert [a for a in report.billing_ingests if a.subject == "pod:pod-t045-bill"] == []
    failures = [a for a in report.failures if a.action == "billing_ingest"]
    assert failures and "ownership" in failures[0].detail
    assert _counts(db)["runpod_billing_buckets"] == 0


def test_open_buckets_are_skipped_and_the_query_is_unknown(db: Database) -> None:
    """A bucket not past the settle lag is open: skipped, not stored as zero."""
    _seed_terminated_lease(db)
    fresh_end = SWEEP_AT - timedelta(minutes=5)  # < settle lag behind the observation
    record = _record()
    record["endTime"] = fresh_end.isoformat().replace("+00:00", "Z")
    transport = ScriptedBillingTransport(records=[record], pod_present=False)
    report = _janitor(db, _provider(transport, db)).sweep()
    assert report.failures == []
    with db.transaction(readonly=True) as tx:
        query = tx.fetchone("SELECT result_state FROM runpod_billing_queries")
        skipped = tx.fetchval("SELECT count(*) FROM runpod_billing_query_skipped_buckets")
    assert query["result_state"] == "UNKNOWN"
    assert skipped == 1


def _open_records(*, end: datetime | None = None) -> list[dict[str, Any]]:
    """One bucket that is still open at the sweep instant."""
    return [
        {
            "podId": POD,
            "startTime": WINDOW_START.isoformat().replace("+00:00", "Z"),
            "endTime": (end or WINDOW_END).isoformat().replace("+00:00", "Z"),
            "totalAmount": "0.070000",
            "gpuAmount": "0.050000",
            "cpuAmount": "0.010000",
            "diskAmount": "0.010000",
        }
    ]


def _paid_settings() -> Settings:
    return Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )


def _backoff_row(db: Database) -> dict[str, Any] | None:
    with db.transaction(readonly=True) as tx:
        return tx.fetchone("SELECT * FROM runpod_billing_ingest_backoff WHERE pod_id=%s", (POD,))


def test_four_sweeps_on_a_running_pod_make_one_provider_call(db: Database) -> None:
    """T045-FIX B-S4: the ingest backoff is persisted per Pod - sweeps 20 s apart on
    a running Pod make exactly one provider billing call, and the all-open response
    is reported as SKIPPED_OPEN, never INGESTED."""
    clock = FakeClock(SWEEP_AT)
    transport = ScriptedBillingTransport(
        records=_open_records(end=SWEEP_AT + timedelta(hours=1)), pod_present=True
    )
    provider = RunpodRestProvider(
        _paid_settings(),
        credential_ref="credref:runpod",
        credential_resolver=lambda _ref: "fixture-dummy-value",
        attestation=_attestation(),
        now=clock.now,
        reservation_guard=lambda *_a, **_k: None,
        cleanup_guard=lambda *_o, **_k: None,
        absent_pod_ownership_probe=lambda *_a, **_k: None,
        transport=transport,
    )
    _seed_terminated_lease(db, terminate=False, reservation_state="ACTIVE")
    # A running pod: the lease is live (not expired, heartbeating, no verified
    # terminate), hold ACTIVE.
    with db.transaction() as tx:
        tx.execute(
            "UPDATE pod_leases SET stop_verified_at=NULL, terminate_verified_at=NULL, "
            "lease_state='ACTIVE', lease_expires_at=%s, heartbeat_at=%s WHERE pod_id=%s",
            (SWEEP_AT + timedelta(hours=1), SWEEP_AT, POD),
        )
    billing_calls = lambda: [c for c in transport.calls if "/billing/pods" in c[1]]  # noqa: E731
    for offset in (0, 20, 40, 60):
        clock.advance(seconds=offset)
        # A live worker heartbeats: the running pod must not be janitor-cleaned.
        with db.transaction() as tx:
            tx.execute("UPDATE pod_leases SET heartbeat_at=%s WHERE pod_id=%s", (clock.now(), POD))
        _janitor(db, provider, now=clock.now(), seq=f"bs4-{offset}").sweep()
    assert len(billing_calls()) == 1
    row = _backoff_row(db)
    assert row is not None and row["last_outcome"] == "SKIPPED_OPEN"


def test_an_ingest_failure_is_persisted_and_backed_off(db: Database) -> None:
    """T045-FIX B-S4: a failed ingest is durable hold-keeping evidence and the next
    sweep inside the backoff makes no provider call."""

    from microdrama.contracts.errors import ProviderError

    class _FailingBilling(ScriptedBillingTransport):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url))
            if "/billing/pods" in url:
                raise ProviderError("Runpod billing endpoint is down (fixture)")
            return super().request(method, url, **kwargs)

    transport = _FailingBilling(records=_open_records(), pod_present=True)
    provider = RunpodRestProvider(
        _paid_settings(),
        credential_ref="credref:runpod",
        credential_resolver=lambda _ref: "fixture-dummy-value",
        attestation=_attestation(),
        now=lambda: SWEEP_AT,
        reservation_guard=lambda *_a, **_k: None,
        cleanup_guard=lambda *_o, **_k: None,
        absent_pod_ownership_probe=lambda *_a, **_k: None,
        transport=transport,
    )
    _seed_terminated_lease(db)
    report = _janitor(db, provider, now=SWEEP_AT, seq="bs4-fail").sweep()
    assert any(a.outcome == "failed" for a in report.failures)
    row = _backoff_row(db)
    assert row is not None and row["last_outcome"] == "FAILED"
    assert "fixture" in row["last_detail"]
    billing_calls = [c for c in transport.calls if "/billing/pods" in c[1]]
    assert len(billing_calls) == 1
    _janitor(db, provider, now=SWEEP_AT + timedelta(seconds=30), seq="bs4-fail2").sweep()
    billing_calls = [c for c in transport.calls if "/billing/pods" in c[1]]
    assert len(billing_calls) == 1  # backed off, no new billing call


def test_sweep_soon_then_later_then_invoice_reaches_billed(db: Database) -> None:
    """T045-FIX B-S4 + A-B1 end to end: a sweep 10 minutes after the run (buckets
    still open), the two-hour sweep stores them, the invoice matches, the hold
    settles BILLED."""
    transport = ScriptedBillingTransport(records=_open_records(), pod_present=False)
    clock = FakeClock(WINDOW_END + timedelta(minutes=10))
    provider = RunpodRestProvider(
        _paid_settings(),
        credential_ref="credref:runpod",
        credential_resolver=lambda _ref: "fixture-dummy-value",
        attestation=_attestation(),
        now=clock.now,
        reservation_guard=lambda *_a, **_k: None,
        cleanup_guard=lambda *_o, **_k: None,
        absent_pod_ownership_probe=durable_pod_ownership_probe(
            db, owned_tag=TAG, provider_account_ref=ACCOUNT
        ),
        transport=transport,
    )
    lease, _reservation, _account = _seed_terminated_lease(db)
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO pod_storage_ownership (id, provider, pod_id, owner_episode_id, "
            "valid_from, valid_until, creating_lease_id) VALUES (%s, 'runpod', %s, "
            "(SELECT owner_episode_id FROM pod_leases WHERE id=%s), %s, %s, %s)",
            (uuid.uuid4(), POD, lease, WINDOW_START, WINDOW_END, lease),
        )
    first = _janitor(db, provider, now=clock.now(), seq="bs4-e2e-1").sweep()
    del first  # the early sweep is paced; its exact outcome is asserted per-case above
    clock.advance(ms=110 * 60 * 1000)
    second = _janitor(db, provider, now=clock.now(), seq="bs4-e2e-2").sweep()
    assert any(a.outcome == "INGESTED" for a in second.billing_ingests)
    # The operator's period invoice matches, and the finality sweep settles BILLED.
    settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    budget = BudgetService(db, clock, SequentialIds("bs4-e2e-inv"), settings)
    finality = RunpodInvoiceFinality(db, budget_service=budget)
    result = finality.verify_invoice_period(
        provider_account_ref=ACCOUNT,
        pod_id=POD,
        period_start=WINDOW_START,
        period_end=WINDOW_END,
        amount_micro_usd=70_000,
        currency="USD",
        evidence_sha256="e" * 64,
        source="INVOICE",
        observed_at=clock.now(),
    )
    assert result.outcome == "MATCHED"
    settled = finality.settle_lease(
        db,
        budget,
        settings,
        lease_id=lease,
        context="bs4 e2e",
        now=clock.now(),
    )
    assert settled.settled_micro_usd == 50_000  # the GPU bucket
    with db.transaction(readonly=True) as tx:
        state = tx.fetchval(
            "SELECT r.state FROM reservations r JOIN pod_leases l ON l.reservation_id=r.id "
            "WHERE l.pod_id=%s",
            (POD,),
        )
    assert state == "SETTLED"


def _lease_id(db: Database) -> uuid.UUID:
    with db.transaction(readonly=True) as tx:
        return tx.fetchval("SELECT id FROM pod_leases WHERE pod_id=%s", (POD,))
