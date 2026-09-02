"""Serve Tier 0 with the two headers the bridge needs.

    python3 kxbox/web/serve.py

It serves the whole `kxbox` directory rather than just `web`, because the page has to reach the
kernel image and the initramfs and those are built into `kernel/build` and `rootfs/build`. The
page itself is at `/web/`, which the startup message prints.

The Python side of the bridge blocks on `Atomics.wait` against a `SharedArrayBuffer`, and a
browser only hands out a working `SharedArrayBuffer` to a page that is cross origin isolated.
That takes two response headers, and `python3 -m http.server` does not send them, so the page
looks broken in a way that has nothing to do with the emulator. Hence this file.

The same two headers are the reason the interactive page cannot live on GitHub Pages, which is
written down in PROTOCOL.md rather than left to be found out.
"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# What cross origin isolation costs: the page may not be opened by a different origin, and every
# subresource has to opt in to being embedded. Both are enforced by the browser, not by us.
ISOLATION = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
}

# Serving .wasm as text/plain makes the emulator fail to instantiate with a message about the
# MIME type, which is not the first thing anybody suspects.
TYPES = {".wasm": "application/wasm", ".mjs": "text/javascript"}


class Isolated(SimpleHTTPRequestHandler):
    """A static file server that says the page may block."""

    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, **TYPES}

    def end_headers(self) -> None:
        for name, value in ISOLATION.items():
            self.send_header(name, value)
        # A kernel image is a large file and a stale one is a confusing one.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        # The default logs every byte range of every image, which buries the one line that matters.
        if not str(args[1] if len(args) > 1 else "").startswith("2"):
            super().log_message(fmt, *args)


# What the page fetches, and the command that makes each one. A missing image gives a boot that
# fails somewhere inside the emulator, which is a long way from the thing that is actually wrong.
NEEDED = {
    "web/vendor/v86/libv86.mjs": "python3 -m tools.vendor",
    "rootfs/build/initrd.gz": "sh kxbox/rootfs/build.sh",
    "kernel/build/A-full/bzImage": "sh kxbox/kernel/build.sh A-full",
}


def missing(root: Path = ROOT) -> list[str]:
    return [
        f"{what} is not there, run: {how}"
        for what, how in NEEDED.items()
        if not (root / what).exists()
    ]


def serve(directory: Path = ROOT, port: int = 8123) -> None:
    handler = partial(Isolated, directory=str(directory))
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        where = f"http://127.0.0.1:{server.server_address[1]}/web/"
        print(f"kxbox: serving {directory} on {where}")
        print("kxbox: cross origin isolated, so the worker can block on the emulator")
        for line in missing(directory):
            print(f"kxbox: {line}")
        server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="serve.py", description="Serve Tier 0 with COOP and COEP.")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--directory", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    try:
        serve(args.directory, args.port)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
