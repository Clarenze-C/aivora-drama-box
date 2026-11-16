"""Actual native CPU/no-weight node registration, not an inference receipt."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, '/opt/ComfyUI')
sys.argv = ['schema_smoke.py', '--cpu', '--disable-api-nodes']
import comfy.options
comfy.options.enable_args_parsing()
import nodes

MAPPED = ['UNETLoader', 'CLIPLoader', 'VAELoader', 'LoraLoaderModelOnly',
          'MiniMaxH3ReferenceToVideo', 'BasicGuider', 'KSamplerSelect',
          'ManualSigmas', 'RandomNoise', 'SamplerCustomAdvanced', 'VAEDecode',
          'VAEDecodeAudio', 'CreateVideo', 'SaveVideo', 'LoadImage', 'LoadAudio']


async def main():
    from server import PromptServer
    from app.assets.manager import default_asset_manager
    PromptServer(asyncio.get_running_loop(), default_asset_manager())
    await nodes.init_extra_nodes(init_custom_nodes=False, init_api_nodes=False)
    from aiohttp.test_utils import TestClient, TestServer
    server = PromptServer.instance
    server.app.add_routes(server.routes)
    async with TestClient(TestServer(server.app)) as client:
        response = await client.get('/object_info')
        assert response.status == 200
        raw_schemas = await response.json()
    schemas = {name: raw_schemas[name] for name in MAPPED}
    h3 = schemas['MiniMaxH3ReferenceToVideo']
    assert list(h3['output']) == ['CONDITIONING', 'LATENT']
    schema = nodes.NODE_CLASS_MAPPINGS['MiniMaxH3ReferenceToVideo'].INPUT_TYPES()
    from comfy_api.latest import _io as io
    # Exercise the real dynamic schema expansion with concrete API keys.
    expanded = io.get_finalized_class_inputs(schema, {
        'ref_images.ref_image_0': ['1', 0], 'ref_audios.ref_audio_0': ['2', 0]})
    assert 'ref_images.ref_image_0' in expanded[0]['optional']
    assert 'ref_audios.ref_audio_0' in expanded[0]['optional']
    save_expanded = io.get_finalized_class_inputs(nodes.NODE_CLASS_MAPPINGS['SaveVideo'].INPUT_TYPES(),
        {'format': 'mp4', 'format.codec': 'h264'})
    assert 'format.codec' in save_expanded[0]['required']
    assert 'minimax' in schemas['CLIPLoader']['input']['required']['type'][0]
    payload = {'evidence_kind': 'ACTUAL_RUNTIME_CPU_NO_WEIGHTS', 'inference_verified': False,
               'schemas': schemas, 'dynamic_inputs': str(expanded), 'save_video_dynamic_inputs': str(save_expanded), 'h3_input_types': schema}
    encoded = json.dumps(payload, sort_keys=True, default=str, allow_nan=False).encode()
    Path('/tmp/schema-smoke.json').write_bytes(encoded)
    print(json.dumps({'evidence_kind': payload['evidence_kind'], 'sha256': hashlib.sha256(encoded).hexdigest(), 'mapped_nodes': len(schemas)}))


if __name__ == '__main__':
    asyncio.run(main())
