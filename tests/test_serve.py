"""The two headers, checked by asking a real server for a real file.

Worth a test rather than a reading, because getting these wrong does not look like a header
problem. The page loads, the emulator starts, and then `SharedArrayBuffer` is either missing or
useless, and the failure shows up as the Python side hanging forever on a call.
"""

from __future__ import annotations

import importlib.util
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "kxbox" / "web"


def load():
    """serve.py is a script beside the page rather than a module in a package."""
    spec = importlib.util.spec_from_file_location("kxbox_serve", WEB / "serve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


serve = load()


@pytest.fixture
def running(tmp_path):
    (tmp_path / "hello.txt").write_text("hi\n")
    (tmp_path / "v86.wasm").write_bytes(b"\0asm")

    from functools import partial

    handler = partial(serve.Isolated, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_page_is_told_it_may_block(running):
    with urllib.request.urlopen(f"{running}/hello.txt") as reply:
        headers = reply.headers
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert headers["Cross-Origin-Embedder-Policy"] == "require-corp"


def test_the_emulator_is_served_as_webassembly(running):
    """Served as text/plain it fails to instantiate, with a message nobody suspects a server for."""
    with urllib.request.urlopen(f"{running}/v86.wasm") as reply:
        assert reply.headers["Content-Type"] == "application/wasm"


def test_a_kernel_image_is_never_served_from_cache(running):
    with urllib.request.urlopen(f"{running}/hello.txt") as reply:
        assert reply.headers["Cache-Control"] == "no-store"


def test_the_page_exists_to_be_served():
    assert (WEB / "index.html").exists()
