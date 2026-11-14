FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime@sha256:7b324d212a4450795b49edba9949b7cdc72429148a64e974334bfe5774d51385
LABEL org.opencontainers.image.source="https://github.com/Comfy-Org/ComfyUI" \
      org.opencontainers.image.revision="63e5bf594339f676b4b15e072529873e3448409e"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/ComfyUI
# Archive is downloaded by build.sh, then independently verified in this layer.
COPY comfyui.tar.gz /tmp/comfyui.tar.gz
RUN echo '22ebca008dc6cbc8ab7cf2b456a3580a9195e3d81102f9d07d54c44b889f8257  /tmp/comfyui.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/comfyui.tar.gz --strip-components=1 -C /opt/ComfyUI \
    && rm /tmp/comfyui.tar.gz
COPY runtime.lock /opt/pika/runtime.lock
RUN python -m pip install --no-cache-dir --no-deps -r /opt/pika/runtime.lock && python -m pip check
COPY models.json source.json provision.py schema_smoke.py /opt/pika/
# T031 R5a: start.sh is the entrypoint. It starts the token gateway, runs the
# pinned weight provisioning only when env MICRODRAMA_PROVISION_MODELS=1
# (set at pod-create time by the pipeline's provisioning flag; no secret), and
# execs ComfyUI exactly as the pinned base did - never on PROVISION_FAILED.
COPY start.sh /opt/pika/start.sh
RUN chmod 0755 /opt/pika/start.sh
# CN-5 (2026-11-09, canary-night review): the exposed port is a token-checking
# gateway (stdlib only - the locked runtime gains no dependencies); ComfyUI
# binds 127.0.0.1:8189 ONLY and the gateway refuses every request without the
# run's bearer token (env MICRODRAMA_COMFY_TOKEN, set at pod-create time from
# the pipeline's credential ref - no secret in the image). The gateway fails
# closed (401 without a token, 502 while ComfyUI boots) and serves the
# provisioning readiness state on /__drama/ready (T031 R5a).
COPY canary_gateway.py /opt/canary_gateway.py
# No startup model/dependency downloads unless the provisioning flag is set;
# no API nodes or third-party custom nodes.
EXPOSE 8188
ENTRYPOINT ["/opt/pika/start.sh"]
