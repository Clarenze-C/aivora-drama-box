"""T021 test support: the frozen T020 world with the YouTube adapter registered.

``YouTubeWorld`` subclasses the T020 ``PublishingWorld`` (never edited) and swaps
``adapters[Platform.YOUTUBE]`` for the offline YouTube adapter, then rebuilds the
service — the registration pattern the T020 notes prescribe for T021–T024. Slot
plans pin capability ids from ``adapter.capability`` at build time, so replacing
the adapter before any plan exists keeps the pinning checks consistent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

from microdrama.config import Settings
from microdrama.contracts.enums import Platform
from microdrama.persistence import Database
from microdrama.publishing.service import PublishingService
from microdrama.publishing.youtube import YouTubeScenario, build_youtube_adapter
from microdrama.testing.fakes.common import ensure_mock_mode

_UNIT_PUBLISHING = Path(__file__).resolve().parents[1]
if str(_UNIT_PUBLISHING) not in sys.path:
    sys.path.insert(0, str(_UNIT_PUBLISHING))

from publishing_support import PublishingWorld  # noqa: E402


class YouTubeWorld(PublishingWorld):
    def __init__(
        self,
        db: Database,
        tmp: Path,
        settings: Settings,
        *,
        scenarios: tuple[YouTubeScenario, ...] = (),
        version: int = 1,
        enabled: bool = True,
    ) -> None:
        super().__init__(db, tmp, settings)
        ensure_mock_mode(settings)  # offline fixture adapters exist only in OFFLINE_MOCK
        self.youtube = build_youtube_adapter(
            settings,
            clock=self.clock,
            ids=self.ids,
            scenarios=scenarios,
            version=version,
            enabled=enabled,
        )
        self.adapters[Platform.YOUTUBE] = self.youtube
        self.service = PublishingService(self.db, self.clock, self.ids, self.adapters, self.store)

    def media_path(self, asset_id: UUID) -> Path:
        """The stored object path for an asset (the service resolves media this way)."""
        row = self.row("SELECT object_key FROM assets WHERE id = %s", (asset_id,))
        assert row is not None
        return self.store.local_path(row["object_key"])


__all__ = ["YouTubeWorld"]
