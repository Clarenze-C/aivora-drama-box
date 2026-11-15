"""T031 R5f (RR-T17, tool scope): the per-pod billing verification wrapper.

``tools/t031_billing_verify.py`` is a THIN wrapper over the existing
``RunpodInvoiceFinality.verify_invoice_period``: it resolves the provider
account from the experiment's durable authorization, hashes the operator's
console evidence file and stores/prints ONLY that sha, runs the real
verifier against a real database (no network), and stays idempotent on
replay. The runbook's step-14 procedure is exercised end-to-end offline:
the EXISTING per-pod billing ingest records one settled bucket, then the
tool verifies the period (MATCH on the true sum, MISMATCH on a wrong one -
the period row only). The admission side of RR-T17 (another acquisition
refused while canonical billing/storage blockers are uncleared) is H-2's
own behaviour, covered by the H2B suites.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "budget"))

import t031_billing_verify as billing_verify  # noqa: E402
from t045_support import T0, closed_bucket, insert_runpod_lease  # noqa: E402

from microdrama.persistence.db import jsonb  # noqa: E402

pytestmark = pytest.mark.db

EVIDENCE = b"runpod-console-invoice-evidence-pdf-bytes-r5f"
EXPERIMENT = UUID("11111111-2222-3333-4444-666666666666")
ACCOUNT_REF = "acct:drama-box-t031"
HOUR = timedelta(hours=1)
#: One settled GPU bucket of 600_000 micro-USD over the verified period.
BUCKET_MICRO_USD = 600_000
PERIOD = (T0.isoformat(), (T0 + HOUR).isoformat())
OBSERVED_AT = (T0 + 2 * HOUR).isoformat()


def _seed_experiment_with_authorization(
    db, *, experiment_id: UUID = EXPERIMENT, account_ref: str = ACCOUNT_REF
) -> UUID:
    """One experiment row plus its durable authorization payload (the account
    the verifier bills) and the episode the per-pod lease hangs from."""
    from microdrama.testing.seed import seed_episode, seed_season

    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season, number=3)
        account = uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, "
            "cap_micro_usd) VALUES (%s,'EPISODE',%s,%s,10000000)",
            (account, season, episode),
        )
        for category, allocated, protected in (
            ("RESEARCH_SCRIPT_PROMPTS_METADATA", 0, True),
            ("REFERENCES_DIALOGUE", 0, True),
            ("QA_CAPTIONS", 0, True),
            ("CPU_STORAGE_TRANSFER", 0, True),
            ("RECOVERY_HEADROOM", 0, True),
            ("GPU_GENERATION", 9_000_000, True),
            ("METERED_MANAGEMENT", 0, False),
        ):
            tx.execute(
                "INSERT INTO budget_category_allocations (account_id, category, "
                "allocated_micro_usd, protected) VALUES (%s,%s,%s,%s)",
                (account, category, allocated, protected),
            )
        tx.execute(
            "INSERT INTO benchmark_experiments(experiment_id,episode_id,account_id,"
            "plan_sha256,plan,cap_micro_usd,gpu_limit_ms) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                experiment_id,
                episode,
                account,
                "a" * 64,
                jsonb({"schema_version": 1}),
                8_000_000,
                14_400_000,
            ),
        )
        payload = {
            "schema_version": 1,
            "operator": "operator@aivora",
            "change_ref": "t031-r5f",
            "experiment_id": str(experiment_id),
            "plan_sha256": "a" * 64,
            "sealed_sha256": "b" * 64,
            "episode_id": str(episode),
            "provider_account_ref": account_ref,
            "max_new_exposure_micro_usd": 8_000_000,
            "max_gpu_ms": 14_400_000,
            "hard_stop_utc": "2026-11-30T00:00:00+00:00",
            "allowed_gpu_types": ["NVIDIA A40"],
            "minimum_host_ram_gb": 64,
            "max_hourly_micro_usd": 860_000,
            "max_storage_exposure_micro_usd": 2_000_000,
            "container_disk_gb": 100,
            "persistent_volume_gb": 0,
            "shutdown_reserve_micro_usd": 500_000,
            "namespace": "t031bench",
            "runpod_credential_ref": "credref:runpod-t031",
            "comfy_credential_ref": "credref:comfy-t031",
            "rights_evidence_hash": "c" * 64,
        }
        tx.execute(
            "INSERT INTO benchmark_authorizations(experiment_id,authorization_sha256,"
            "payload,source_bytes,authorized_at) VALUES(%s,%s,%s,%s,%s)",
            (
                experiment_id,
                "d" * 64,
                jsonb(payload),
                json.dumps(payload).encode(),
                datetime.now(UTC),
            ),
        )
    return episode


def _link_acquisition(db, episode_id: UUID, lease_id: UUID, *, experiment_id: UUID = EXPERIMENT):
    """R5V-6: the experiment's acquisition (generation 1) owning the pod's
    lease, admitted under the seeded authorization."""
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO benchmark_acquisitions(acquisition_id,experiment_id,generation,"
            "quote,quote_sha256,intent,state,create_intent_at,authorization_sha256,lease_id) "
            "VALUES(%s,%s,1,%s,%s,%s,'CLOSED',%s,%s,%s)",
            (
                uuid4(),
                experiment_id,
                jsonb({"schema_version": 1}),
                "f" * 64,
                jsonb({"schema_version": 1}),
                T0,
                "d" * 64,
                lease_id,
            ),
        )


def _ingest_pod_billing(db, episode_id: UUID, *, pod_id: str) -> None:
    """Runbook §7 step 14(a): the EXISTING per-pod billing ingest records one
    settled provider bucket for the pod's period."""
    from microdrama.budget import BudgetService
    from microdrama.budget.billing import BillingRepository
    from microdrama.config import Settings
    from microdrama.contracts.enums import ExecutionMode
    from microdrama.core.clock import SystemClock, UuidIds

    with db.transaction() as tx:
        lease_id, _reservation = insert_runpod_lease(
            tx,
            episode_id,
            pod_id=pod_id,
            lease_state="RELEASED",
            pod_state="TERMINATED",
            create_requested_at=T0,
            compute_window_start_at=T0,
            compute_window_end_at=T0 + HOUR,
            stop_verified_at=T0 + HOUR,
            terminate_verified_at=T0 + HOUR,
        )
    settings = Settings(
        execution_mode=ExecutionMode.PAID_BENCHMARK,
        paid_requests_enabled=True,
        cloud_resources_enabled=True,
    )
    repository = BillingRepository(
        db, budget_service=BudgetService(db, SystemClock(), UuidIds(), settings)
    )
    query, bucket = closed_bucket(
        pod_id=pod_id,
        start=T0,
        end=T0 + HOUR,
        gpu=BUCKET_MICRO_USD,
        cpu=0,
        disk=0,
        account_ref=ACCOUNT_REF,
    )
    repository.ingest(query, [bucket])
    return lease_id


def _run(db_dsn: str, tmp_path: Path, *, amount: int, pod_id: str = "pod-r5f-1") -> int:
    evidence = tmp_path / "console-evidence.json"
    evidence.write_bytes(EVIDENCE)
    return billing_verify.main(
        [
            "--dsn",
            db_dsn,
            "--experiment-id",
            str(EXPERIMENT),
            "--pod-id",
            pod_id,
            "--period-start",
            PERIOD[0],
            "--period-end",
            PERIOD[1],
            "--amount-micro-usd",
            str(amount),
            "--evidence",
            str(evidence),
            "--observed-at",
            OBSERVED_AT,
        ]
    )


def test_rr_t17_matched_period_stores_only_the_evidence_sha(db, db_dsn, tmp_path, capsys) -> None:
    episode = _seed_experiment_with_authorization(db)
    lease_id = _ingest_pod_billing(db, episode, pod_id="pod-r5f-1")
    _link_acquisition(db, episode, lease_id)
    assert _run(db_dsn, tmp_path, amount=BUCKET_MICRO_USD) == 0
    matched = json.loads(capsys.readouterr().out)
    assert matched["outcome"] == "MATCHED"
    assert matched["bucket_sum_micro_usd"] == BUCKET_MICRO_USD
    sha = hashlib.sha256(EVIDENCE).hexdigest()
    assert matched["evidence_sha256"] == sha

    with db.transaction(readonly=True) as tx:
        rows = tx.fetchall(
            "SELECT provider_account_ref, evidence_sha256, evidence_source, outcome, "
            "bucket_sum_micro_usd FROM runpod_billing_period_evidence "
            "WHERE pod_id=%s",
            ("pod-r5f-1",),
        )
    assert len(rows) == 1
    assert rows[0]["provider_account_ref"] == ACCOUNT_REF
    assert rows[0]["evidence_sha256"] == sha
    assert rows[0]["outcome"] == "MATCHED"
    # ONLY the sha is stored: the evidence bytes appear in no column, and the
    # printed output never carries them either.
    for row in rows:
        for value in row.values():
            assert not (isinstance(value, str) and EVIDENCE in value.encode())
    assert EVIDENCE.decode() not in json.dumps(matched)

    # Replay with the identical evidence is idempotent.
    assert _run(db_dsn, tmp_path, amount=BUCKET_MICRO_USD) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["outcome"] == "MATCHED" and replay["replayed"] is True
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT count(*) FROM runpod_billing_period_evidence WHERE pod_id=%s",
                ("pod-r5f-1",),
            )
            == 1
        )


def test_rr_t17_wrong_amount_is_a_loud_mismatch(db, db_dsn, tmp_path, capsys) -> None:
    episode = _seed_experiment_with_authorization(db)
    lease_id = _ingest_pod_billing(db, episode, pod_id="pod-r5f-2")
    _link_acquisition(db, episode, lease_id)
    assert _run(db_dsn, tmp_path, amount=BUCKET_MICRO_USD + 1, pod_id="pod-r5f-2") == 1
    mismatch = json.loads(capsys.readouterr().out)
    assert mismatch["outcome"] == "MISMATCHED"
    with db.transaction(readonly=True) as tx:
        assert (
            tx.fetchval(
                "SELECT count(*) FROM runpod_billing_period_evidence WHERE pod_id=%s "
                "AND outcome='MISMATCHED'",
                ("pod-r5f-2",),
            )
            == 1
        )


def test_rr_t17_refuses_without_authorization_or_evidence(db, db_dsn, tmp_path) -> None:
    episode = _seed_experiment_with_authorization(db)
    # The probe pod is this experiment's own acquisition pod, so the refusals
    # below exercise the AUTHORIZATION/evidence/verifier checks - provenance
    # (R5V-6) is satisfied here.
    with db.transaction() as tx:
        lease_id, _reservation = insert_runpod_lease(tx, episode, pod_id="pod-r5f-x")
    _link_acquisition(db, episode, lease_id)
    evidence = tmp_path / "console-evidence.json"
    evidence.write_bytes(EVIDENCE)

    def argv(experiment: str, evidence_path: Path, *, period_end: str | None = None):
        return [
            "--dsn",
            db_dsn,
            "--experiment-id",
            experiment,
            "--pod-id",
            "pod-r5f-x",
            "--period-start",
            PERIOD[0],
            "--period-end",
            period_end or PERIOD[1],
            "--amount-micro-usd",
            "1",
            "--evidence",
            str(evidence_path),
            "--observed-at",
            OBSERVED_AT,
        ]

    # An experiment with no durable authorization cannot name the account.
    with pytest.raises(SystemExit, match="no durable authorization|not an acquisition pod"):
        billing_verify.main(argv(str(uuid4()), evidence))
    # A missing evidence file never reaches the verifier.
    with pytest.raises(SystemExit, match="evidence file is missing"):
        billing_verify.main(argv(str(EXPERIMENT), tmp_path / "absent.json"))
    # An empty period is refused by the verifier's own schema checks.
    assert billing_verify.main(argv(str(EXPERIMENT), evidence, period_end=PERIOD[0])) == 2


# ---------------------------------------------------------------------------
# R5V-6 - acquisition-specific provenance
# ---------------------------------------------------------------------------


def test_r5v6_foreign_pod_refused(db, db_dsn, tmp_path) -> None:
    """A pod that belongs to ANOTHER experiment's acquisition is refused: the
    tool resolves experiment -> target pod/lease -> acquisition before the
    verifier, so it can never bill a foreign pod from this experiment's
    provenance."""
    episode = _seed_experiment_with_authorization(db)
    lease_id = _ingest_pod_billing(db, episode, pod_id="pod-r5f-1")
    _link_acquisition(db, episode, lease_id)

    other = uuid4()
    other_episode = _seed_experiment_with_authorization(db, experiment_id=other)
    other_lease = _ingest_pod_billing(db, other_episode, pod_id="pod-foreign-1")
    _link_acquisition(db, other_episode, other_lease, experiment_id=other)

    evidence = tmp_path / "console-evidence.json"
    evidence.write_bytes(EVIDENCE)
    with pytest.raises(SystemExit, match="not an acquisition pod of this experiment"):
        billing_verify.main(
            [
                "--dsn",
                db_dsn,
                "--experiment-id",
                str(EXPERIMENT),
                "--pod-id",
                "pod-foreign-1",
                "--period-start",
                PERIOD[0],
                "--period-end",
                PERIOD[1],
                "--amount-micro-usd",
                str(BUCKET_MICRO_USD),
                "--evidence",
                str(evidence),
                "--observed-at",
                OBSERVED_AT,
            ]
        )


def test_r5v6_uses_the_target_acquisitions_own_authorization(db, db_dsn, tmp_path, capsys) -> None:
    """A NEWER experiment authorization with a different provider account
    never overrides the TARGET acquisition's original admission authorization
    (R5C-7: the billed account is the acquisition's own provenance)."""
    episode = _seed_experiment_with_authorization(db)
    lease_id = _ingest_pod_billing(db, episode, pod_id="pod-r5f-3")
    _link_acquisition(db, episode, lease_id)

    # A later authorization row for the SAME experiment names a DIFFERENT
    # account; the pod's acquisition was admitted under the ORIGINAL.
    newer = {
        "schema_version": 1,
        "operator": "operator@aivora",
        "change_ref": "t031-r5f-rotated",
        "experiment_id": str(EXPERIMENT),
        "plan_sha256": "a" * 64,
        "sealed_sha256": "b" * 64,
        "episode_id": str(episode),
        "provider_account_ref": "acct:drama-box-t031-ROTATED",
        "max_new_exposure_micro_usd": 8_000_000,
        "max_gpu_ms": 14_400_000,
        "hard_stop_utc": "2026-12-31T00:00:00+00:00",
        "allowed_gpu_types": ["NVIDIA A40"],
        "minimum_host_ram_gb": 64,
        "max_hourly_micro_usd": 860_000,
        "max_storage_exposure_micro_usd": 2_000_000,
        "container_disk_gb": 100,
        "persistent_volume_gb": 0,
        "shutdown_reserve_micro_usd": 500_000,
        "namespace": "t031bench",
        "runpod_credential_ref": "credref:runpod-t031",
        "comfy_credential_ref": "credref:comfy-t031",
        "rights_evidence_hash": "c" * 64,
    }
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO benchmark_authorizations(experiment_id,authorization_sha256,"
            "payload,source_bytes,authorized_at) VALUES(%s,%s,%s,%s,%s)",
            (
                EXPERIMENT,
                "e" * 64,
                jsonb(newer),
                json.dumps(newer).encode(),
                datetime.now(UTC) + timedelta(minutes=1),
            ),
        )

    assert _run(db_dsn, tmp_path, amount=BUCKET_MICRO_USD, pod_id="pod-r5f-3") == 0
    matched = json.loads(capsys.readouterr().out)
    assert matched["outcome"] == "MATCHED", matched
    with db.transaction(readonly=True) as tx:
        stored = tx.fetchval(
            "SELECT provider_account_ref FROM runpod_billing_period_evidence WHERE pod_id=%s",
            ("pod-r5f-3",),
        )
    assert stored == ACCOUNT_REF, "the acquisition's ORIGINAL account was billed"
