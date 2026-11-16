"""T031 R5a (RR-T1): the image entrypoint ``start.sh`` owns provisioning state.

Offline behavioral test of the POSIX sh entrypoint against a fake ``python``
shim: no docker, no network, no real ComfyUI. The script under test is the
recipe's real ``deployment/pika-h3-flex/start.sh`` with its roots overridden
through the documented env knobs (``PIKA_ROOT`` etc.); inside the image the
defaults keep ``/opt/pika``.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parents[3] / "deployment" / "pika-h3-flex"
START_SH = RECIPE / "start.sh"

# The fake interpreter dispatches on the basename of argv[1].
FAKE_PYTHON = """#!/bin/sh
# T031 R5a test double: gateway / provision.py / ComfyUI main.py are inert.
script=$(basename "$1")
case "$script" in
  canary_gateway.py)
    printf 'gateway\\n' >> "$MARKERS/calls"
    exec sleep 100000
    ;;
  provision.py)
    printf 'provision %s\\n' "$*" >> "$MARKERS/calls"
    sleep "${FAKE_PROVISION_SLEEP:-0}"
    if [ -n "$FAKE_PROVISION_STDERR" ]; then
      printf '%s' "$FAKE_PROVISION_STDERR" >&2
    fi
    exit "${FAKE_PROVISION_EXIT:-0}"
    ;;
  main.py)
    printf 'comfy %s\\n' "$*" >> "$MARKERS/calls"
    exec sleep 100000
    ;;
  *)
    printf 'unexpected %s\\n' "$1" >> "$MARKERS/calls"
    exit 99
    ;;
esac
"""


class StartShRun:
    """One ``start.sh`` subprocess under a controlled environment."""

    def __init__(self, tmp_path: Path, *, env_extra: dict[str, str]) -> None:
        self.root = tmp_path / "run"
        self.markers = self.root / "markers"
        self.pika = self.root / "pika"
        self.markers.mkdir(parents=True)
        self.pika.mkdir(parents=True)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").write_text(FAKE_PYTHON)
        (bin_dir / "python").chmod(0o755)
        # The script execs the gateway from an absolute path; stage inert stubs
        # so only the basename dispatch matters.
        (self.pika / "canary_gateway.py").write_text("# stub\n")
        (self.pika / "provision.py").write_text("# stub\n")
        (self.pika / "main.py").write_text("# stub\n")
        env = dict(os.environ)
        env.update(
            {
                "PATH": f"{bin_dir}:{env['PATH']}",
                "MARKERS": str(self.markers),
                "PIKA_ROOT": str(self.pika),
                "MICRODRAMA_GATEWAY": str(self.pika / "canary_gateway.py"),
                "MICRODRAMA_COMFY_MAIN": str(self.pika / "main.py"),
                "MICRODRAMA_PROVISION_STATE_FILE": str(self.pika / "state.json"),
            }
        )
        env.update(env_extra)
        # New session: stop() kills the whole process group - the backgrounded
        # gateway child must not outlive the test holding the pipes open.
        self.proc = subprocess.Popen(
            ["sh", str(START_SH)],
            env=env,
            cwd=str(self.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

    def calls(self) -> list[str]:
        path = self.markers / "calls"
        if not path.exists():
            return []
        return path.read_text().splitlines()

    def state(self) -> dict | None:
        target = self.pika / "state.json"
        if not target.exists():
            return None
        return json.loads(target.read_text())

    def wait_for(self, predicate, *, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                out, err = self.proc.communicate(timeout=5)
                raise AssertionError(
                    f"start.sh exited early ({self.proc.returncode}): {err.decode()[-500:]}"
                )
            try:
                if predicate():
                    return
            except Exception:
                pass
            time.sleep(0.05)
        raise AssertionError("timed out waiting for start.sh state")

    def stop(self) -> None:
        import signal

        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                self.proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.communicate(timeout=10)


@pytest.fixture()
def run_factory(tmp_path: Path):
    runs: list[StartShRun] = []

    def _run(**env_extra: str) -> StartShRun:
        item = StartShRun(tmp_path, env_extra=env_extra)
        runs.append(item)
        return item

    yield _run
    for item in runs:
        item.stop()


def test_rr_t1a_provisioned_path_execs_comfyui(run_factory) -> None:
    """(a) PROVISIONED -> ComfyUI exec'd with the pinned argument line."""
    run = run_factory(MICRODRAMA_PROVISION_MODELS="1", FAKE_PROVISION_EXIT="0")
    run.wait_for(lambda: any(c.startswith("comfy ") for c in run.calls()))
    assert any(c == "gateway" for c in run.calls())
    comfy = [c for c in run.calls() if c.startswith("comfy ")][0]
    assert (
        "--listen 127.0.0.1 --port 8189 --disable-api-nodes --disable-all-custom-nodes" in comfy
    ), f"ComfyUI argument line drifted: {comfy}"
    state = run.state()
    assert state is not None and state["state"] == "PROVISIONED"
    assert state["exit_code"] == 0
    assert "started_at" in state and "ended_at" in state
    # The provisioning call used the pinned manifest/destination/download shape.
    provision = [c for c in run.calls() if c.startswith("provision ")][0]
    assert "--manifest" in provision and "--download" in provision
    assert "--destination /opt/ComfyUI/models" in provision


def test_rr_t1b_provision_failed_never_starts_comfyui(run_factory) -> None:
    """(b) PROVISION_FAILED -> ComfyUI is never started; state stays failed."""
    run = run_factory(
        MICRODRAMA_PROVISION_MODELS="1",
        FAKE_PROVISION_EXIT="3",
        FAKE_PROVISION_STDERR="boom: /opt/ComfyUI/models refused",
    )
    run.wait_for(
        lambda: (state := run.state()) is not None and state["state"] == "PROVISION_FAILED"
    )
    # Give the script every chance to (wrongly) start ComfyUI after the failure.
    time.sleep(0.3)
    assert not any(c.startswith("comfy ") for c in run.calls()), run.calls()
    state = run.state()
    assert state["state"] == "PROVISION_FAILED"
    assert state["exit_code"] == 3
    # The stderr tail is captured (hex-encoded so no escaping ambiguity).
    assert state.get("stderr_tail_hex"), state


def test_rr_t1c_flag_absent_skips_provisioning_entirely(run_factory) -> None:
    """(c) flag absent -> no provisioning call, no state file, ComfyUI exec'd."""
    run = run_factory()
    run.wait_for(lambda: any(c.startswith("comfy ") for c in run.calls()))
    assert any(c == "gateway" for c in run.calls())
    assert not any(c.startswith("provision ") for c in run.calls())
    assert run.state() is None


def test_start_sh_state_transitions_through_provisioning(run_factory) -> None:
    """The state file is published as PROVISIONING before the download runs."""
    # A slow "download": block until the test drops the release file.
    run_root_holder: list[StartShRun] = []

    slow = run_factory(MICRODRAMA_PROVISION_MODELS="1", FAKE_PROVISION_SLEEP="1")
    run_root_holder.append(slow)
    slow.wait_for(lambda: (state := slow.state()) is not None and state["state"] == "PROVISIONING")
    assert slow.state()["state"] == "PROVISIONING"
    # FAKE_PROVISION_EXIT defaults to 0: the download finishes on its own.
    slow.wait_for(lambda: (state := slow.state()) is not None and state["state"] == "PROVISIONED")


def test_start_sh_is_executable_and_posix() -> None:
    text = START_SH.read_text()
    assert text.startswith("#!/bin/sh"), "start.sh must be a POSIX sh script"
    assert "PROVISION_FAILED" in text and "PROVISIONED" in text
    # The image default roots stay pinned to /opt/pika.
    assert "/opt/pika" in text
    assert "MICRODRAMA_PROVISION_MODELS" in text
