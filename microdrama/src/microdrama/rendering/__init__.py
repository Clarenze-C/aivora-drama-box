"""Routing, Comfy jobs, Runpod leases, independent janitor.

T012 (this build): pod acquisition/reconciliation, timed leases with cost accrual on
declared bases, verified shutdown, warm-pod transfer and the independent janitor. The
ComfyUI adapter (T013), route/preset support (T014), and fixture-backed live transports
(T045) live in focused modules. Live Runpod composition remains attestation- and effect-gated;
route/job registration belongs to the integrator.
"""

from microdrama.rendering.finality import (
    LeaseBillingFinality,
    LeaseSettlement,
    RunpodInvoiceFinality,
    SyntheticUsageFinality,
)
from microdrama.rendering.janitor import (
    Janitor,
    JanitorAction,
    JanitorReport,
    build_janitor,
)
from microdrama.rendering.leases import (
    HUMAN_WAIT_STATES,
    LIVE_LEASE_STATES,
    TERMINAL_LEASE_STATES,
    LeaseHandle,
    LeaseService,
    PodLeaseClaimRequest,
    PodLeaseConfig,
    ShutdownResult,
    accrue_lease_usage,
    build_lease_service,
    client_token_for,
    close_storage_ownership,
    human_wait_guard,
    mock_pod_price,
    open_storage_ownership,
    settle_reservation_for_lease,
)
from microdrama.rendering.pods import (
    LEASE_OPERATION_KIND,
    STOP_OPERATION_KIND,
    PodManager,
    PodSpec,
    RunpodLiveAdapter,
    check_acquisition_filters,
    resolve_pod_provider,
)
from microdrama.rendering.runpod_transport import (
    RunpodBillingHistory,
    RunpodBillingRecord,
    RunpodQuoteAttestation,
    RunpodRestProvider,
)

__all__ = [
    "HUMAN_WAIT_STATES",
    "Janitor",
    "JanitorAction",
    "JanitorReport",
    "LEASE_OPERATION_KIND",
    "LIVE_LEASE_STATES",
    "LeaseHandle",
    "LeaseService",
    "PodLeaseClaimRequest",
    "PodLeaseConfig",
    "PodManager",
    "PodSpec",
    "RunpodLiveAdapter",
    "RunpodBillingHistory",
    "RunpodBillingRecord",
    "RunpodQuoteAttestation",
    "RunpodRestProvider",
    "STOP_OPERATION_KIND",
    "ShutdownResult",
    "TERMINAL_LEASE_STATES",
    "accrue_lease_usage",
    "build_janitor",
    "build_lease_service",
    "check_acquisition_filters",
    "client_token_for",
    "human_wait_guard",
    "mock_pod_price",
    "resolve_pod_provider",
    "close_storage_ownership",
    "open_storage_ownership",
    "LeaseBillingFinality",
    "LeaseSettlement",
    "RunpodInvoiceFinality",
    "SyntheticUsageFinality",
    "settle_reservation_for_lease",
]
