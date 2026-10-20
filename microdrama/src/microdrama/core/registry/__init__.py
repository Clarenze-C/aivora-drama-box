"""Configuration and evidence registries (T006).

- ``policy``: accepted automation policy and directing playbook as settings. Importing them never
  makes anything ready (``AutomationPolicySettings.readiness_blockers``).
- ``rights``: versioned rights evidence per route and subject; UNKNOWN, INELIGIBLE, EXPIRED and
  uncovered territories block.
- ``capabilities``: account/provider capability records; only SUPPORTED_TESTED operations pass.
- ``presets``: benchmarked render presets; ``compatible`` never drops a required control.
- ``credentials``: credential references and edge-only resolution; ``Secret`` never prints.
- ``release_conditions``: all release blockers together; green QA never clears them (AT-13).

Every writer and reader here runs on the real database through ``persistence.Database``.
"""

from microdrama.core.registry.capabilities import CapabilityDecision, CapabilityRegistry
from microdrama.core.registry.credentials import (
    CredentialStore,
    CredentialStoreKind,
    Secret,
    assert_no_secrets,
    redactor,
)
from microdrama.core.registry.policy import (
    ALLOCATION_KEYS,
    AutomationPolicySettings,
    DirectingPlaybook,
    PlaybookLimits,
    PolicySafetyFlags,
    import_policy,
    load_automation_policy,
    load_directing_playbook,
    usd_to_micro,
)
from microdrama.core.registry.presets import PresetRegistry
from microdrama.core.registry.release_conditions import (
    QA_BLOCKER,
    DestinationRequirement,
    evaluate_release_conditions,
)
from microdrama.core.registry.rights import RightsDecision, RightsRegistry

__all__ = [
    "ALLOCATION_KEYS",
    "QA_BLOCKER",
    "AutomationPolicySettings",
    "CapabilityDecision",
    "CapabilityRegistry",
    "CredentialStore",
    "CredentialStoreKind",
    "DestinationRequirement",
    "DirectingPlaybook",
    "PlaybookLimits",
    "PolicySafetyFlags",
    "PresetRegistry",
    "RightsDecision",
    "RightsRegistry",
    "Secret",
    "assert_no_secrets",
    "evaluate_release_conditions",
    "import_policy",
    "load_automation_policy",
    "load_directing_playbook",
    "redactor",
    "usd_to_micro",
]
