#!/usr/bin/env bash
set -euo pipefail

pair=$1
kits="$RUNNER_TEMP/kits"
out="$RUNNER_TEMP/out"
mkdir "$out"
mkdir -p "$kits"
host=x86_64-unknown-linux-gnu
tag=ohm-1.100.0-2
name="$tag-$host.tar.gz"
packed="$kits/$name"
release="https://github.com/astral-experiments/ohm/releases/download/$tag/$name"
curl -fsSL --retry 4 "$release" -o "$packed"
echo "a6a1621e4581940e93ff7f9720b6102f6589185539650633a4235410f0bbd26d  $packed" | sha256sum -c -
tar -C "$kits" -xzf "$packed" --strip-components=3 "rust-1.100.0-dev-$host/cargo/bin/cargo"
echo "596f817cbe3af0c256c15b7db5df57f8bb456eb891c08c359f135b66a7ac7fde  $kits/cargo" | sha256sum -c -
sha256sum "$packed" > "$out/archives.sha256"
if [[ -n "${RUSTC_KITS:-}" ]]; then
  control="$kits/control"
  candidate="$kits/candidate"
  for role in control candidate; do
    sha256sum "$kits/$role.tar.zst" >> "$out/archives.sha256"
    tar --zstd -C "$kits" -xf "$kits/$role.tar.zst"
    (cd "$kits/$role" && sha256sum --quiet -c manifest.sha256)
    mkdir "$out/sdk-$role"
    cp "$kits/$role"/{bootstrap.toml,compiler.patch,manifest.sha256,revision,version.txt} "$out/sdk-$role/"
    if [[ -f "$kits/$role/bootstrap.patch" ]]; then
      cp "$kits/$role/bootstrap.patch" "$out/sdk-$role/"
    fi
  done
  # Earlier artifacts in this experiment all use the pinned epoch 5.
  control_epoch="$(cat "$control/epoch" 2>/dev/null || echo 5)"
  candidate_epoch="$(cat "$candidate/epoch" 2>/dev/null || echo 5)"
  echo "metadata epochs $control_epoch $candidate_epoch" > "$out/stdlib"
  if [[ "$candidate_epoch" == "$control_epoch" ]]; then
    mv "$candidate/lib/rustlib/$host/lib" "$kits/unused-std"
    cp -al "$control/lib/rustlib/$host/lib" "$candidate/lib/rustlib/$host/lib"
    echo 'Both compilers consume the control std' >> "$out/stdlib"
  else
    echo 'Each compiler consumes the std it built' >> "$out/stdlib"
  fi
else
  control="$kits/release"
  candidate="$control"
  tar -C "$kits" -xzf "$packed"
  "$kits/rust-1.100.0-dev-$host/install.sh" --prefix="$control" --disable-ldconfig
fi
candidate_cargo="$kits/cargo"
if [[ -n "${CARGO_KITS:-}" ]]; then
  sha256sum "$kits/cargo.tar.zst" >> "$out/archives.sha256"
  tar --zstd -C "$kits" -xf "$kits/cargo.tar.zst"
  (cd "$kits/cargo-kits" && sha256sum --quiet -c manifest.sha256)
  cmp "$kits/cargo-kits/source.patch" scripts/uv-check-instructions/salts-pilot.patch
  candidate_cargo="$kits/cargo-kits/candidate"
  mkdir "$out/cargo"
  cp "$kits/cargo-kits"/{source.patch,manifest.sha256,revision,version-*.txt} "$out/cargo/"
fi

if [[ "$(cat /proc/sys/kernel/perf_event_paranoid)" -gt 2 ]]; then
  sudo sysctl kernel.perf_event_paranoid=2
fi
lscpu > "$out/lscpu.txt"
export CARGO_HOME="$RUNNER_TEMP/registry"
first=control
if (( pair % 2 == 0 )); then
  first=candidate
fi
entry=run.py
extra=()
if [[ "${AUDIT_UV:-}" == 1 ]]; then
  extra+=(--audit)
fi
if [[ "${PROFILE_UV:-}" == 1 ]]; then
  if ! perf --version; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends linux-tools-generic
  fi
  entry=profile.py
fi
python3 -IS "scripts/uv-check-instructions/$entry" \
  --uv "$PWD/uv" \
  --control "$control" \
  --candidate "$candidate" \
  --cargo "$kits/cargo" \
  --candidate-cargo "$candidate_cargo" \
  --scratch "$RUNNER_TEMP/experiment" \
  --output "$out" \
  --first "$first" --jobs 4 "${extra[@]}"
