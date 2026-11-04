"""Drama Box T031 canary stub nodes.

This custom node ships ONLY inside the digest-pinned canary image. The canary
workflow (mock-video-fake-sampler template) wires:

    CheckpointLoaderSimple{ckpt_name="fake-video-model.safetensors"}
      -> FakeVideoModelSampler{model, prompt, frames, seed, width, height}
      -> VHS_VideoCombine{images, frame_rate, filename_prefix, format="video/h264-mp4"}

so the image must expose exactly those class names in /object_info, with exactly
the inputs the repo binder sends. Note that custom-node mappings CANNOT override
core class names on ComfyUI v0.3.77 (verified: the builtin CheckpointLoaderSimple
executed and died on the placeholder file) - the core loader is patched at build
time instead (patch_comfyui.py). This module provides:

- FakeVideoModelSampler (ours outright): deterministic synthetic frames from the
  seed.
- VHS_VideoCombine (an override - the name is free because real VHS is not
  installed): exactly the four contracted inputs; encodes the tensor to h264 via
  imageio-ffmpeg and reports the standard "gifs" UI shape the client reads from
  /history.

Nothing here needs a real model, and the pod's GPU is exercised only as the
leased billing surface.
"""

from __future__ import annotations

import time

import imageio.v2 as imageio
import torch
from folder_paths import get_output_directory

CANARY_CHECKPOINT = "fake-video-model.safetensors"
CANARY_FORMAT = "video/h264-mp4"


class FakeVideoModelSampler:
    """Deterministic synthetic video frames standing in for a real model."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "frames": ("INT", {"default": 97, "min": 1, "max": 1024}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "width": ("INT", {"default": 720, "min": 16, "max": 4096}),
                "height": ("INT", {"default": 1280, "min": 16, "max": 4096}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "sample"
    CATEGORY = "canary/stub"

    def sample(self, model, prompt, frames, seed, width, height):
        # (frames, height, width, 3) float32 in [0, 1]: one seed-derived color
        # field with a per-frame drift. ~1 GB at the canary's 97x1280x720; the
        # in-place remainder keeps peak memory at one extra tensor.
        print(
            f"CANARY sample: frames={frames} seed={seed} width={width} height={height}",
            flush=True,
        )
        generator = torch.Generator().manual_seed(int(seed))
        field = torch.rand(1, int(height), int(width), 3, generator=generator)
        drift = torch.rand(int(frames), 1, 1, 3, generator=generator) * 0.5
        out = field + drift
        out %= 1.0
        # A TUPLE return is the ComfyUI convention: a bare tensor gets iterated
        # by the execution engine's return-wrapping, which splits the batch into
        # per-frame "outputs" and downstream [node, 0] links receive ONE frame
        # (verified live: combine saw (1280,720,3) instead of (98,1280,720,3)).
        return (out.contiguous(),)


class CanaryVideoCombine:
    """Override of VHS_VideoCombine with exactly the four contracted inputs."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "frame_rate": ("INT", {"default": 24, "min": 1, "max": 240}),
                "filename_prefix": ("STRING", {"default": "md/canary"}),
                "format": ([CANARY_FORMAT],),
            }
        }

    RETURN_TYPES = ()
    FUNCTION = "combine"
    OUTPUT_NODE = True
    CATEGORY = "canary/stub"

    def combine(self, images, frame_rate, filename_prefix, format):
        print(
            f"CANARY combine: images type={type(images).__name__} "
            f"shape={tuple(images.shape) if hasattr(images, 'shape') else 'n/a'}",
            flush=True,
        )
        prefix = str(filename_prefix) or "md/canary"
        subfolder, _, leaf = prefix.rpartition("/")
        directory = get_output_directory()
        if subfolder:
            directory = f"{directory}/{subfolder}"
        import os

        os.makedirs(directory, exist_ok=True)
        filename = f"{leaf}_{time.time_ns():x}.mp4"
        path = f"{directory}/{filename}"
        writer = imageio.get_writer(
            path,
            fps=int(frame_rate),
            codec="libx264",
            macro_block_size=None,
            pixelformat="yuv420p",
        )
        try:
            for frame in images:
                writer.append_data((frame.cpu().numpy() * 255).astype("uint8"))
        finally:
            writer.close()
        return {"ui": {"gifs": [{"filename": filename, "subfolder": subfolder, "type": "output"}]}}


NODE_CLASS_MAPPINGS = {
    "FakeVideoModelSampler": FakeVideoModelSampler,
    "VHS_VideoCombine": CanaryVideoCombine,
}

__all__ = ["NODE_CLASS_MAPPINGS", "CANARY_CHECKPOINT", "CANARY_FORMAT"]
