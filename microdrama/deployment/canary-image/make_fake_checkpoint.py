"""Write the placeholder checkpoint so the name exists in models/checkpoints."""

import torch
from safetensors.torch import save_file

save_file(
    {"canary.placeholder": torch.zeros(1)},
    "/opt/ComfyUI/models/checkpoints/fake-video-model.safetensors",
)
print("wrote /opt/ComfyUI/models/checkpoints/fake-video-model.safetensors")
