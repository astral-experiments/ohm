#!/usr/bin/env bash
set -euo pipefail

pair=$1
kits="$RUNNER_TEMP/kits"
out="$RUNNER_TEMP/out"
mkdir "$out"
mkdir -p "$kits"
host=x86_64-unknown-linux-gnu
tag=ohm-1.100.0-3
name="$tag-$host.tar.gz"
packed="$kits/$name"
release="https://github.com/astral-experiments/ohm/releases/download/$tag/$name"
curl -fsSL --retry 4 "$release" -o "$packed"
echo "7fc3d21a5efad6bff7be654b14e0e60aa2fbbfd11db198582788f3cc4bcf7591  $packed" | sha256sum -c -
tar -C "$kits" -xzf "$packed" --strip-components=3 "rust-1.100.0-dev-$host/cargo/bin/cargo"
sha256sum "$packed" > "$out/archives.sha256"
if [[ -n "${RUSTC_KITS:-}" ]]; then
  control="$kits/control"
  candidate="$kits/candidate"
  roles=(control candidate)
  if [[ "${PROBE_UV:-}" == 1 ]]; then
    roles=(candidate)
    control="$candidate"
  fi
  for role in "${roles[@]}"; do
    if [[ "${PROBE_UV:-}" == 1 ]]; then
      sha256sum "$RUNNER_TEMP/packages/$role.tar.zst" >> "$out/archives.sha256"
    else
      sha256sum "$kits/$role.tar.zst" >> "$out/archives.sha256"
      tar --zstd -C "$kits" -xf "$kits/$role.tar.zst"
    fi
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
  if [[ "$candidate_epoch" == "$control_epoch" && "$control" != "$candidate" ]]; then
    mv "$candidate/lib/rustlib/$host/lib" "$kits/unused-std"
    cp -al "$control/lib/rustlib/$host/lib" "$candidate/lib/rustlib/$host/lib"
    echo 'Both compilers consume the control std' >> "$out/stdlib"
    if [[ -z "${REFERENCE_PAIR:-}" ]]; then
      cp "$control/bin/rustc" "$candidate/bin/rustc"
      sha256sum "$control/bin/rustc" | cut -d' ' -f1 > "$out/common-launcher"
    fi
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
  cmp "$kits/cargo-kits/source.patch" scripts/project-check-instructions/salts-pilot.patch
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
load_reference() {
  local role=$1 packed_role=$2
  sha256sum "$kits/$packed_role.tar.zst" >> "$out/archives.sha256"
  mkdir "$kits/$role"
  tar --zstd -C "$kits/$role" --strip-components=1 -xf "$kits/$packed_role.tar.zst"
  (cd "$kits/$role" && sha256sum --quiet -c manifest.sha256)
  mkdir "$out/sdk-$role"
  cp "$kits/$role"/{bootstrap.toml,bootstrap.patch,compiler.patch,manifest.sha256,revision,version.txt} "$out/sdk-$role/"
  if [[ "$(cat "$kits/$role/epoch")" == "$control_epoch" ]]; then
    mv "$kits/$role/lib/rustlib/$host/lib" "$kits/unused-$role-std"
    cp -al "$control/lib/rustlib/$host/lib" "$kits/$role/lib/rustlib/$host/lib"
    echo "$role consumes the control std" >> "$out/stdlib"
  else
    echo "$role consumes the std it built" >> "$out/stdlib"
  fi
  extra+=(--"$role" "$kits/$role")
}
if [[ -n "${REFERENCE_PAIR:-}" || -n "${INTERMEDIATE_KIT:-}" ]]; then
  test -n "${RUSTC_KITS:-}"
  extra+=(--pair "$pair")
  if [[ -n "${REFERENCE_PAIR:-}" ]]; then
    load_reference release references/control
    load_reference current references/candidate
  fi
  if [[ -n "${INTERMEDIATE_KIT:-}" ]]; then
    load_reference intermediate pr/candidate
    if [[ -n "${SECOND_KIT:-}" ]]; then
      load_reference second pr2/candidate
    fi
  fi
  if [[ -n "${REFERENCE_PAIR:-}" ]]; then
    # This independent replay uses the release's exact std, as in the original
    # −2 comparison. The primary matched six-VM run uses the #318 std.
    std="$kits/unused-release-std"
    test -d "$std"
    for role in release control current intermediate second candidate; do
      [[ -d "$kits/$role" ]] || continue
      test "$(cat "$kits/$role/epoch")" = "$control_epoch"
      mv "$kits/$role/lib/rustlib/$host/lib" "$kits/intermediate-std-$role"
      cp -al "$std" "$kits/$role/lib/rustlib/$host/lib"
    done
    echo 'All compilers consume the release std' > "$out/stdlib"
    # Keep the allocator and launcher identical. The SDK manifests captured
    # above describe the original builds, before substituting the launcher.
    launcher="$kits/release/bin/rustc"
    sha256sum "$launcher" | cut -d' ' -f1 > "$out/common-launcher"
    for role in control current intermediate second candidate; do
      [[ -d "$kits/$role" ]] || continue
      cp "$launcher" "$kits/$role/bin/rustc"
      cmp "$launcher" "$kits/$role/bin/rustc"
    done
  fi
fi
if [[ "${PROBE_UV:-}" == 1 ]]; then
  extra+=(--probe)
fi
if [[ "${AUDIT_UV:-}" == 1 ]]; then
  extra+=(--audit)
elif [[ "${AUDIT_UV:-}" == control ]]; then
  extra+=(--audit --audit-role control)
fi
if [[ "${PROFILE_UV:-}" == 1 ]]; then
  if ! perf --version; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends linux-tools-generic
  fi
  entry=profile.py
fi
python3 -IS "scripts/project-check-instructions/$entry" \
  --project "$PROJECT" --source "$PWD/workload" \
  --control "$control" \
  --candidate "$candidate" \
  --cargo "$kits/cargo" \
  --candidate-cargo "$candidate_cargo" \
  --scratch "$RUNNER_TEMP/experiment" \
  --output "$out" \
  --first "$first" --jobs 4 "${extra[@]}"
