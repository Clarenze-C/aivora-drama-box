"""Build-time patch of the pinned ComfyUI (v0.3.77) for the canary image.

Custom-node mappings cannot override core class names on v0.3.77, so the core
CheckpointLoaderSimple is patched instead: when asked for the canary's
fake-video-model.safetensors it returns inert MODEL/CLIP/VAE placeholders
instead of trying to load the placeholder file as a real diffusion checkpoint.
The exact source line is matched verbatim; a version bump that changes it fails
the build loudly rather than shipping an unpatched loader.
"""

from pathlib import Path

NODES = Path("/opt/ComfyUI/nodes.py")
NEEDLE = (
    "    def load_checkpoint(self, ckpt_name):\n"
    '        ckpt_path = folder_paths.get_full_path_or_raise("checkpoints", ckpt_name)\n'
)

PATCHED = (
    "    def load_checkpoint(self, ckpt_name):\n"
    '        if ckpt_name == "fake-video-model.safetensors":\n'
    "            # Drama Box T031 canary image patch: the canary workflow never\n"
    "            # uses a real model; custom nodes cannot override core class\n"
    "            # names on v0.3.77, so the core loader returns placeholders.\n"
    "            class _Inert:\n"
    "                pass\n"
    "            return (_Inert(), _Inert(), _Inert())\n"
    '        ckpt_path = folder_paths.get_full_path_or_raise("checkpoints", ckpt_name)\n'
)

source = NODES.read_text()
count = source.count(NEEDLE)
if count != 1:
    raise SystemExit(
        f"canary patch: expected exactly one load_checkpoint needle in {NODES}, "
        f"found {count} - the pinned ComfyUI source changed; refusing to build"
    )
NODES.write_text(source.replace(NEEDLE, PATCHED, 1))
print("canary patch applied to CheckpointLoaderSimple")
