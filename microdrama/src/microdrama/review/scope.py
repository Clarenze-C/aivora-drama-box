"""Season-to-owner scope for every review/workbench read and decision (T044a).

The ``season_owners`` relation (migration 0024) is the only ownership truth: a
season is visible to exactly the owner its row names, and to nobody else — not to
other owners, not to service credentials (every helper here resolves the owner
through ``owner_id_in_tx``, which refuses workers, models, schedulers and
webhooks before anything is read), and not to anonymous readers. Seasons with no
row (ambiguous or unapproved legacy data) are hidden until an audited assignment
links them.

Provenance is enforced at two layers, and only the first is database-enforced
today: the ``season_owners`` trigger verifies that a ``GATE1_APPROVAL_BACKFILL``
link cites the season's own human Gate 1 approval, while
``CREATOR_AT_CREATION``/``AUDITED_ASSIGNMENT`` rows are admitted by the database
whenever the shared application DB role writes them — the human-only write paths
in this module are an application-layer control, not a structural one. DB-role
isolation and an audited assignment control are T046 work (see
docs/microdrama-system/T044a-contract-proposal.md).

Every helper refuses with the same ``NotFound`` the row would raise if it did not
exist, so a cross-owner probe cannot distinguish "exists, not yours" from "does
not exist" — no private bytes leak either way.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from microdrama.contracts.errors import NotFound
from microdrama.contracts.principals import Principal
from microdrama.core.auth import owner_id_in_tx
from microdrama.persistence.db import Tx, insert_row

CREATOR_SOURCE = "CREATOR_AT_CREATION"


def link_season_creator(tx: Tx, season_id: UUID, principal: Principal) -> None:
    """Link a just-created season to the human owner creating it (intake path).

    Called inside the season-creation transaction: a season never exists unowned
    on the new-intake path. Only a human owner principal can claim creation —
    ``owner_id_in_tx`` refuses workers, models, schedulers and webhooks before
    anything is written. This is an application-layer control: the database
    trigger behind ``season_owners`` verifies only ``GATE1_APPROVAL_BACKFILL``
    provenance, so a caller sharing the application DB role could still insert a
    ``CREATOR_AT_CREATION`` row directly; closing that with DB-role isolation is
    T046 work. There is deliberately no assignment endpoint in this module.
    """
    owner_id = owner_id_in_tx(tx, principal)
    if tx.fetchone("SELECT 1 FROM season_owners WHERE season_id = %s", (season_id,)):
        raise NotFound(f"season {season_id} already has an owner")
    insert_row(
        tx,
        "season_owners",
        {
            "season_id": season_id,
            "owner_id": owner_id,
            "source": CREATOR_SOURCE,
        },
    )


def scoped_owner_id(tx: Tx, principal: Principal) -> UUID:
    """The owner every scoped read of this transaction is limited to."""
    return owner_id_in_tx(tx, principal)


def season_is_owned_by(tx: Tx, season_id: UUID, owner_id: UUID) -> bool:
    return (
        tx.fetchone(
            "SELECT 1 FROM season_owners WHERE season_id = %s AND owner_id = %s",
            (season_id, owner_id),
        )
        is not None
    )


def require_season_access(tx: Tx, principal: Principal, season_id: UUID) -> None:
    """Refuse unless the season exists AND is linked to the principal's owner."""
    owner_id = scoped_owner_id(tx, principal)
    row = tx.fetchone("SELECT id FROM seasons WHERE id = %s", (season_id,))
    if row is None or not season_is_owned_by(tx, season_id, owner_id):
        raise NotFound(f"season {season_id} not found")


def require_episode_access(tx: Tx, principal: Principal, episode_id: UUID) -> dict[str, Any]:
    """The episode row, but only when its season belongs to the principal's owner."""
    owner_id = scoped_owner_id(tx, principal)
    row = tx.fetchone(
        "SELECT e.*, so.owner_id AS scope_owner_id FROM episodes e "
        "LEFT JOIN season_owners so ON so.season_id = e.season_id "
        "WHERE e.id = %s",
        (episode_id,),
    )
    if row is None or row["scope_owner_id"] != owner_id:
        raise NotFound(f"episode {episode_id} not found")
    return row


def require_asset_access(tx: Tx, principal: Principal, asset_id: UUID) -> dict[str, Any]:
    """The asset row for the owner media stream; unscoped assets never stream.

    Real render outputs (``rendering/comfy_assets.persist_output``) are
    registered with ``season_id=None`` and a valid ``episode_id``: their scope
    is derived from the linked episode's season, never from a NULL asset
    season. ``asset.season_id`` authorizes only season-level assets that carry
    no episode. Any non-null ``asset.season_id`` must name the same season as
    the linked episode — a disagreeing pair is an inconsistent row and is
    refused, so an asset cannot ride one owner's season column while its bytes
    belong to another owner's episode. Assets with neither id, a dangling
    episode id, or an unowned scope season answer like missing rows.
    """
    owner_id = scoped_owner_id(tx, principal)
    row = tx.fetchone("SELECT * FROM assets WHERE id = %s", (asset_id,))
    if row is None:
        raise NotFound(f"asset {asset_id} not found")
    episode_id = row["episode_id"]
    asset_season_id = row["season_id"]
    if episode_id is not None:
        episode = tx.fetchone("SELECT season_id FROM episodes WHERE id = %s", (episode_id,))
        if episode is None:
            raise NotFound(f"asset {asset_id} not found")  # dangling episode link
        if asset_season_id is not None and asset_season_id != episode["season_id"]:
            raise NotFound(f"asset {asset_id} not found")  # inconsistent season/episode
        scope_season_id = episode["season_id"]
    elif asset_season_id is not None:
        scope_season_id = asset_season_id
    else:
        raise NotFound(f"asset {asset_id} not found")  # unscoped: no episode, no season
    if not season_is_owned_by(tx, scope_season_id, owner_id):
        raise NotFound(f"asset {asset_id} not found")
    return row


def owner_season_rows(tx: Tx, principal: Principal) -> list[dict[str, Any]]:
    """Every season linked to the principal's owner, in listing order."""
    owner_id = scoped_owner_id(tx, principal)
    return tx.fetchall(
        "SELECT s.* FROM seasons s JOIN season_owners so ON so.season_id = s.id "
        "WHERE so.owner_id = %s ORDER BY s.created_at, s.id",
        (owner_id,),
    )


__all__ = [
    "CREATOR_SOURCE",
    "link_season_creator",
    "owner_season_rows",
    "require_asset_access",
    "require_episode_access",
    "require_season_access",
    "scoped_owner_id",
    "season_is_owned_by",
]
