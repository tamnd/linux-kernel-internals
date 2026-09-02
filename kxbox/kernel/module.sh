#!/usr/bin/env sh
# Build an out of tree module against a built profile of the pinned kernel.
#
#     ./kxbox/kernel/module.sh D-lockdep lessons/C09/assets
#
# The second argument is a directory with a `.c` file and a `Makefile` in it. What comes out is a
# `.ko` beside them, built for i386 against the same tree and the same toolchain that produced
# `build/$PROFILE/bzImage`.
#
# A module is not portable between two kernels that differ in configuration, even when they are
# the same version. `vermagic` is a string compiled into the module and compared at load time, and
# it carries the preemption model and a few other switches with it. So a module built here loads
# in the profile it was built against and is refused by the others, which is correct and is the
# reason this takes a profile name rather than assuming one.
#
# The tree lives in the same docker volume `build.sh` uses. This reconfigures it for the profile
# asked for, because the tree keeps whatever configuration was built in it last and a module built
# against the wrong one would load and then behave like a different kernel.

set -eu

PROFILE="${1:-D-lockdep}"
WHERE="${2:-lessons/C09/assets}"
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
VOLUME="${KXBOX_VOLUME:-kxbox-src}"

if [ ! -f "$HERE/build/$PROFILE/bzImage" ]; then
    echo "no build for $PROFILE yet, run ./kxbox/kernel/build.sh $PROFILE first"
    exit 1
fi

if [ ! -d "$ROOT/$WHERE" ]; then
    echo "no such directory: $WHERE"
    exit 1
fi

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
FRAGMENTS=$(read_pin fragments)

echo "profile: $PROFILE"
echo "kernel:  $VERSION"
echo "module:  $WHERE"

docker run --rm -i \
    -v "$ROOT:/work" \
    -v "$VOLUME:/src" \
    -w /src \
    -e PROFILE="$PROFILE" \
    -e VERSION="$VERSION" \
    -e FRAGMENTS="$FRAGMENTS" \
    -e WHERE="$WHERE" \
    -e DEBIAN_FRONTEND=noninteractive \
    debian:trixie-slim sh -eu <<'CONTAINER'
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    build-essential bc bison flex libelf-dev libssl-dev xz-utils \
    dwarves python3 kmod >/dev/null

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
    echo "no tree in the volume, run ./kxbox/kernel/build.sh $PROFILE first"
    exit 1
fi

cd "$SRC"
export KBUILD_BUILD_TIMESTAMP="@0"
export KBUILD_BUILD_USER=kxbox
export KBUILD_BUILD_HOST=kxbox
MAKE="make -s ARCH=i386 CROSS_COMPILE=$CROSS"

# The tree holds whatever configuration was built in it last, so put the asked for one back before
# touching anything. This is the same three steps build.sh takes, and it is cheap when the answer
# is already the right one.
$MAKE tinyconfig
./scripts/kconfig/merge_config.sh -m -O . .config \
    $(for f in $FRAGMENTS; do echo "/work/kxbox/kernel/$f"; done) >/dev/null
$MAKE olddefconfig

# `modules_prepare` builds the generated headers and the host tools kbuild needs. `modules` after
# it is what writes Module.symvers, which modpost reads to find out whether the symbols this
# module calls exist. Without it every module builds with a page of undefined symbol warnings and
# then fails to load, which is a bad way to find out.
$MAKE modules_prepare
$MAKE -j"$(nproc)" modules

# Copy the module source out of the shared folder and into the volume. Building in /work would
# write object files into the repository, and a kernel build reads its directory tens of thousands
# of times, which across a laptop virtual machine boundary is slow enough to notice.
rm -rf /src/module
mkdir -p /src/module
cp "/work/$WHERE"/*.c "/work/$WHERE"/Makefile /src/module/

$MAKE -C "$SRC" M=/src/module modules

for one in /src/module/*.ko; do
    cp "$one" "/work/$WHERE/"
    echo "built $(basename "$one"), $(wc -c < "$one") bytes"
done
CONTAINER

echo
echo "next: ./kxbox/rootfs/build.sh, which picks up any .ko it finds beside the lessons"
