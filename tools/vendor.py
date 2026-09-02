"""Fetch the emulator Tier 0 runs on, and check it against the pin.

    python3 -m tools.vendor                 fetch anything missing, verify everything
    python3 -m tools.vendor --check         verify what is on disk, download nothing
    python3 -m tools.vendor --force         fetch again even if the files are already there

v86 is a dependency in the same sense the kernel is a dependency. A different build of it is a
different machine, and a trace taken on a different machine is a different trace, so the version,
the commit it was built from and the checksum of every file all live in `kxbox/web/vendor.toml`.

The files are not committed. They are four megabytes of binary, and a repository that carries its
own dependencies is one nobody can tell apart from them. What is committed is the pin, which is
what makes the download reproducible.

Every file is checked after it lands. A download that is truncated or served from somewhere else
is not the emulator we pinned, and finding that out from a checksum is much better than finding it
out from a kernel that will not boot.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import sys
import tarfile
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PIN = Path("kxbox/web/vendor.toml")
INTO = Path("kxbox/web/vendor/v86")

TIMEOUT = 300


@dataclass(frozen=True)
class Want:
    """One file we expect to end up with, and what it has to hash to."""

    path: Path
    sha256: str
    source: str

    @property
    def present(self) -> bool:
        return self.path.exists()

    def actual(self) -> str:
        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()

    def ok(self) -> bool:
        return self.present and self.actual() == self.sha256


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:  # noqa: S310
        return answer.read()


def wanted(pin: dict, into: Path) -> list[Want]:
    """Everything the pin says should be on disk once this has run."""
    files = [
        Want(into / one["path"], one["sha256"], f"{pin['v86']['url']}!{one['member']}")
        for one in pin["v86"]["files"]
    ]
    files += [Want(into / one["name"], one["sha256"], one["url"]) for one in pin["bios"]]
    return files


def unpack(tarball: bytes, pin: dict, into: Path) -> None:
    """Take the three files we use out of the npm tarball and leave the rest of it alone."""
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        for one in pin["v86"]["files"]:
            member = archive.extractfile(one["member"])
            if member is None:
                raise SystemExit(f"{one['member']} is not in the tarball")
            (into / one["path"]).write_bytes(member.read())


def download(pin: dict, into: Path, force: bool = False) -> None:
    into.mkdir(parents=True, exist_ok=True)
    files = wanted(pin, into)

    if force or not all(one.present for one in files[: len(pin["v86"]["files"])]):
        url = pin["v86"]["url"]
        print(f"fetching {url}")
        tarball = fetch(url)
        got = digest(tarball)
        if got != pin["v86"]["sha256"]:
            raise SystemExit(
                f"the tarball does not match the pin, refusing to unpack it\n"
                f"  wanted {pin['v86']['sha256']}\n  got    {got}"
            )
        unpack(tarball, pin, into)

    for one in pin["bios"]:
        target = into / one["name"]
        if target.exists() and not force:
            continue
        print(f"fetching {one['url']}")
        blob = fetch(one["url"])
        got = digest(blob)
        if got != one["sha256"]:
            raise SystemExit(
                f"{one['name']} does not match the pin, not writing it\n"
                f"  wanted {one['sha256']}\n  got    {got}"
            )
        target.write_bytes(blob)


def check(pin: dict, into: Path) -> list[str]:
    """What is wrong, one line each, empty when the directory matches the pin."""
    wrong = []
    for one in wanted(pin, into):
        if not one.present:
            wrong.append(f"{one.path}: missing, run `python3 -m tools.vendor`")
        elif one.actual() != one.sha256:
            wrong.append(f"{one.path}: does not match the pin, delete it and fetch it again")
    return wrong


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=Path, default=PIN)
    parser.add_argument("--into", type=Path, default=INTO)
    parser.add_argument("--check", action="store_true", help="verify only, download nothing")
    parser.add_argument("--force", action="store_true", help="fetch again even if present")
    parser.add_argument("--clean", action="store_true", help="delete the vendored files")
    args = parser.parse_args(argv)

    pin = tomllib.loads(args.pin.read_text(encoding="utf-8"))

    if args.clean:
        shutil.rmtree(args.into, ignore_errors=True)
        print(f"removed {args.into}")
        return 0

    if not args.check:
        download(pin, args.into, force=args.force)

    wrong = check(pin, args.into)
    for line in wrong:
        print(line, file=sys.stderr)
    if wrong:
        return 1

    version = pin["v86"]["version"]
    matched = len(wanted(pin, args.into))
    print(f"vendor: v86 {version} in {args.into}, {matched} files match the pin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
