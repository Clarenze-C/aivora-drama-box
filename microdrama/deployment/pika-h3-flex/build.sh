#!/usr/bin/env bash
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
context=${1:?Pass a dedicated scratch build-context directory}
mkdir -p "$context"
available=$(df -PB1 "$context" | awk 'NR==2 {print $4}')
(( available >= 12884901888 )) || { echo 'Need at least 12GiB free for code-only build' >&2; exit 1; }
cp "$here"/{Dockerfile,runtime.lock,models.json,source.json,provision.py,schema_smoke.py,canary_gateway.py,start.sh} "$context/"
curl --fail --location --max-time 120 \
  https://codeload.github.com/Comfy-Org/ComfyUI/tar.gz/63e5bf594339f676b4b15e072529873e3448409e \
  --output "$context/comfyui.tar.gz"
echo "22ebca008dc6cbc8ab7cf2b456a3580a9195e3d81102f9d07d54c44b889f8257  $context/comfyui.tar.gz" | sha256sum -c -
docker build --pull=false --tag drama-pika-h3-flex:t031-native "$context"
