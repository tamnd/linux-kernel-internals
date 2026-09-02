#!/usr/bin/env sh
# Build the initramfs Tier 0 boots into.
#
#     ./kxbox/rootfs/build.sh
#
# The result is kxbox/rootfs/build/initrd.gz, which is one busybox, one init script and four empty
# directories. It is about half a megabyte and it is not committed, the same as the kernel.
#
# This one needs no container and no root. Everything in it is a regular file, a directory or a
# symlink, and the device nodes the kernel needs are made by devtmpfs before init runs, which is
# what CONFIG_DEVTMPFS_MOUNT in the teaching fragment is for. A rootfs that needed mknod would need
# root, and asking a reader for root to build a teaching image is a bad trade.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/build"
STAGE="$OUT/root"
PIN="$HERE/pin.toml"

read_pin() {
    python3 - "$PIN" "$1" <<'PY'
import sys, tomllib
pin = tomllib.load(open(sys.argv[1], "rb"))["busybox"]
value = pin[sys.argv[2]]
print(" ".join(value) if isinstance(value, list) else value)
PY
}

VERSION=$(read_pin version)
URL=$(read_pin url)
SHA=$(read_pin sha256)
APPLETS=$(read_pin required_applets)
BUSYBOX="$OUT/busybox-$VERSION"

mkdir -p "$OUT"

if [ ! -f "$BUSYBOX" ]; then
    echo "fetching $URL"
    curl -fL --progress-bar -o "$BUSYBOX.part" "$URL"
    mv "$BUSYBOX.part" "$BUSYBOX"
fi

python3 - "$BUSYBOX" "$SHA" <<'PY'
import hashlib, sys
digest = hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()
if digest != sys.argv[2]:
    sys.exit(f"checksum mismatch, refusing to build a rootfs\n  wanted {sys.argv[2]}\n  got    {digest}")
print("checksum ok")
PY

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
