#!/usr/bin/env bash
# Give the unchanged Cargo suite coherent dirent/stat identities on the same runner.
set -euo pipefail

base="$RUNNER_TEMP/cargo-ci-native-volume"
build="$RUNNER_TEMP/cargo-tests"
test ! -e "$base" && test ! -e "$build"
mkdir "$base"
(( $(df --output=avail -B1 "$base" | tail -1) > 64*1024**3 ))
image="$RUNNER_TEMP/cargo-ci-native.ext4"
test ! -e "$image"
truncate -s 32G "$image"
mkfs.ext4 -q -F -m 0 "$image"
if sudo -n mount -t ext4 -o loop,exec,nodev,nosuid "$image" "$base"; then
    backend=private-ext4
    sudo -n chown "$(id -u):$(id -g)" "$base"
elif sudo -n mount -t tmpfs -o size=28G,exec,nodev,nosuid,mode=0755 tmpfs "$base"; then
    backend=private-tmpfs
    sudo -n chown "$(id -u):$(id -g)" "$base"
else
    backend=existing-tmpfs
    base=$(mktemp -d /dev/shm/cargo-ci-301.XXXXXXXX)
fi
mkdir "$base/compiled" "$base/tmp"
if [[ $backend == existing-tmpfs ]]; then
    ln -s "$base/compiled" "$build"
else
    mkdir "$build"
    sudo -n mount --bind "$base/compiled" "$build"
fi
python3 -IB - "$backend" "$base" "$build" <<'PY'
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
backend, base, build = sys.argv[1:]
report = {'backend':backend,'mounts':{}}
for path in [Path(base)/'tmp', Path(build)]:
    capacity = shutil.disk_usage(path)
    assert capacity.free >= 22*1024**3
    with tempfile.TemporaryDirectory(dir=path) as tmp:
        p=Path(tmp)
        (p/'dir').mkdir(); shutil.copy2('/bin/true',p/'native')
        subprocess.run([str(p/'native')],check=True)
        entries=list(os.scandir(p)); assert all(e.inode()==os.lstat(e.path).st_ino for e in entries)
        assert len({os.lstat(e.path).st_dev for e in entries}|{p.stat().st_dev}) == 1
    report['mounts'][str(path)] = {'free':capacity.free,'device':path.stat().st_dev,
        'findmnt':subprocess.check_output(['findmnt','-T',str(path),'-n','-o','TARGET,SOURCE,FSTYPE']).decode().strip()}
assert os.stat(Path(base)/'compiled').st_ino == os.stat(build).st_ino
assert os.stat(Path(base)/'compiled').st_dev == os.stat(build).st_dev
print(json.dumps(report,sort_keys=True))
PY
echo "TMPDIR=$base/tmp" >> "$GITHUB_ENV"
