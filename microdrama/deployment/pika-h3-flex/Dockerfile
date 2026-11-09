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
# No startup model/dependency downloads, API nodes or third-party custom nodes.
EXPOSE 8188
ENTRYPOINT ["python", "/opt/ComfyUI/main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-api-nodes", "--disable-all-custom-nodes"]
