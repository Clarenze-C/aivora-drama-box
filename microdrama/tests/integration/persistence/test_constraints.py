"""Database-level invariants every lane relies on (T003 acceptance + SPEC §4.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from microdrama.contracts.errors import (
    Conflict,
    DuplicateSemanticKey,
    SchemaInvalid,
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


def _asset(tx: Tx, *, sha: str = H) -> uuid.UUID:
    asset_id = uuid.uuid4()
    key = f"k/{asset_id.hex}"
    insert_row(
        tx,
        "assets",
        {
            "id": asset_id,
            "asset_kind": "OTHER",
            "object_key": key,
            "sha256": sha,
            "size_bytes": 1,
            "media_type": "application/octet-stream",
            "state": "ACCEPTED",
            "provenance": "FAKE_SYNTHETIC",
            "descriptor": jsonb({"asset_id": str(asset_id), "sha256": sha, "object_key": key}),
        },
    )
    return asset_id


def _package(
    tx: Tx, episode: uuid.UUID, *, version: int = 1, status: str = "READY"
) -> tuple[uuid.UUID, str]:
    package_id = uuid.uuid4()
    package_hash = canonical_hash({"p": str(episode), "v": version})
    insert_row(
        tx,
        "release_packages",
        {
            "id": package_id,
            "episode_id": episode,
            "version": version,
            "package_hash": package_hash,
            "body": jsonb({}),
            "media_hashes": jsonb([H]),
            "management_policy_hash": H,
            "release_scope_hash": H,
            "status": status,
            "gate_blockers": jsonb(["blocked for test"] if status == "BLOCKED" else []),
        },
    )
    return package_id, package_hash


def _gate2(
    tx: Tx,
    episode: uuid.UUID,
    package_hash: str,
    *,
    revision: int = 1,
    action: str = "APPROVE",
    **extra,
):
    owner = seed_owner(tx)
    session = seed_human_session(tx, owner)
    values = dict(media_hashes=jsonb([H]), management_policy_hash=H, release_scope_hash=H)
    if action == "REVISE":
        values["feedback"] = jsonb([{"category": "pacing"}])
    values.update(extra)
    return _approval(
        tx,
        owner,
        session,
        gate="EPISODE_FINAL",
        action=action,
        entity_id=episode,
        revision=revision,
        package_hash=package_hash,
        **values,
    )["id"]


def _approve_package(tx: Tx, package_id: uuid.UUID, approval_id: uuid.UUID) -> None:
    tx.execute(
        "UPDATE release_packages SET status = 'APPROVED', approval_event_id = %s WHERE id = %s",
        (approval_id, package_id),
    )


def _post(tx: Tx):
    season = seed_season(tx)
    episode = seed_episode(tx, season)
    package_id, package_hash = _package(tx, episode)
    approval = _gate2(tx, episode, package_hash)
    _approve_package(tx, package_id, approval)
    return season, episode, package_id, approval, _asset(tx)


def _slot(
    tx: Tx, season, episode, package, approval, asset, *, dedupe: str, token: str, sha: str = H
) -> None:
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
            "asset_sha256": sha,
            "state": "SCHEDULED",
            "iana_zone": "Asia/Bangkok",
            "local_time": "2026-10-27T19:30:00",
            "scheduled_utc": T0,
            "client_token": token,
        },
    )


class TestPublicationSlots:
    def test_duplicate_slot_rejected(self, db: Database) -> None:
        with db.transaction() as tx:
            ids = _post(tx)
        with db.transaction() as tx:
            _slot(tx, *ids, dedupe=canonical_hash({"slot": 1}), token="tok-1")
        # Same SPEC slot tuple, even with a different dedupe key/token, is rejected.
        with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
            _slot(tx, *ids, dedupe=canonical_hash({"slot": 2}), token="tok-2")

    def test_slot_hash_must_be_the_assets_hash(self, db: Database) -> None:  # V-10
        with db.transaction() as tx:
            ids = _post(tx)
        with pytest.raises(Conflict), db.transaction() as tx:
            _slot(tx, *ids, dedupe=canonical_hash({"slot": 3}), token="tok-3", sha="0" * 64)

    def test_only_one_approved_package_per_episode(self, db: Database) -> None:
        with db.transaction() as tx:
            _, episode, _, _, _ = _post(tx)
            package_v2, hash_v2 = _package(tx, episode, version=2)
            approval_v2 = _gate2(tx, episode, hash_v2, revision=2)
        with pytest.raises(DuplicateSemanticKey), db.transaction() as tx:
            _approve_package(tx, package_v2, approval_v2)


class TestReleasePackageBinding:  # V-3
    def test_cannot_insert_already_approved(self, db: Database) -> None:
        with db.transaction() as tx:
            episode = seed_episode(tx, seed_season(tx))
        with pytest.raises(Conflict), db.transaction() as tx:
            _package(tx, episode, status="APPROVED")

    def test_blocked_package_cannot_jump_to_approved(self, db: Database) -> None:
        with db.transaction() as tx:
            episode = seed_episode(tx, seed_season(tx))
            package_id, package_hash = _package(tx, episode, status="BLOCKED")
            approval = _gate2(tx, episode, package_hash)
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute(
                "UPDATE release_packages SET status='APPROVED', approval_event_id=%s, gate_blockers='[]'::jsonb "
                "WHERE id=%s",
                (approval, package_id),
            )

    @pytest.mark.parametrize(
        "mismatch", ["package_hash", "media", "policy", "scope", "entity", "action"]
    )
    def test_approval_must_match_the_package(self, db: Database, mismatch: str) -> None:
        with db.transaction() as tx:
            episode = seed_episode(tx, seed_season(tx))
            other_episode = seed_episode(tx, seed_season(tx))
            package_id, package_hash = _package(tx, episode)
            other = canonical_hash({"other": mismatch})
            kwargs = {
                "package_hash": dict(package_hash=other),
                "media": dict(media_hashes=jsonb([other])),
                "policy": dict(management_policy_hash=other),
                "scope": dict(release_scope_hash=other),
                "entity": {},
                "action": {},
            }[mismatch]
            target = other_episode if mismatch == "entity" else episode
            action = "REJECT" if mismatch == "action" else "APPROVE"
            ph = kwargs.pop("package_hash", package_hash)
            approval = _gate2(tx, target, ph, action=action, **kwargs)
        with pytest.raises(Unauthorized), db.transaction() as tx:
            _approve_package(tx, package_id, approval)

    def test_matching_approval_binds_and_cannot_be_rebound(self, db: Database) -> None:
        with db.transaction() as tx:
            _, episode, package_id, approval, _ = _post(tx)
            other_package, other_hash = _package(tx, episode, version=2)
            other_approval = _gate2(tx, episode, other_hash, revision=2)
        with pytest.raises(Conflict), db.transaction() as tx:
            tx.execute(
                "UPDATE release_packages SET approval_event_id=%s WHERE id=%s",
                (other_approval, package_id),
            )

    def test_episode_release_states_require_an_approved_package(self, db: Database) -> None:
        with db.transaction() as tx:
            episode = seed_episode(tx, seed_season(tx), state="AWAITING_FINAL_REVIEW")
            package_id, package_hash = _package(tx, episode)
        with pytest.raises(Unauthorized), db.transaction() as tx:
            tx.execute("UPDATE episodes SET state='RELEASE_APPROVED' WHERE id=%s", (episode,))
        with db.transaction() as tx:
            _approve_package(tx, package_id, _gate2(tx, episode, package_hash))
            tx.execute("UPDATE episodes SET state='RELEASE_APPROVED' WHERE id=%s", (episode,))


class TestApprovalBindingHardening:
    def test_backdated_created_at_cannot_revive_an_expired_session(
        self, db: Database
    ) -> None:  # V-1
        with db.transaction() as tx:
            owner = seed_owner(tx)
            session = seed_human_session(
                tx,
                owner,
                created_at=datetime.now(UTC) - timedelta(hours=3),
                expires_in=timedelta(hours=1),
            )
        with pytest.raises(Unauthorized), db.transaction() as tx:
            _approval(
                tx, owner, session, created_at=datetime.now(UTC) - timedelta(hours=2, minutes=30)
            )

    def test_recorded_time_is_server_time(self, db: Database) -> None:
        with db.transaction() as tx:
            owner = seed_owner(tx)
            row = _approval(
                tx,
                owner,
                seed_human_session(tx, owner),
                created_at=datetime(2001, 1, 1, tzinfo=UTC),
            )
        assert row["created_at"].year >= 2026

    def test_season_cannot_be_approved_with_a_dangling_or_mismatched_approval(
        self, db: Database
    ) -> None:  # V-2
        with db.transaction() as tx:
            season = seed_season(tx)
        scope = canonical_hash({"scope": 1})
        # The binding trigger refuses before the FK is even checked (both guard this).
        with pytest.raises(Unauthorized), db.transaction() as tx:
            tx.execute(
                "UPDATE seasons SET state='SEASON_APPROVED', approved_scope_hash=%s, approved_scope_version=1, "
                "approval_event_id=%s WHERE id=%s",
                (scope, uuid.uuid4(), season),
            )
        with db.transaction() as tx:
            owner = seed_owner(tx)
            wrong = _approval(
                tx,
                owner,
                seed_human_session(tx, owner),
                entity_id=season,
                package_hash=canonical_hash({"scope": "other"}),
            )
        with pytest.raises(Unauthorized), db.transaction() as tx:
            tx.execute(
                "UPDATE seasons SET state='SEASON_APPROVED', approved_scope_hash=%s, approved_scope_version=1, "
                "approval_event_id=%s WHERE id=%s",
                (scope, wrong["id"], season),
            )

    def test_seeded_approved_season_is_backed_by_a_real_gate1_event(self, db: Database) -> None:
        with db.transaction() as tx:
            season = seed_season(tx, state="SEASON_APPROVED")
            row = tx.fetchone(
                "SELECT a.gate_type, a.action, a.entity_id FROM seasons s "
                "JOIN approval_events a ON a.id = s.approval_event_id WHERE s.id = %s",
                (season,),
            )
        assert row == {"gate_type": "SEASON_CONCEPT", "action": "APPROVE", "entity_id": season}


@pytest.mark.parametrize(
    "table",
    [
        "approval_events",
        "charges",
        "policy_versions",
        "qualification_runs",
        "manual_interventions",
        "domain_events",
        "qa_observations",
    ],
)
def test_append_only_tables_refuse_truncate(db: Database, table: str) -> None:  # V-8
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute(f"TRUNCATE {table} CASCADE")


def test_asset_descriptor_is_immutable_and_consistent(db: Database) -> None:  # V-9
    with db.transaction() as tx:
        asset = _asset(tx)
    with pytest.raises(Conflict), db.transaction() as tx:
        tx.execute(
            "UPDATE assets SET descriptor = jsonb_set(descriptor, '{sha256}', '\"ffff\"') WHERE id=%s",
            (asset,),
        )
    with pytest.raises(Conflict), db.transaction() as tx:
        aid = uuid.uuid4()
        insert_row(
            tx,
            "assets",
            {
                "id": aid,
                "asset_kind": "OTHER",
                "object_key": "k/x",
                "sha256": H,
                "size_bytes": 1,
                "media_type": "x",
                "state": "ACCEPTED",
                "provenance": "FAKE_SYNTHETIC",
                "descriptor": jsonb(
                    {"asset_id": str(aid), "sha256": "f" * 64, "object_key": "k/x"}
                ),
            },
        )


def test_metered_action_cannot_execute_without_reservation(db: Database) -> None:  # V-11
    def action(tx: Tx, cost: int) -> None:
        insert_row(
            tx,
            "management_actions",
            {
                "id": uuid.uuid4(),
                "kind": "PUBLIC_REPLY",
                "platform": "TIKTOK",
                "account_ref": "acct:tt",
                "dedupe_key": f"reply:{uuid.uuid4().hex}",
                "body": jsonb({"estimated_cost_micro_usd": cost}),
                "policy_hash": H,
                "catalog_version": 1,
                "decision": "EXECUTED",
                "provenance": "FAKE_SYNTHETIC",
            },
        )

    with pytest.raises(Conflict), db.transaction() as tx:
        action(tx, 500)
    with db.transaction() as tx:
        action(tx, 0)  # template/fixed-quota actions with no metered cost are allowed
    with pytest.raises(Conflict), db.transaction() as tx:  # a missing estimate is not zero
        insert_row(
            tx,
            "management_actions",
            {
                "id": uuid.uuid4(),
                "kind": "PUBLIC_REPLY",
                "platform": "TIKTOK",
                "account_ref": "acct:tt",
                "dedupe_key": "reply:no-estimate",
                "body": jsonb({}),
                "policy_hash": H,
                "catalog_version": 1,
                "decision": "EXECUTED",
                "provenance": "FAKE_SYNTHETIC",
            },
        )


def test_enabled_preset_row_needs_a_measurement(db: Database) -> None:
    def preset(tx: Tx, record: dict) -> None:
        insert_row(
            tx,
            "preset_registry",
            {
                "id": uuid.uuid4(),
                "preset_id": f"p-{uuid.uuid4().hex[:6]}",
                "version": 1,
                "tier": "fast_four_step",
                "workflow_sha256": H,
                "record": jsonb(record),
                "enabled": True,
                "evidence": jsonb([{"source": "MEASURED_BENCHMARK", "ref": "bench:1"}]),
            },
        )

    with pytest.raises(Conflict), db.transaction() as tx:
        preset(tx, {})
    with db.transaction() as tx:
        preset(tx, {"measured": {"sample_count": 3}})


def test_float_bind_parameters_are_refused(db: Database) -> None:  # V-12
    with db.transaction() as tx:
        account_season = seed_season(tx)
        episode = seed_episode(tx, account_season)
        account = uuid.uuid4()
        tx.execute(
            "INSERT INTO budget_accounts (id, scope_kind, season_id, episode_id, cap_micro_usd) "
            "VALUES (%s,'EPISODE',%s,%s,10000000)",
            (account, account_season, episode),
        )
    with pytest.raises(SchemaInvalid), db.transaction() as tx:
        tx.execute(
            "UPDATE budget_accounts SET accrued_micro_usd = %s WHERE id = %s", (1.5, account)
        )
    with db.transaction() as tx:
        assert (
            tx.fetchval("SELECT accrued_micro_usd FROM budget_accounts WHERE id=%s", (account,))
            == 0
        )


def test_management_qualification_needs_ten(db: Database) -> None:  # V-6
    with pytest.raises(Conflict), db.transaction() as tx:
        insert_row(
            tx,
            "qualification_runs",
            {
                "id": uuid.uuid4(),
                "season_id": seed_season(tx),
                "evaluated_at": T0,
                "production_status": "NOT_QUALIFIED",
                "management_status": "QUALIFIED",
                "consecutive": 1,
                "body": jsonb({}),
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
