"""Release core (T020): scheduling DAG, provider protocol orchestration, reconciliation.

``slots`` expands an APPROVED Gate 2 package into durable publication slots;
``service`` drives each slot through submit/poll/reconcile with provider-operation
crash safety and readback-gated verification; ``metadata`` versions post metadata.
Platform adapters (T021–T024) implement the shared ``PublisherAdapter`` protocol and
register with the service — they own no local approval or budget logic of their own.
"""

from microdrama.publishing.service import (
    MAX_SUBMIT_ATTEMPTS,
    PUBLISH_DEADLINE_MS,
    REQUIRED_VERIFY_FIELDS,
    HeldSlot,
    PublishingService,
)
from microdrama.publishing.slots import (
    platform_post_id,
    publish_client_token,
    schedule_release,
    validate_scope_dag,
)

__all__ = [
    "HeldSlot",
    "MAX_SUBMIT_ATTEMPTS",
    "PUBLISH_DEADLINE_MS",
    "PublishingService",
    "REQUIRED_VERIFY_FIELDS",
    "platform_post_id",
    "publish_client_token",
    "schedule_release",
    "validate_scope_dag",
]
