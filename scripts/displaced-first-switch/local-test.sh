#!/bin/bash
# Private mount namespace for synthetic codec tests only. Donors are read-only.
set -euo pipefail
D=$(dirname "$(readlink -f "$0")")
case "$D" in
 /home/dev-user/.cache/ohm-branch-displaced-table-feasibility-20261031/probe-v1|/home/dev-user/code/oss/ohm-package-qa-branch-displaced-tables-20261031/scripts/displaced-first-switch) ;;
 *) exit 2 ;;
esac
W="$D/mount"
S=/mnt/devbox-scratch/dev-user/ohm-gnu-renderer-notebook-holdout-20261031-v1/pfc-signed-contact/donor
R=/home/dev-user/.cargo/registry
[[ $(id -u) == 0 && "$PWD" == "$D" && -d "$W" && -z $(ls -A "$W") && $(stat -c %u "$D") == 1000 ]]
[[ $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) -gt 17000000 && $(df -B1 --output=avail /mnt/devbox-scratch | tail -1) -gt 4294967296 ]]
mount --make-rprivate /
mount -t tmpfs -o size=384M,nr_inodes=30000,nosuid,nodev,mode=0700,uid=1000,gid=1000 displaced-codec-control "$W"
for p in "$S" "$R"; do mount --bind "$p" "$p"; mount -o remount,bind,ro "$p"; done
/usr/bin/setpriv --reuid=1000 --regid=1000 --init-groups --no-new-privs -- /usr/bin/env -i HOME="$W" PATH=/home/dev-user/.cargo/bin:/usr/local/bin:/usr/bin:/bin /usr/bin/nice -n 10 /usr/bin/python3 -IBu "$D/local-test.py" "$W" "$S" "$R"
# Two filesystems below overlay reproduce Linux's documented distinct regular-file st_dev.
mkdir -p "$W/overlay-lower" "$W/overlay-upper" "$W/merged"
mount -t tmpfs -o size=8M,nosuid,nodev tmpfs "$W/overlay-lower"
mount -t tmpfs -o size=8M,nosuid,nodev tmpfs "$W/overlay-upper"
mkdir -p "$W/overlay-upper/u" "$W/overlay-upper/w"
mount -t overlay overlay -o "lowerdir=$W/overlay-lower,upperdir=$W/overlay-upper/u,workdir=$W/overlay-upper/w,xino=off,index=off" "$W/merged"
mkdir -p "$W/merged"/{target,build,displaced-shadow,other}
printf 'old regular\n' >"$W/merged/target/old"
printf 'new regular\n' >"$W/merged/displaced-shadow/new"
printf 'foreign regular\n' >"$W/merged/other/foreign"
test $(stat -c %d "$W/merged") != $(stat -c %d "$W/merged/target/old")
python3 -IB "$D/test_mount.py" "$W/merged" positive
mount --bind "$W/merged/other/foreign" "$W/merged/displaced-shadow/new"
python3 -IB "$D/test_mount.py" "$W/merged" bound
umount "$W/merged/displaced-shadow/new"
ln "$W/merged/target/old" "$W/merged/displaced-shadow/unsound"
python3 -IB "$D/test_mount.py" "$W/merged" hardlinked
