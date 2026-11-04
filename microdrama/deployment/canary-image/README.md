# T031 canary image

The digest-pinned image the T031 canary runs. ComfyUI v0.3.77 +
`canary_stub_nodes/`, which provides all three non-builtin classes the canary's
workflow needs: a stub `FakeVideoModelSampler`, an override of
`CheckpointLoaderSimple` (so the fake checkpoint never really loads), and an
override of `VHS_VideoCombine` (exactly the four inputs the repo binder sends;
encodes via imageio-ffmpeg). The stubs exist because the canary's workflow is
the mock template (`mock-video-fake-sampler`): a stock ComfyUI image cannot
satisfy its `/object_info` gate by design, and real VideoHelperSuite commits
either demand extra required inputs or a newer comfy_api. Nothing here is
secret; the image contains no credentials, prompts or models.

## Build and verify (this host)

```bash
docker build -t drama-canary:t031 \
  /root/AIVORA/drama-box/microdrama/deployment/canary-image/

docker rm -f canary-smoke 2>/dev/null || true
# --cpu override for the driverless VPS; the image's own CMD stays GPU-native
# for the Runpod pod (ComfyUI v0.3.76/77 hard-fails cuda init with no driver).
docker run -d --name canary-smoke -p 127.0.0.1:18188:8188 drama-canary:t031 \
  python main.py --listen 0.0.0.0 --port 8188 --cpu
cd /root/AIVORA/drama-box/microdrama
PYTHONPATH=src .venv/bin/python deployment/canary-image/smoke_test_canary_image.py
# prints SMOKE TEST PASSED and leaves the mp4 in out/canary-smoke-output/
docker rm -f canary-smoke
```

The smoke test proves the image against the repo binder's exact graph:
all four mapped node classes in `/object_info`, the stub-loader override
active, `/prompt` acceptance, successful execution, and a fetchable output
with sha256.

## Push (operator)

**RunPod hosts no pushable registry** — `create-registry` in the RunPod API
only stores PULL credentials for an external registry. So "RunPod's registry"
translates to: push to a public external registry; public means the pod create
needs no `registry` credential id at all.

Docker Hub (public repo `clarenze/drama-canary`):

```bash
docker login                       # operator's Docker Hub credentials
docker tag drama-canary:t031 clarenze/drama-canary:t031
docker push clarenze/drama-canary:t031
docker inspect --format='{{index .RepoDigests 0}}' clarenze/drama-canary:t031
```

or GHCR (public image, PAT with write:packages):

```bash
echo $GHCR_TOKEN | docker login ghcr.io -u Clarenze-C --password-stdin
docker tag drama-canary:t031 ghcr.io/clarenze-c/drama-canary:t031
docker push ghcr.io/clarenze-c/drama-canary:t031
```

The `docker inspect` line prints the digest reference to copy into
`pins.image_ref` of `/root/.secrets/drama-box/t031-canary-auth.json`
(full `<registry>/<repo>@sha256:<64 hex>`), then re-run preflight for the new
`authorization_sha256`. A private registry would ALSO need the adapter to send
RunPod's registry credential id on create — keep the image public and avoid
that change.

## Notes

- The clones inside (ComfyUI, VideoHelperSuite) float at build-time HEAD.
  Reproducibility comes from the pushed digest, which is the authorization pin.
- `--listen 0.0.0.0` in CMD is required: the RunPod proxy cannot reach a
  localhost bind, and the canary's Comfy endpoint is
  `https://<pod-id>-8188.proxy.runpod.net` (public and unauthenticated for the
  pod's lifetime — ~90 min per canary run; nothing sensitive is served).
- Ports are declared at pod creation by the adapter (`ports: ["8188/http"]`,
  2026-11-04 fix); RunPod cannot add ports to a running pod.
