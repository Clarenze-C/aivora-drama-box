# Pika H3 Flex Ref2VA code-only runtime

Separate from the old stub canary image. Uses unmodified ComfyUI revision
`63e5bf594339f676b4b15e072529873e3448409e` and the digest-pinned CUDA/PyTorch
base in `source.json`. No model weights, credentials, sampler stubs, loader patches,
hosted Pika calls or external TTS.

`runtime.lock` is the complete exact Python distribution inventory resolved in
that immutable base. `--no-deps` prevents silently widening the lock; `pip check`
gates the image. Build from this directory with a dedicated scratch context and
at least 12GiB free, plus the base image if not already available:

```sh
flock /tmp/t031-native-heavy.lock systemd-run --scope -p CPUQuota=45% \
  timeout 1200 bash ./build.sh /absolute/path/to/scratch/context
```

Only local tag `drama-pika-h3-flex:t031-native` is built. Never push without
separate authorization. Public code downloads use immutable revisions and SHA256.
Runtime startup runs neither provisioning nor pip. Hugging Face/Transformers
are offline; API nodes and custom nodes are disabled. Normal runtime needs a GPU.
CPU smoke cannot qualify A40 inference, fit, Thai speech or quality.

`models.json` pins five official repack files (42,030,014,463 bytes). The repack
adapter differs from Pika's original BF16 export. Bundled Qwen tokenizer and
critical loader sources have hashes in `loader-source-inventory.json`, from the
same pinned archive. This inventory is not complete weight-loading proof; any
additional files discovered during actual loading require provenance.

Preflight has no network and fails for missing/corrupt files:

```sh
python provision.py --destination /path/to/models
```

Only explicit `--download` can fetch weights. The following was NOT executed and
requires separate authorization and a sufficiently provisioned host:

```sh
python provision.py --destination /path/to/models --download
```

Free space must cover missing final files, largest temporary file and 8GiB
headroom. Size/SHA256 verification precedes atomic promotion; verified complete
files alone are reused. Failed downloads never become loader inputs. No fallback.

CPU smoke registers native nodes and reads actual schemas, exercising native
Autogrow expansion. API slots are zero-based dotted keys:
`ref_images.ref_image_0` through `_8`, `ref_audios.ref_audio_0` through `_2`.
Prompt labels `<Picture 1>`/`<Audio 1>` are one-based. The 480×832 portrait
adaptation obeys H3's 32-pixel multiple but remains unqualified on GPU.
124 frames at 24 fps means 5.167 seconds.

```sh
flock /tmp/t031-native-heavy.lock systemd-run --scope -p CPUQuota=45% \
  timeout 240 docker run --rm --network none --cpus 0.45 \
  --entrypoint python drama-pika-h3-flex:t031-native /opt/pika/schema_smoke.py
```

Smoke evidence says `ACTUAL_RUNTIME_CPU_NO_WEIGHTS`, `inference_verified=false`.
Failure is a runtime blocker; fixture node definitions never replace it. Tiny
provisioning tests live in `test_provision.py`. Image identity and receipts are
recorded in `BUILD_EVIDENCE.md` when available.
