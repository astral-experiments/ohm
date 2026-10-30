#!/usr/bin/env bash
set -euo pipefail

test "$(uname -sm)" = "Linux x86_64"
test -n "$RUNNER_TEMP"
test -n "$GITHUB_ENV"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  gcc-aarch64-linux-gnu g++-aarch64-linux-gnu libc6-dev-arm64-cross qemu-user \
  strace zstd cmake ninja-build pkg-config perl libssl-dev

root="$RUNNER_TEMP/ohm-aarch64-linux-zmij"
mkdir -p "$root/receipts" "$root/inbox"
release=ohm-1.99.0-20
archive="$release-x86_64-unknown-linux-gnu"
gh release download "$release" --repo astral-experiments/ohm --dir "$root/inbox" \
  --pattern "$archive.tar.gz" --pattern "$archive.tar.gz.sha256" --pattern "$archive-provenance.json"
dpkg-query -W gcc-aarch64-linux-gnu g++-aarch64-linux-gnu libc6-dev-arm64-cross qemu-user strace \
  cmake binutils gcc python3 zstd > "$root/receipts/host-packages.tsv"
printf '%s\n' "QA_ROOT=$root" \
  'CC_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-gcc' \
  'CXX_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-g++' \
  'AR_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-ar' >> "$GITHUB_ENV"
