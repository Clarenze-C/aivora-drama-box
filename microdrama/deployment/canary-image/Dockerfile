# Drama Box T031 canary image — ComfyUI + VideoHelperSuite + the canary stub nodes.
#
# The image DIGEST (not the tags or the clones inside) is what the T031
# authorization pins: image_ref must be the full <registry>/<repo>@sha256:<hex>
# of the image that gets pushed. Nothing here is secret; the image is intended
# to be pushed PUBLIC so the pod create needs no registry credential.
#
# Build context: this directory (canary_stub_nodes/, make_fake_checkpoint.py).
#   docker build -t drama-canary:t031 .

FROM pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ComfyUI pinned to v0.3.77 (commit 59afc3984868289f808d02fa5cd180edfb2de240):
# the newest tag whose comfy/quant_ops.py does NOT import comfy_kitchen/triton,
# which crashes at import on any GPU-less host (verified: every v0.4x tag does;
# local CPU verification of this image is a hard requirement, so HEAD is not
# pinnable). Reproducibility comes from the pushed digest, which is the
# authorization pin.
# VHS_VideoCombine is provided by canary_stub_nodes (an override with exactly
# the four inputs the repo binder sends) — real VideoHelperSuite commits either
# require extra inputs (loop_count/pingpong/save_output on the v0.3.77-era line)
# or a newer comfy_api than v0.3.77 ships, so it is deliberately not installed.
RUN git clone --depth 1 --branch v0.3.77 \
        https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI

# Core-loader patch (see patch_comfyui.py): custom nodes cannot override core
# class names on v0.3.77, so CheckpointLoaderSimple is patched to short-circuit
# for the canary's placeholder checkpoint. Fails the build if the source moved.
COPY patch_comfyui.py /tmp/patch_comfyui.py
RUN python /tmp/patch_comfyui.py && rm /tmp/patch_comfyui.py

COPY canary_stub_nodes /opt/ComfyUI/custom_nodes/canary_stub_nodes
COPY make_fake_checkpoint.py /tmp/make_fake_checkpoint.py

# ComfyUI's requirements bring safetensors, which make_fake_checkpoint.py needs;
# imageio (not in ComfyUI's requirements) drives the h264 encode in the stub
# VHS_VideoCombine override.
RUN pip install --no-cache-dir -r /opt/ComfyUI/requirements.txt \
    && pip install --no-cache-dir imageio imageio-ffmpeg

RUN python /tmp/make_fake_checkpoint.py && rm /tmp/make_fake_checkpoint.py

WORKDIR /opt/ComfyUI
# CN-5 (2026-11-09, canary-night review): the exposed port is a token-checking
# gateway, not ComfyUI itself. ComfyUI binds 127.0.0.1:8189 ONLY; the gateway
# owns 0.0.0.0:8188 (the port the Runpod proxy serves) and refuses every request
# without the run's bearer token (env MICRODRAMA_COMFY_TOKEN, set at pod-create
# time from the pipeline's credential ref - no secret in the image). ComfyUI
# stays PID 1 (a crash still kills the pod); the gateway fails closed: without
# a token env it 401s everything, and while ComfyUI boots it 502s (the canary's
# documented boot-window retry covers that).
COPY canary_gateway.py /opt/canary_gateway.py
EXPOSE 8188
CMD ["sh", "-c", "python /opt/canary_gateway.py & exec python main.py --listen 127.0.0.1 --port 8189"]
