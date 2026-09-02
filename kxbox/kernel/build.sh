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
# The tree is unpacked into a docker volume rather than into the repository. A kernel tree is about
# ninety thousand files and a shared folder on a laptop virtual machine reads every one of them
# slowly, so the same build takes hours across the mount and minutes inside the volume. Only the
# tarball and the finished image cross the boundary.
#
#     docker volume rm kxbox-src
#
# is how you throw the tree away when you are done with it.

set -eu

PROFILE="${1:-A-full}"
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
OUT="$HERE/build/$PROFILE"
CACHE="$HERE/build/cache"
VOLUME="${KXBOX_VOLUME:-kxbox-src}"

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

docker volume create "$VOLUME" >/dev/null

docker run --rm -i \
    -v "$ROOT:/work" \
    -v "$CACHE:/cache" \
    -v "$VOLUME:/src" \
    -w /src \
    -e PROFILE="$PROFILE" \
    -e VERSION="$VERSION" \
    -e FRAGMENTS="$FRAGMENTS" \
    -e DEBIAN_FRONTEND=noninteractive \
    debian:trixie-slim sh -eu <<'CONTAINER'
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    build-essential bc bison flex libelf-dev libssl-dev xz-utils \
    dwarves python3 kmod >/dev/null

# The kernel is 32-bit x86 because that is the machine v86 gives us. On an x86 host the native
# compiler builds it. On anything else there has to be a cross compiler, and saying which one was
# used is part of the result rather than a detail, because two images built by two compilers are
# two different kernels even when the source and the config are identical.
HOST=$(uname -m)
case "$HOST" in
    x86_64 | i?86)
        CROSS=""
        ;;
    *)
        apt-get install -y -qq --no-install-recommends gcc-i686-linux-gnu >/dev/null
        CROSS="i686-linux-gnu-"
        ;;
esac

SRC="/src/linux-$VERSION"
if [ ! -d "$SRC" ]; then
    echo "unpacking"
    tar -C /src -xf "/cache/linux-$VERSION.tar.xz"
fi

cd "$SRC"
export KBUILD_BUILD_TIMESTAMP="@0"
export KBUILD_BUILD_USER=kxbox
export KBUILD_BUILD_HOST=kxbox
MAKE="make -s ARCH=i386 CROSS_COMPILE=$CROSS"

$MAKE tinyconfig
./scripts/kconfig/merge_config.sh -m -O . .config \
    $(for f in $FRAGMENTS; do echo "/work/kxbox/kernel/$f"; done) >/dev/null
$MAKE olddefconfig

# What Kconfig actually did with the fragments, which is not the same as what they asked for.
cp .config "/work/kxbox/kernel/build/$PROFILE/config"

STARTED=$(date +%s)
$MAKE -j"$(nproc)" bzImage
ELAPSED=$(( $(date +%s) - STARTED ))

cp arch/x86/boot/bzImage "/work/kxbox/kernel/build/$PROFILE/bzImage"
cp vmlinux "/work/kxbox/kernel/build/$PROFILE/vmlinux"

# What actually built this, written next to it, so that a measurement can never drift away from
# the toolchain that produced it.
{
    echo "host_arch = \"$HOST\""
    echo "cross_compile = \"$CROSS\""
    echo "compiler = \"$(${CROSS}gcc --version | head -1)\""
    echo "binutils = \"$(${CROSS}ld --version | head -1)\""
    echo "pahole = \"$(pahole --version 2>/dev/null || echo absent)\""
    echo "build_seconds = $ELAPSED"
} > "/work/kxbox/kernel/build/$PROFILE/toolchain.toml"
CONTAINER

(cd "$ROOT" && python3 -m tools.kconfig --profile "$PROFILE" --verify "$OUT/config")

echo
echo "bzImage: $(wc -c < "$OUT/bzImage") bytes"
echo "next:    record the boot measurement in kxbox/kernel/RESULTS.md"
