#!/bin/bash
set -eu
# The cache checks /proc/self/maps against fstat on each loaded image.
# Give the runner's loader and the compiler regular files in a private mount.
scratch=/tmp/ohm-llvm-pmu
mkdir -p "$scratch"
mount -t tmpfs -o size=37G tmpfs "$scratch"
mkdir "$scratch/compiler"
mkdir "$scratch/work"
chown "$1" "$scratch/work"
chown "$1" "$scratch/compiler"
python3 - <<'PY'
import os
seen=set()
for line in open("/proc/self/maps"):
    address,mode,offset,device,inode,*rest=line.split()
    if not rest or rest[0] in seen or not rest[0].startswith("/"):continue
    path=rest[0]
    seen.add(path)
    id=os.stat(path)
    mapped=tuple(int(v,16) for v in device.split(":"))+(int(inode),)
    if (os.major(id.st_dev),os.minor(id.st_dev),id.st_ino)!=mapped: print("mapped image differs",path)
PY
for name in ld-linux-x86-64.so.2 libc.so.6 libm.so.6 libpthread.so.0 libdl.so.2 librt.so.1 libgcc_s.so.1 libstdc++.so.6 libz.so.1 libzstd.so.1 libffi.so.8 libtinfo.so.6 libxml2.so.2 libatomic.so.1 libutil.so.1 libmvec.so.1 liblzma.so.5 libicuuc.so.74 libicudata.so.74 libresolv.so.2; do
  path=/usr/lib/x86_64-linux-gnu/$name
  if [[ -e "$path" ]]; then
    cp -L "$path" "$scratch/$name"
    mount --bind "$scratch/$name" "$path"
  fi
done
exec runuser -u "$1" -- env -u LD_PRELOAD -u LD_AUDIT -u LD_LIBRARY_PATH -u CI -u GITHUB_ACTIONS RUNNER_TEMP="$scratch/work" PATH="$3" GITHUB_STEP_SUMMARY="$4" python3 -I pmuv.py "$2"
