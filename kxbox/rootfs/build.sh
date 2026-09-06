#!/usr/bin/env sh
# Build the initramfs Tier 0 boots into.
#
#     ./kxbox/rootfs/build.sh
#
# The result is kxbox/rootfs/build/initrd.gz, which is one busybox, one strace, three small
# programs, one init script and four empty directories. It is not committed, the same as the
# kernel.
#
# This one needs no root. Everything in it is a regular file, a directory or a
# symlink, and the device nodes the kernel needs are made by devtmpfs before init runs, which is
# what CONFIG_DEVTMPFS_MOUNT in the teaching fragment is for. A rootfs that needed mknod would need
# root, and asking a reader for root to build a teaching image is a bad trade.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/build"
STAGE="$OUT/root"
PIN="$HERE/pin.toml"

# One reader for the whole pin file, called as `read_pin <section> <key>`. There were three of
# these, one per section, identical apart from the name in the middle, and a fourth was about to be
# written for strace. A list comes back space separated because that is what a shell loop wants.
read_pin() {
    python3 - "$PIN" "$1" "$2" <<'PY'
import sys, tomllib
value = tomllib.load(open(sys.argv[1], "rb"))[sys.argv[2]][sys.argv[3]]
print(" ".join(value) if isinstance(value, list) else value)
PY
}

# Fetch a file once and check it against the sha256 the pin records. Both things this image
# downloads come through here, and neither is used before the checksum has matched.
fetch() {
    url=$1
    into=$2
    want=$3
    if [ ! -f "$into" ]; then
        echo "fetching $url"
        curl -fL --progress-bar -o "$into.part" "$url"
        mv "$into.part" "$into"
    fi
    python3 - "$into" "$want" <<'PY'
import hashlib, sys
digest = hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()
if digest != sys.argv[2]:
    sys.exit(f"checksum mismatch, refusing to build a rootfs\n  wanted {sys.argv[2]}\n  got    {digest}")
print(f"checksum ok: {sys.argv[1].rsplit('/', 1)[-1]}")
PY
}

read_programs() { read_pin programs "$1"; }
read_modules() { read_pin modules "$1"; }
read_strace() { read_pin strace "$1"; }

VERSION=$(read_pin busybox version)
URL=$(read_pin busybox url)
SHA=$(read_pin busybox sha256)
APPLETS=$(read_pin busybox required_applets)
BUSYBOX="$OUT/busybox-$VERSION"

mkdir -p "$OUT"

fetch "$URL" "$BUSYBOX" "$SHA"

# What the binary says it can do, checked against what the bridge needs. The list of applets is in
# the binary itself, so this is asking it rather than trusting the version number.
python3 - "$BUSYBOX" "$APPLETS" <<'PY'
import re, sys
blob = open(sys.argv[1], "rb").read()
have = set(re.findall(rb"[a-z0-9_.\[\]-]{2,20}", blob))
missing = [one for one in sys.argv[2].split() if one.encode() not in have]
if missing:
    sys.exit("this busybox has no " + ", ".join(missing))
print(f"applets ok: {len(sys.argv[2].split())} of them present")
PY

rm -rf "$STAGE"
mkdir -p "$STAGE/bin" "$STAGE/dev" "$STAGE/proc" "$STAGE/sys" "$STAGE/tmp"

cp "$BUSYBOX" "$STAGE/bin/busybox"
chmod 755 "$STAGE/bin/busybox"

# The compiled things in the image. They need a cross compiler, so they need the container, which
# is the same one the kernel is built in. A machine with no docker still gets a working box, it
# just gets one where a fault or a write has to be traced the noisy way, so this warns instead of
# stopping. The kernel build is the thing that really needs docker and it says so itself.
SOURCES=$(read_programs sources)
if command -v docker >/dev/null 2>&1; then
    echo "compiling $SOURCES"
    BUILD=""
    for source in $SOURCES; do
        name=${source%.c}
        BUILD="$BUILD $(read_programs compiler) $(read_programs flags) -o /out/$name /rootfs/$source;"
        BUILD="$BUILD strip /out/$name 2>/dev/null || true;"
    done
    docker run --rm \
        -v "$HERE:/rootfs:ro" -v "$STAGE/bin:/out" \
        "$(read_programs image)" sh -eu -c "
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq >/dev/null
            apt-get install -y -qq --no-install-recommends $(read_programs packages) >/dev/null
            $BUILD
        "
    for source in $SOURCES; do
        name=${source%.c}
        chmod 755 "$STAGE/bin/$name"
        echo "$name: $(wc -c < "$STAGE/bin/$name") bytes"
    done
else
    echo "no docker, so none of $SOURCES in this image"
    echo "  without them: a page fault trace is thirty faults and a write trace is nine writes"
fi

# strace, built from the release tarball rather than downloaded as a binary, because nobody
# publishes a static i686 one and this project is not going to be the first.
#
# The result is cached beside busybox and reused, which matters more here than anywhere else in
# this file. The build is a configure and a make, it took thirty seven minutes the first time it
# ran on an arm laptop, and almost all of that is qemu translating x86 instructions one at a time.
# On an x86 machine it is a couple of minutes. Either way it happens once.
STRACE_VERSION=$(read_strace version)
STRACE="$OUT/strace-$STRACE_VERSION-i686"
if command -v docker >/dev/null 2>&1; then
    if [ ! -f "$STRACE" ]; then
        TARBALL="$OUT/strace-$STRACE_VERSION.tar.xz"
        fetch "$(read_strace url)" "$TARBALL" "$(read_strace sha256)"
        echo "building strace $STRACE_VERSION, which takes a while and then never happens again"
        docker run --rm -v "$OUT:/out" "$(read_strace image)" sh -eu -c "
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq >/dev/null
            apt-get install -y -qq --no-install-recommends $(read_strace packages) >/dev/null
            cd /tmp && tar xf /out/strace-$STRACE_VERSION.tar.xz && cd strace-$STRACE_VERSION
            ./configure $(read_strace configure) LDFLAGS=-static >/tmp/configure.log 2>&1 \
                || { tail -30 /tmp/configure.log; exit 1; }
            make -j4 >/tmp/make.log 2>&1 || { tail -40 /tmp/make.log; exit 1; }
            $(read_strace strip) src/strace
            cp src/strace /out/strace-$STRACE_VERSION-i686
        "
    fi
    cp "$STRACE" "$STAGE/bin/strace"
    chmod 755 "$STAGE/bin/strace"
    echo "strace: $STRACE_VERSION, $(wc -c < "$STRACE") bytes"
else
    echo "no docker, so no strace in this image"
    echo "  without it: nothing shows which system calls a program made, only what they did inside"
fi

# Any module somebody has built, copied in as it is. Nothing here compiles one, because a module
# needs the kernel tree and the kernel tree needs the container and the volume, which is what
# `kxbox/kernel/module.sh` is for. This just carries whatever is already on disk.
MODULES_INTO=$(read_modules into)
mkdir -p "$STAGE/$MODULES_INTO"
found=0
for where in $(read_modules look_in); do
    for one in "$HERE/../../$where"/*.ko; do
        [ -f "$one" ] || continue
        cp "$one" "$STAGE/$MODULES_INTO/"
        echo "module: $(basename "$one"), $(wc -c < "$one") bytes, from $where"
        found=$((found + 1))
    done
done
if [ "$found" -eq 0 ]; then
    echo "no modules built, so none in this image"
    echo "  without them: C09 cannot make its own splat and falls back to the committed one"
fi

# One symlink, because /init has a shebang and a shebang needs an interpreter that already exists.
# Every other applet is linked by busybox itself on the first line of init.
ln -sf busybox "$STAGE/bin/sh"

cp "$HERE/init" "$STAGE/init"
chmod 755 "$STAGE/init"

# newc is the only format the kernel's initramfs unpacker reads. Ownership is forced to root
# because the archive carries whichever uid built it, and a shell that cannot write to /tmp
# because the image was built on somebody's laptop is a confusing way to find that out.
(cd "$STAGE" && find . -print | cpio --quiet -o -H newc -R 0:0) | gzip -9 > "$OUT/initrd.gz"

echo
echo "initrd:  $OUT/initrd.gz, $(wc -c < "$OUT/initrd.gz") bytes"
echo "busybox: $VERSION, $(wc -c < "$BUSYBOX") bytes"
