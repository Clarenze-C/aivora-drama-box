# T031 local runtime build evidence — 6 November 2026 UTC

Status: LOCAL CODE-ONLY IMAGE BUILT; NATIVE CPU SCHEMA VERIFIED; GPU/WEIGHTS UNQUALIFIED.

- Local tag: `drama-pika-h3-flex:t031-native`.
- Image ID: `sha256:773f4df5effd1f9087bacc4b693c97e633dbbbef9f8cbac784bc3ea3896d142d`.
- Image size: 9,541,941,864 bytes (9.54GB decimal).
- Source revision: `63e5bf594339f676b4b15e072529873e3448409e`.
- Source archive SHA256: `22ebca008dc6cbc8ab7cf2b456a3580a9195e3d81102f9d07d54c44b889f8257`.
- Base digest: `sha256:7b324d212a4450795b49edba9949b7cdc72429148a64e974334bfe5774d51385`.
- Runtime lock: 173 exact distribution pins, including unchanged base torch2.9.1+cu128,
  torchvision0.24.1+cu128 and torchaudio2.9.1+cu128. Complete inventory includes inherited base packages.
- `python -m pip check`: passed in build and final image.
- Six tiny offline provisioning tests: passed,0.18seconds. No model download was run.
- Native CPU/no-weight registration:16 mapped classes passed; actual HTTP `/object_info`
  from real PromptServer/default_asset_manager, with container networking disabled.
- Native Autogrow parses zero-based dotted image/audio ports. Native SaveVideo parses
  `format=mp4`, `format.codec=h264`. Actual CLIPLoader enum includes `minimax`.
- Complete actual CPU receipt: `schema-attestation.cpu.json`, SHA256
  `1a6023e24ad38cd4ef41e1d3b1c727550a52cba9cd055be2ede8373e487a4c89`.
  This is actual CPU runtime evidence; it is not a LIVE executable seal. Model filename
  enums are empty on this deliberately weight-free image, so schema must be reattested
  after independently authorized provisioning on the final runtime.
- Source contains native audio/video nodes; no stub sampler/loader patches or weights.
  Source archive contained no checkpoint/safetensors/pt/pth/bin files.
- Last checked disk headroom after build: approximately24GB. Other workstream data/caches
  were preserved. No push, provider resources, hosted API or account operation occurred.

The approved CUDA12.8 base emits an upstream warning that optimized CUDA operations
need CUDA13.0+. No runtime patch or base substitution was made. CPU imports/schema
passed; A40 support, kernel/offload behavior, memory fit, actual weight loading and
Thai/native-audio quality remain unverified. Bundled tokenizer provenance is inventoried;
actual weight-loading may discover additional files and remains a later gated check.

## Commands and logs

From worktree root `/root/AIVORA/drama-box/.scratch/t031-native-worktree`:

```sh
flock /tmp/t031-native-heavy.lock systemd-run --scope -p CPUQuota=45% \
  timeout 1200 docker build --pull=false --tag drama-pika-h3-flex:t031-native .scratch/runtime-image/context
flock /tmp/t031-native-heavy.lock systemd-run --scope -p CPUQuota=45% \
  timeout 300 bash .scratch/runtime-image/verify.sh
flock /tmp/t031-native-heavy.lock systemd-run --scope -p CPUQuota=45% \
  timeout 120 microdrama/.venv/bin/python -m pytest microdrama/deployment/pika-h3-flex/test_provision.py \
  --basetemp .scratch/runtime-image/basetemp-provision -q -o addopts=
```

Public dependencies were resolved using `pip install --dry-run --report` in the exact
base; `dependency-resolution.json` retains selected versions/artifact hashes.
Logs: `.scratch/runtime-image/base-pull.log`, `resolve-pip.log`, `build.log`,
`rebuild.log` (final cached helper rebuild), `schema-smoke.log`, `provision-tests.log`,
`image-check.log`, `image-inspect.json`. Earlier helper constructor failure is retained
in `schema-smoke-server-init-failure.log`; it was corrected using the upstream real
AssetManager signature, without modifying any upstream runtime code.

## Artifact SHA256

- `Dockerfile`: `f8202c2a2da95969af1728a5ea647aae70fe18b378a72bad80236e4548b579f8`.
- `README.md`: `6c101f2537fe4d75289f23ed720a63b94270c60acb079fe8b3f7b7fe12a28adc`.
- `base-packages.json`: `5822e5033e4164bb61521e4e7ce0339b93f3d78d6ce018777878de364f9f7655`.
- `build.sh`: `54bd543f742812646363e88b842e7019a9ac17595f899d7c6802cffdad2e7527`.
- `dependency-resolution.json`: `a5a8f15c432495d96458cfdbba90d7f643be8752308b5586f347b21dad4582d7`.
- `loader-source-inventory.json`: `d224ef0704cbb144bbe183546d305e322c825b07f99485eda6d7c08496fe68a9`.
- `models.json`: `a62564d1ec9c18ef0797b3fabf06527b1fe0956a4b63a4b61c51f73e8779f99f`.
- `provision.py`: `04070ce9df7f2d7cb538b81562fd88ad45a458a1be27bc5455354eacdc29ca3b`.
- `runtime.lock`: `8948d4bb810b12e3a419064ab0ef8443656d710d4dce82e3e5813e6f7522b118`.
- `schema-attestation.cpu.json`: `1a6023e24ad38cd4ef41e1d3b1c727550a52cba9cd055be2ede8373e487a4c89`.
- `schema_smoke.py`: `6fb6ffb439ba07d0127965b9ffbd328e8364f1d66d847a3fb7e13ae6bb05454c`.
- `source.json`: `4d016efdaed16a39d0f539e304e31b7b328585126d98cffd78df9b4aaad6c145`.
- `test_provision.py`: `4ad7160cc0e9d287ed358520f4ae742dd2bdecbc692bc28a70ffe8bc10c8e564`.
