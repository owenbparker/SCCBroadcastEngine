"""A test of the whole relay on this PC, without going live anywhere.

A second RTMP server (on spare ports) gets a test pattern, as if OBS were
streaming, and three outputs (sent as it is, cropped to vertical,
re-encoded at a lower bitrate) push it back into that same server. When
all three arrive, MediaMTX, FFmpeg and the encoder all work here, so the
only things left that can stop a platform are its stream key and the
internet connection.

Used by the "Test on this PC" button and the build's smoke test.
"""

import os
import shutil
import socket
import tempfile
import threading
import time

from . import procs
from .config import tool
from .log import log
from .relay import Ingest, Relay
from .settings import CROP, ENCODE, Settings, new_destination

OUTPUTS = (("copy", "Sent as it is", None), ("crop", "Cropped to vertical", CROP), ("encode", "Re-encoded", ENCODE))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(timeout=60, rtmp_port=None, api_port=None):
    """Runs the test. Returns (ok, [(passed, text), ...])."""
    results = []

    def check(passed, text):
        results.append((bool(passed), text))
        return passed

    for name in ("mediamtx", "ffmpeg"):
        path = tool(name)
        if not check(os.path.isfile(path) or shutil.which(path), f"{name} found ({path})"):
            return False, results
    rtmp_port = rtmp_port or free_port()
    while not api_port or api_port == rtmp_port:
        api_port = free_port()
    work = tempfile.mkdtemp(prefix="sccms-test-")
    settings = Settings(os.path.join(work, "config.json"))
    out = f"rtmp://127.0.0.1:{rtmp_port}/out"
    settings.data["destinations"] = [
        new_destination("custom", id=i, name=label, enabled=True, server=out, key=i, bitrate=1500,
                        **({"video": mode} if mode else {}))
        for i, label, mode in OUTPUTS]
    relay = Relay(settings, Ingest(rtmp_port=rtmp_port, api_port=api_port, data_dir=work))
    publisher = None
    try:
        relay.start()
        if not check(relay.ingest.alive(), f"Test RTMP server started{' (' + relay.ingest.error + ')' if relay.ingest.error else ''}"):
            return False, results
        publisher = procs.popen([tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-re",
                                 "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                                 "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-pix_fmt", "yuv420p",
                                 "-c:a", "aac", "-t", str(timeout + 10), "-f", "flv",
                                 f"rtmp://127.0.0.1:{rtmp_port}/live/main"])
        deadline = time.monotonic() + timeout
        state = relay.state()
        while time.monotonic() < deadline:
            state = relay.state()
            outs = {o["id"]: o for o in state["outputs"]}
            if all(outs.get(i, {}).get("status") == "live" for i, _, _ in OUTPUTS) and \
                    {f"out/{i}" for i, _, _ in OUTPUTS} <= set(relay.ingest.paths):
                break
            time.sleep(1)
        ing = state["ingest"]
        check(ing["status"] == "live", f"Test stream received ({ing.get('kbps')} kbps, {' + '.join(ing.get('tracks') or []) or 'nothing'})")
        outs = {o["id"]: o for o in state["outputs"]}
        for i, label, _ in OUTPUTS:
            o = outs.get(i, {})
            arrived = f"out/{i}" in relay.ingest.paths
            detail = "arrived back" if o.get("status") == "live" and arrived else (o.get("message") or o.get("status") or "didn't start")
            check(o.get("status") == "live" and arrived, f"{label} output ({detail})")
        check(bool(relay.encoder), f"Encoder: {relay.encoder or 'none found'}")
    except Exception as e:
        check(False, f"Test stopped: {type(e).__name__}: {e}")
    finally:
        procs.stop(publisher)
        relay.stop()
        shutil.rmtree(work, ignore_errors=True)
    return all(p for p, _ in results), results


class Runner:
    """The panel's "Test on this PC" button: one test at a time, in the background."""

    def __init__(self):
        self.status = "idle"     # idle, running, passed, failed
        self.results = []
        self.finished = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self.status == "running":
                return
            self.status, self.results = "running", []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        log("Testing the relay on this PC (nothing goes live)…")
        try:
            ok, results = run()
        except Exception as e:
            ok, results = False, [(False, f"{type(e).__name__}: {e}")]
        self.results, self.finished = results, time.time()
        self.status = "passed" if ok else "failed"
        for passed, text in results:
            log(f"Test: {'OK' if passed else 'FAILED'} - {text}", "info" if passed else "error")
        log("Test passed: the relay works on this PC" if ok else "Test failed (see above)", "info" if ok else "error")

    def info(self):
        return {"status": self.status, "finished": self.finished,
                "results": [{"ok": p, "text": t} for p, t in self.results]}
