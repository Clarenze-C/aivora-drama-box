"""Versioned ComfyUI workflow templates for the rendering lane (T013).

A template is declarative metadata plus a binding family: ``binding.bind_workflow`` turns
a template and a ``RenderRequest`` into the API-format prompt graph actually submitted.
Nothing in this package talks to a server. Template identity is content-hashed
(``template_sha256``) so a ``RenderRequest.workflow_sha256`` pins the exact template the
attempt was planned against; a stored request can never silently render through a
different workflow.

The mock family targets the T007 fake node catalog (LoadImage, CheckpointLoaderSimple,
FakeVideoModelSampler, VHS_VideoCombine). Real pinned workflows arrive with T031 preset
evidence; T014's preset registry maps preset ids onto templates through
``PRESET_TEMPLATES`` (or registers its own live equivalents beside them).
"""

from microdrama.rendering.workflows.binding import (
    BoundWorkflow,
    bind_workflow,
)
from microdrama.rendering.workflows.templates import (
    MOCK_VIDEO_TEMPLATE,
    PRESET_TEMPLATES,
    WorkflowTemplate,
    template_sha256,
)

__all__ = [
    "MOCK_VIDEO_TEMPLATE",
    "PRESET_TEMPLATES",
    "BoundWorkflow",
    "WorkflowTemplate",
    "bind_workflow",
    "template_sha256",
]
