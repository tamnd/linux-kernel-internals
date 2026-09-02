#!/usr/bin/env sh
# Unpack the pinned kernel source, so that citations have something to resolve against.
#
#     ./kxbox/kernel/tree.sh              unpack into kxbox/kernel/build/tree
#     ./kxbox/kernel/tree.sh /some/where  unpack somewhere else
#
# This is the pristine tarball, not the tree the build used. That matters. A built tree has object
# files and generated headers in it, and a citation that resolved against a generated header would
# resolve for the person who built the kernel and for nobody else. What comes out of here is what
# comes out of kernel.org, checked against the same sha256 the build checks.
#
# It takes a few minutes and about 1.6 GB. `build/` is ignored by git, so nothing here gets
# committed, and `rm -rf` on the directory is how you get the space back.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
CACHE="$HERE/build/cache"
INTO="${1:-$HERE/build/tree}"

read_pin() {
    python3 - "$HERE/pin.toml" "$1" <<'PY'
import sys, tomllib
pin = tomllib.load(open(sys.argv[1], "rb"))
print(pin["kernel"][sys.argv[2]])
PY
}

VERSION=$(read_pin version)
URL=$(read_pin url)
SHA=$(read_pin sha256)
TARBALL="$CACHE/linux-$VERSION.tar.xz"

mkdir -p "$CACHE"

if [ ! -f "$TARBALL" ]; then
    echo "fetching $URL"
    curl -fL --progress-bar -o "$TARBALL.part" "$URL"
    mv "$TARBALL.part" "$TARBALL"
fi

# The same check the build does. A tarball that does not match the pin is not our kernel, and a
# citation resolved against the wrong kernel is worse than one that was never resolved.
GOT=$(shasum -a 256 "$TARBALL" | cut -d' ' -f1)
if [ "$GOT" != "$SHA" ]; then
    echo "checksum mismatch"
    echo "  wanted $SHA"
    echo "  got    $GOT"
    exit 1
fi
echo "checksum ok"

if [ -d "$INTO/linux-$VERSION" ]; then
    echo "tree:  $INTO/linux-$VERSION, already unpacked"
else
    echo "unpacking into $INTO, this takes a few minutes"
    mkdir -p "$INTO"
    tar -C "$INTO" -xf "$TARBALL"
fi

echo
echo "tree:  $INTO/linux-$VERSION"
echo "next:  python3 -m tools.refcheck --tree $INTO/linux-$VERSION --confirm"
