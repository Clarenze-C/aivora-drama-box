"""Database-level invariants every lane relies on (T003 acceptance + SPEC §4.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from microdrama.contracts.errors import (
    Conflict,
    DuplicateSemanticKey,
    StaleRevision,
    Unauthorized,
)
from microdrama.contracts.hashing import canonical_hash
from microdrama.persistence import Database, Tx, insert_row, jsonb, update_with_revision
from microdrama.testing.seed import (
    seed_episode,
    seed_human_session,
    seed_job,
    seed_owner,
    seed_season,
)

pytestmark = pytest.mark.db
H = canonical_hash({"x": 1})
T0 = datetime(2026, 10, 20, tzinfo=UTC)


def _approval(
    tx: Tx,
    owner_id,
    session_id,
    *,
    entity_id=None,
    revision=1,
    action="APPROVE",
    gate="SEASON_CONCEPT",
    **extra,
):
    values = {
        "id": uuid.uuid4(),
        "gate_type": gate,
        "action": action,
        "entity_type": "season" if gate == "SEASON_CONCEPT" else "episode",
        "entity_id": entity_id or uuid.uuid4(),
        "expected_revision": revision,
        "package_hash": H,
        "actor_owner_id": owner_id,
        "actor_session_id": session_id,
        "idempotency_key": f"idem-{uuid.uuid4().hex}",
        "command_hash": H,
    }
    values.update(extra)
    return insert_row(tx, "approval_events", values)


def test_duplicate_semantic_job_rejected(db: Database) -> None:
    with db.transaction() as tx:
        seed_job(tx, semantic_key="qa.technical:ep1:cycle1")
    with pytest.raises(DuplicateSemanticKey) as err, db.transaction() as tx:
        seed_job(tx, semantic_key="qa.technical:ep1:cycle1")
    assert err.value.details["constraint"] == "jobs_semantic_key_key"


def test_job_identity_is_immutable(db: Database) -> None:
    with db.transaction() as tx:
        job_id = seed_job(tx, semantic_key="k:immutable")
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute("UPDATE jobs SET input = '{}'::jsonb WHERE id = %s", (job_id,))


def test_running_job_requires_lease(db: Database) -> None:
    with db.transaction() as tx:
        job_id = seed_job(tx, semantic_key="k:lease")
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute("UPDATE jobs SET status = 'RUNNING' WHERE id = %s", (job_id,))


def test_optimistic_revision_rejects_stale_writer(db: Database) -> None:
    with db.transaction() as tx:
        season_id = seed_season(tx)
    with db.transaction() as tx:
        update_with_revision(tx, "seasons", season_id, 0, {"title_en": "first"})
    with pytest.raises(StaleRevision), db.transaction() as tx:
        update_with_revision(tx, "seasons", season_id, 0, {"title_en": "stale"})


class TestApprovalEvents:
    def test_live_human_session_can_record(self, db: Database) -> None:
        with db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
            _approval(tx, owner, session)

    @pytest.mark.parametrize(
        "problem", ["revoked", "expired", "other_owner", "inactive_owner", "no_session"]
    )
    def test_without_live_human_session_is_refused(self, db: Database, problem: str) -> None:
        with db.transaction() as tx:
            owner = seed_owner(tx, active=problem != "inactive_owner")
            other = seed_owner(tx)
            session = seed_human_session(
                tx,
                other if problem == "other_owner" else owner,
                revoked=problem == "revoked",
                expires_in=timedelta(seconds=1),
                created_at=datetime.now(UTC) - timedelta(hours=1) if problem == "expired" else None,
            )
        with pytest.raises(Unauthorized), db.transaction() as tx:
            _approval(tx, owner, uuid.uuid4() if problem == "no_session" else session)

    def test_append_only(self, db: Database) -> None:
        with db.transaction() as tx:
            owner = seed_owner(tx)
            row = _approval(tx, owner, seed_human_session(tx, owner))
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute("UPDATE approval_events SET action = 'REJECT' WHERE id = %s", (row["id"],))
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute("DELETE FROM approval_events WHERE id = %s", (row["id"],))

    def test_one_decision_per_entity_revision(self, db: Database) -> None:
        entity = uuid.uuid4()
        with db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
            _approval(tx, owner, session, entity_id=entity, revision=4)
        with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
            _approval(tx, owner, session, entity_id=entity, revision=4, action="REJECT")

    def test_gate2_approval_must_bind_media_policy_scope(self, db: Database) -> None:
        with db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
        with pytest.raises(Conflict), db.transaction() as tx:
            _approval(tx, owner, session, gate="EPISODE_FINAL")
        with db.transaction() as tx:
            _approval(
                tx,
                owner,
                session,
                gate="EPISODE_FINAL",
                media_hashes=jsonb([H]),
                management_policy_hash=H,
                release_scope_hash=H,
            )

    def test_gate1_cannot_revise(self, db: Database) -> None:
        with db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(tx, owner)
        with pytest.raises(Conflict), db.transaction() as tx:
            _approval(tx, owner, session, action="REVISE", feedback=jsonb([{"c": 1}]))


def _account(tx: Tx, *, cap: int = 10_000_000) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    season = seed_season(tx)
    episode = seed_episode(tx, season)
    account = uuid.uuid4()
    tx.execute(
        "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) VALUES (%s,'EPISODE',%s,%s,%s)",
        (account, season, episode, cap),
    )
    return account, season, episode


class TestBudgetBackstops:
    def test_outstanding_plus_spent_cannot_exceed_cap(self, db: Database) -> None:
        with db.transaction() as tx:
            account, _, _ = _account(tx)
        with db.transaction() as tx:
            tx.execute(
                "UPDATE budget_accounts SET reserved_outstanding_micro_usd = 6000000, settled_micro_usd = 4000000 WHERE id = %s",
                (account,),
            )
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute("UPDATE budget_accounts SET accrued_micro_usd = 1 WHERE id = %s", (account,))

    def test_overrun_must_be_recorded_and_blocks_dispatch(self, db: Database) -> None:
        with db.transaction() as tx:
            account, _, _ = _account(tx)
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute(
                "UPDATE budget_accounts SET settled_micro_usd = 10500000, overrun_micro_usd = 500000 WHERE id = %s",
                (account,),
            )
        with db.transaction() as tx:
            tx.execute(
                "UPDATE budget_accounts SET settled_micro_usd = 10500000, overrun_micro_usd = 500000, "
                "paid_dispatch_blocked = true, blocked_reason = 'observed overrun' WHERE id = %s",
                (account,),
            )

    def test_cap_cannot_exceed_ten_dollars_or_change(self, db: Database) -> None:
        with pytest.raises(Conflict), db.transaction() as tx:
            _account(tx, cap=10_000_001)
        with db.transaction() as tx:
            account, _, _ = _account(tx)
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute(
                "UPDATE budget_accounts SET cap_micro_usd = 5000000 WHERE id = %s", (account,)
            )

    def test_receipts_dedupe_and_fake_labelling(self, db: Database) -> None:
        with db.transaction() as tx:
            account, _, _ = _account(tx)

        def charge(
            tx: Tx, receipt: str, basis: str = "SYNTHETIC_FAKE", provenance: str = "FAKE_SYNTHETIC"
        ) -> None:
            insert_row(
                tx,
                "charges",
                {
                    "id": uuid.uuid4(),
                    "account_id": account,
                    "receipt_id": uuid.uuid4(),
                    "provider": "fake",
                    "provider_receipt_id": receipt,
                    "kind": "SETTLEMENT",
                    "cost_basis": basis,
                    "provenance": provenance,
                    "category": "GPU_GENERATION",
                    "amount_micro_usd": 10,
                    "units": 1,
                    "unit": "GPU_SECOND",
                    "observed_at": T0,
                    "receipt": jsonb({}),
                },
            )

        with db.transaction() as tx:
            charge(tx, "r-1")
        with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
            charge(tx, "r-1")
        with pytest.raises(Conflict), db.transaction() as tx:
            charge(tx, "r-2", basis="BILLED", provenance="FAKE_SYNTHETIC")
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute("UPDATE charges SET amount_micro_usd = 0")


class TestGpuLeases:
    def _lease(self, tx: Tx, episode, account, state: str = "ACTIVE") -> uuid.UUID:
        reservation = uuid.uuid4()
        insert_row(
            tx,
            "reservations",
            {
                "id": reservation,
                "account_id": account,
                "request_id": uuid.uuid4(),
                "semantic_key": f"gpu:{reservation}",
                "request_hash": H,
                "category": "GPU_GENERATION",
                "queue": "production",
                "provider": "fake-runpod",
                "operation_kind": "pod",
                "price": jsonb({}),
                "ceilings": jsonb({}),
                "reserved_micro_usd": 100,
                "state": "ACTIVE",
                "expires_at": T0 + timedelta(hours=1),
            },
        )
        lease = uuid.uuid4()
        insert_row(
            tx,
            "pod_leases",
            {
                "id": lease,
                "provider": "fake-runpod",
                "pod_id": f"pod-{lease.hex[:6]}",
                "owned_tag": "md-owned",
                "client_token": f"lease-{lease}",
                "owner_episode_id": episode,
                "reservation_id": reservation,
                "lease_state": state,
                "pod_state": "RUNNING",
                "gpu_type": "FAKE",
                "hourly_price_micro_usd": 900000,
                "lease_expires_at": T0 + timedelta(minutes=20),
            },
        )
        return lease

    def test_only_one_live_gpu_lease_in_pilot(self, db: Database) -> None:
        with db.transaction() as tx:
            account, season, episode = _account(tx)
            first = self._lease(tx, episode, account)
        with db.transaction() as tx:
            other_episode = seed_episode(tx, season, number=2)
            other_account = uuid.uuid4()
            tx.execute(
                "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) VALUES (%s,'EPISODE',%s,%s,10000000)",
                (other_account, season, other_episode),
            )
        with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
            self._lease(tx, other_episode, other_account)
        with db.transaction() as tx:  # sequential transfer: release first, then claim
            tx.execute("UPDATE pod_leases SET lease_state = 'RELEASED' WHERE id = %s", (first,))
            self._lease(tx, other_episode, other_account)

    def test_gpu_interval_billed_once(self, db: Database) -> None:
        with db.transaction() as tx:
            account, _, episode = _account(tx)
            lease = self._lease(tx, episode, account)
            pod_id = tx.fetchval("SELECT pod_id FROM pod_leases WHERE id = %s", (lease,))

        def interval(tx: Tx, start_min: int, end_min: int) -> None:
            insert_row(
                tx,
                "pod_usage_intervals",
                {
                    "id": uuid.uuid4(),
                    "provider": "fake-runpod",
                    "pod_id": pod_id,
                    "lease_id": lease,
                    "account_id": account,
                    "interval_start": T0 + timedelta(minutes=start_min),
                    "interval_end": T0 + timedelta(minutes=end_min),
                    "basis": "RUNNING",
                    "amount_micro_usd": 1,
                },
            )

        with db.transaction() as tx:
            interval(tx, 0, 10)
            interval(tx, 10, 20)  # adjacent is fine
        with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
            interval(tx, 5, 15)  # overlap would double-count


def _post(tx: Tx, *, slot: str = "full", dedupe: str | None = None) -> None:
    owner = seed_owner(tx)
    session = seed_human_session(tx, owner)
    season = seed_season(tx)
    episode = seed_episode(tx, season)
    approval = _approval(
        tx,
        owner,
        session,
        gate="EPISODE_FINAL",
        entity_id=episode,
        media_hashes=jsonb([H]),
        management_policy_hash=H,
        release_scope_hash=H,
    )
    package = insert_row(
        tx,
        "release_packages",
        {
            "id": uuid.uuid4(),
            "episode_id": episode,
            "version": 1,
            "package_hash": canonical_hash({"p": str(episode)}),
            "body": jsonb({}),
            "media_hashes": jsonb([H]),
            "management_policy_hash": H,
            "release_scope_hash": H,
            "status": "APPROVED",
            "approval_event_id": approval["id"],
        },
    )
    asset = insert_row(
        tx,
        "assets",
        {
            "id": uuid.uuid4(),
            "asset_kind": "OTHER",
            "object_key": f"k/{uuid.uuid4().hex}",
            "sha256": H,
            "size_bytes": 1,
            "media_type": "application/octet-stream",
            "state": "ACCEPTED",
            "provenance": "FAKE_SYNTHETIC",
            "descriptor": jsonb({}),
        },
    )
    return season, episode, package["id"], approval["id"], asset["id"]


class TestPublicationSlots:
    def test_duplicate_slot_rejected(self, db: Database) -> None:
        with db.transaction() as tx:
            season, episode, package, approval, asset = _post(tx)

        def slot(tx: Tx, dedupe: str, token: str) -> None:
            insert_row(
                tx,
                "platform_posts",
                {
                    "id": uuid.uuid4(),
                    "series_id": season,
                    "episode_id": episode,
                    "part": 0,
                    "locale": "th-TH",
                    "platform": "YOUTUBE",
                    "account_ref": "acct:yt",
                    "release_slot": "full",
                    "dedupe_key": dedupe,
                    "slot_kind": "FULL_EPISODE",
                    "required": True,
                    "release_package_id": package,
                    "approval_event_id": approval,
                    "asset_id": asset,
                    "asset_sha256": H,
                    "state": "SCHEDULED",
                    "iana_zone": "Asia/Bangkok",
                    "local_time": "2026-10-27T19:30:00",
                    "scheduled_utc": T0,
                    "client_token": token,
                },
            )

        with db.transaction() as tx:
            slot(tx, canonical_hash({"slot": 1}), "tok-1")
        # Same SPEC slot tuple, even with a different dedupe key/token, is rejected.
        with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
            slot(tx, canonical_hash({"slot": 2}), "tok-2")

    def test_only_one_approved_package_per_episode(self, db: Database) -> None:
        with db.transaction() as tx:
            _, episode, _, approval, _ = _post(tx)
        with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
            insert_row(
                tx,
                "release_packages",
                {
                    "id": uuid.uuid4(),
                    "episode_id": episode,
                    "version": 2,
                    "package_hash": canonical_hash({"v": 2}),
                    "body": jsonb({}),
                    "media_hashes": jsonb([H]),
                    "management_policy_hash": H,
                    "release_scope_hash": H,
                    "status": "APPROVED",
                    "approval_event_id": approval,
                },
            )


def test_qa_observations_are_immutable_and_findings_cannot_fake_pass(db: Database) -> None:
    with db.transaction() as tx:
        episode = seed_episode(tx, seed_season(tx))
        obs = insert_row(
            tx,
            "qa_observations",
            {
                "id": uuid.uuid4(),
                "episode_id": episode,
                "request_id": uuid.uuid4(),
                "request_sha256": H,
                "media_sha256": jsonb([H]),
                "report": jsonb({}),
                "report_sha256": H,
                "provenance": "FAKE_SYNTHETIC",
                "frozen_at": T0,
            },
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute(
            "UPDATE qa_observations SET report = '{\"agree\": true}'::jsonb WHERE id = %s",
            (obs["id"],),
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        insert_row(
            tx,
            "qa_findings",
            {
                "id": uuid.uuid4(),
                "episode_id": episode,
                "qa_cycle": 1,
                "asset_id": uuid.uuid4(),
                "start_ms": 0,
                "end_ms": 10,
                "check_id": "temporal.lip_sync",
                "check_family": "TEMPORAL",
                "source_pass": "TECHNICAL",
                "severity": "CRITICAL",
                "coverage": "UNSAMPLED",
                "outcome": "PASS",
                "body": jsonb({}),
            },
        )


def test_membership_catalog_truthfulness(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
        episode = seed_episode(tx, season)

    def entry(tx: Tx, **extra) -> None:
        values = {
            "id": uuid.uuid4(),
            "season_id": season,
            "episode_id": episode,
            "catalog_version": extra.pop("v", 1),
            "public_state": "EARLY_ACCESS_MEMBERS",
            "media_finished_and_approved": False,
            "body": jsonb({}),
            "current": False,
        }
        values.update(extra)
        insert_row(tx, "membership_catalog", values)

    with pytest.raises(Conflict), db.transaction() as tx:
        entry(tx)  # unapproved media sold as early access
    with pytest.raises(Conflict), db.transaction() as tx:
        entry(tx, public_state="PUBLIC_FREE", public_url="https://x.fake.invalid/e?token=abc", v=2)


def test_series_preference_requires_explicit_scope(db: Database) -> None:
    with db.transaction() as tx:
        season = seed_season(tx)
    with pytest.raises(Conflict), db.transaction() as tx:
        insert_row(
            tx,
            "preference_rules",
            {
                "id": uuid.uuid4(),
                "season_id": season,
                "rule_key": "subtitle-style",
                "version": 1,
                "scope": "SERIES",
                "category": "subtitles",
                "instruction": "always use yellow",
                "state": "ACTIVE",
            },
        )
