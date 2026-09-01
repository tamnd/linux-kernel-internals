#!/usr/bin/env sh
# Build one profile of the pinned kernel, in a container, so that two people who run this get the
# same image.
#
#     ./kxbox/kernel/build.sh A-full
#     ./kxbox/kernel/build.sh D-lockdep
#
# The container is the only reason this is reproducible. A kernel built with a different gcc, a
# different binutils or a different pahole is a different kernel, and BTF in particular changes
# with the pahole version. Those three are pinned in pin.toml and installed here by name.
#
# Nothing about this has been run yet. It is written down first because a build recipe that lives
# in somebody's shell history is not a pinned kernel, and because the first person to run it
# should be following instructions rather than reconstructing them.

set -eu

PROFILE="${1:-A-full}"
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
OUT="$HERE/build/$PROFILE"
CACHE="$HERE/build/cache"

read_pin() {
    python3 - "$HERE/pin.toml" "$PROFILE" "$1" <<'PY'
import sys, tomllib
pin = tomllib.load(open(sys.argv[1], "rb"))
profile = next(p for p in pin["profiles"] if p["name"] == sys.argv[2])
field = sys.argv[3]
if field == "fragments":
    print(" ".join(profile["fragments"]))
elif field in profile:
    print(profile[field])
else:
    print(pin[profile["kernel"]][field])
PY
}

VERSION=$(read_pin version)
URL=$(read_pin url)
SHA=$(read_pin sha256)
FRAGMENTS=$(read_pin fragments)
TARBALL="$CACHE/linux-$VERSION.tar.xz"

echo "profile:   $PROFILE"
echo "kernel:    $VERSION"
echo "fragments: $FRAGMENTS"

mkdir -p "$CACHE" "$OUT"

if [ ! -f "$TARBALL" ]; then
    echo "fetching $URL"
    curl -fL --progress-bar -o "$TARBALL.part" "$URL"
    mv "$TARBALL.part" "$TARBALL"
fi

# Verify before unpacking, not after. A tarball that does not match the pin is not our kernel, and
# the point of pinning it was to be able to say that. Done in python because the checksum tool is
# called something different on every machine this might run on.
python3 - "$TARBALL" "$SHA" <<'PY'
import hashlib, sys
digest = hashlib.sha256()
with open(sys.argv[1], "rb") as handle:
    for block in iter(lambda: handle.read(1 << 20), b""):
        digest.update(block)
if digest.hexdigest() != sys.argv[2]:
    sys.exit(f"checksum mismatch, refusing to build\n  wanted {sys.argv[2]}\n  got    {digest.hexdigest()}")
print("checksum ok")
PY

docker run --rm -i \
    -v "$ROOT:/work" \
    -v "$CACHE:/cache" \
    -w /work \
    -e PROFILE="$PROFILE" \
    -e VERSION="$VERSION" \
    -e FRAGMENTS="$FRAGMENTS" \
    debian:trixie-slim sh -eu <<'CONTAINER'
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    build-essential bc bison flex libelf-dev libssl-dev xz-utils \
    dwarves gcc-14 python3 kmod >/dev/null

SRC="/cache/linux-$VERSION"
if [ ! -d "$SRC" ]; then
    echo "unpacking"
    tar -C /cache -xf "/cache/linux-$VERSION.tar.xz"
fi

cd "$SRC"
export ARCH=i386
export KBUILD_BUILD_TIMESTAMP="@0"
export KBUILD_BUILD_USER=kxbox
export KBUILD_BUILD_HOST=kxbox

make -s ARCH=i386 tinyconfig
./scripts/kconfig/merge_config.sh -m -O . .config \
    $(for f in $FRAGMENTS; do echo "/work/kxbox/kernel/$f"; done)
make -s ARCH=i386 olddefconfig

# What Kconfig actually did with the fragments, which is not the same as what they asked for.
cp .config "/work/kxbox/kernel/build/$PROFILE/config"

make -s ARCH=i386 -j"$(nproc)" bzImage
cp arch/x86/boot/bzImage "/work/kxbox/kernel/build/$PROFILE/bzImage"
cp vmlinux "/work/kxbox/kernel/build/$PROFILE/vmlinux"
CONTAINER

(cd "$ROOT" && python3 -m tools.kconfig --profile "$PROFILE" --verify "$OUT/config")

echo
echo "bzImage: $(wc -c < "$OUT/bzImage") bytes"
echo "next:    record the boot measurement in kxbox/kernel/RESULTS.md"
