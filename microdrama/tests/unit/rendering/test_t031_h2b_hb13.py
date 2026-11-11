"""HB-13 (Codex P1-P3 review): acceptance fixtures may not hide the production
failures they are meant to exclude.

The fake ComfyUI server lives only as long as its pod (spec §9.1): a harness
that couples the pod lifetime flips the server unreachable the moment its pod
stops or terminates, exactly like a real pod-side ComfyUI - no test can quietly
read output from a cleaned-up pod through a surviving fake.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rendering_support import RenderWorld

from microdrama.persistence import Database

pytestmark = pytest.mark.db


def test_hb13_fake_comfy_server_dies_with_its_pod(db: Database, tmp_path: Path):
    """§9.1: fake Comfy availability follows pod lifetime.

    While the pod runs, the pod-side server answers; the moment the manager
    stops the pod, every client call on that server is unreachable
    (TimeoutError) - recovery after cleanup can no longer "read output" from a
    pod that was cleaned up through a surviving fake."""

    from test_benchmark_experiments import _composed_world
    from test_t031_h2b_p2_gate import _lease_with_live_pod
    from test_t031_h2b_p3_ambiguity import _valid_fake_graph

    from microdrama.testing.fakes.comfy import FakeComfyClient

    world = RenderWorld(db)
    ep, plan, service, budget, comfy, adapter = _composed_world(world, tmp_path)
    lease_id = _lease_with_live_pod(db, world, ep.episode_id)
    with db.transaction(readonly=True) as tx:
        pod_id = tx.fetchval("SELECT pod_id FROM pod_leases WHERE id=%s", (lease_id,))
    assert pod_id is not None

    # Reachable while its pod runs (a queued prompt is visible through a
    # brand-new client connection to the same pod-side server).
    client = FakeComfyClient(comfy.server)
    prompt_id = client.queue_prompt(_valid_fake_graph(), client_id="hb13-lifetime")
    assert comfy.server.alive is True

    world.manager.stop(pod_id)  # the pod's compute is gone...
    assert comfy.server.alive is False  # ...and so is its pod-side ComfyUI
    for probe in (
        lambda: client.history(prompt_id),
        lambda: client.in_queue(prompt_id),
        lambda: client.progress_events(prompt_id),
        lambda: client.object_info(),
        lambda: client.find_prompt_id_by_client("hb13-lifetime"),
        lambda: client.queue_prompt(_valid_fake_graph(), client_id="hb13-after-stop"),
    ):
        with pytest.raises(TimeoutError):
            probe()
