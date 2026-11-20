#!/usr/bin/env bash
set -euo pipefail

pair=$1
kits="$RUNNER_TEMP/kits"
out="$RUNNER_TEMP/out"
mkdir "$out"
host=x86_64-unknown-linux-gnu
tag=ohm-1.100.0-2
name="$tag-$host.tar.gz"
packed="$kits/$name"
release="https://github.com/astral-experiments/ohm/releases/download/$tag/$name"
curl -fsSL --retry 4 "$release" -o "$packed"
echo "a6a1621e4581940e93ff7f9720b6102f6589185539650633a4235410f0bbd26d  $packed" | sha256sum -c -
tar -C "$kits" -xzf "$packed" --strip-components=3 "rust-1.100.0-dev-$host/cargo/bin/cargo"
echo "596f817cbe3af0c256c15b7db5df57f8bb456eb891c08c359f135b66a7ac7fde  $kits/cargo" | sha256sum -c -
for role in control candidate; do
  sha256sum "$kits/$role.tar.zst" >> "$out/archives.sha256"
  tar --zstd -C "$kits" -xf "$kits/$role.tar.zst"
  (cd "$kits/$role" && sha256sum --quiet -c manifest.sha256)
  mkdir "$out/sdk-$role"
  cp "$kits/$role"/{bootstrap.toml,compiler.patch,manifest.sha256,revision,version.txt} "$out/sdk-$role/"
done
# Both arms read the same standard library.
mv "$kits/candidate/lib/rustlib/$host/lib" "$kits/unused-std"
cp -al "$kits/control/lib/rustlib/$host/lib" "$kits/candidate/lib/rustlib/$host/lib"

if [[ "$(cat /proc/sys/kernel/perf_event_paranoid)" -gt 2 ]]; then
  sudo sysctl kernel.perf_event_paranoid=2
fi
lscpu > "$out/lscpu.txt"
export CARGO_HOME="$RUNNER_TEMP/registry"
first=control
if (( pair % 2 == 0 )); then
  first=candidate
fi
python3 -IS scripts/uv-check-instructions/run.py \
  --uv "$PWD/uv" \
  --control "$kits/control" \
  --candidate "$kits/candidate" \
  --cargo "$kits/cargo" \
  --scratch "$RUNNER_TEMP/experiment" \
  --output "$out" \
  --first "$first" --jobs 4
