"""In-app scheduling and webhook intake (T029): the W01–W12 trigger surface.

Replaces the earlier n8n export plan (operator decision 2026-10-23): firing is
a pure function of (registry, now) that only enqueues frozen job types or runs
the independent janitor actions; webhook routes record deduplicated untrusted
events. Core invariants stay in the tested services.
"""

from __future__ import annotations

from .registry import SCHEDULES_VERSION, Schedule, ScheduleCatalog, default_catalog
from .service import FireReport, TriggerScheduler, load_last_fired, record_fired

__all__ = [
    "SCHEDULES_VERSION",
    "FireReport",
    "Schedule",
    "ScheduleCatalog",
    "TriggerScheduler",
    "default_catalog",
    "load_last_fired",
    "record_fired",
]
