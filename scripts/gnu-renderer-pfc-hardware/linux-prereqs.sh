#!/usr/bin/env bash
# Exercise the same unprivileged tracer and system C tools the structural observers use.
set -euo pipefail
export LC_ALL=C
mkdir -- "$1"
cd -- "$1"
dpkg-query -W binutils build-essential ca-certificates coreutils git grep strace util-linux zstd
for tool in ar as c++filt cc findmnt gh git ld python3 readelf sha256sum strace zstd rustup cargo rustc rustdoc; do
    command -v "$tool"
done
printf 'int main(void) { return 0; }\n' | cc -x c - -o probe
readelf -h ./probe
sha256sum ./probe
strace -f -qq -yy -s 1024 -e trace=execve,openat -o trace ./probe
grep -F 'execve("./probe"' trace | grep -E ' = 0$'
grep -E 'openat\(.*libc\.so\.6".* = [0-9]+<' trace
