#!/bin/bash
# Called within a fresh private mount namespace. Programs run as the original unprivileged user.
set -euo pipefail
action=$1 work=$2 gccdir=$3 oldns=$4 uid=$5 gid=$6
shift 6
[[ $uid =~ ^[1-9][0-9]*$ && $gid =~ ^[0-9]+$ && $gccdir =~ ^/usr/lib/gcc/x86_64-linux-gnu/[0-9]+$ ]]
[[ "$(id -u)" == 0 && "$(readlink /proc/self/ns/mnt)" != "$oldns" ]]
[[ "$(findmnt -n -o PROPAGATION /)" == private && -f "$gccdir/libgcc.a" && ! -e "$gccdir/libutil.so" && ! -L "$gccdir/libutil.so" ]]
[[ -d "$work/system-copy/lower" && -d "$work/system-copy/earlier" ]]
mount --bind "$gccdir" "$work/system-copy/lower"
mount -o remount,bind,ro "$work/system-copy/lower"
mount -t overlay -o "ro,lowerdir=$work/system-copy/earlier:$work/system-copy/lower" overlay "$gccdir"
[[ "$(findmnt -rn -M "$gccdir" -o FSTYPE)" == overlay ]]
opts=$(findmnt -rn -M "$gccdir" -o OPTIONS)
[[ ,$opts, == *,ro,* ]]
cmp -- "$work/system-copy/lower/libgcc.a" "$gccdir/libgcc.a"
if [[ $action == probe ]]; then
    findmnt -rn -M "$gccdir" -o TARGET,SOURCE,FSTYPE,OPTIONS
    exit 0
fi
[[ $action == visit && -x $1 && -f $2 ]]
exec setpriv --reuid="$uid" --regid="$gid" --clear-groups --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs --     env RUNNER_TEMP="$(dirname "$work")" "$1" -IB -u "$2" visit "${@:3}"
