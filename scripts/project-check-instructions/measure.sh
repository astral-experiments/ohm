#!/usr/bin/env bash
set -euo pipefail

pair=$1
kits="$RUNNER_TEMP/kits"
out="$RUNNER_TEMP/out"
mkdir "$out"
mkdir -p "$kits"
host=x86_64-unknown-linux-gnu
tag=ohm-1.100.0-3
digest=7fc3d21a5efad6bff7be654b14e0e60aa2fbbfd11db198582788f3cc4bcf7591
if [[ "${RELEASE4:-}" == true ]]; then
  tag=ohm-1.100.0-4
  digest=${LINUX_SHA:-09c701b4a1f6b196d51164e8392adafc2304f7e2c759d2aa524d5c42d2178943}
fi
name="$tag-$host.tar.gz"
packed="$kits/$name"
release="https://github.com/astral-experiments/ohm/releases/download/$tag/$name"
if [[ ! -f "$packed" ]]; then
  curl -fsSL --retry 4 "$release" -o "$packed"
fi
echo "$digest  $packed" | sha256sum -c -
tar -C "$kits" -xzf "$packed" --strip-components=3 "rust-1.100.0-dev-$host/cargo/bin/cargo"
sha256sum "$packed" > "$out/archives.sha256"
extra=()
if [[ -z "${RUSTC_KITS:-}" || "${SHIPPED:-}" == true ]]; then
  shipped="$kits/release"
  tar -C "$kits" -xzf "$packed"
  "$kits/rust-1.100.0-dev-$host/install.sh" --prefix="$shipped" --disable-ldconfig
  control="$shipped"
  candidate="$shipped"
  if [[ -n "${RUSTC_KITS:-}" ]]; then
    extra+=(--release "$shipped")
  fi
fi

if [[ "${RELEASE_LLVM:-}" == true ]]; then
  test "$tag" = ohm-1.100.0-4
  lib=libLLVM.so.23.1-rust-dev
  tar -C "$kits" -xzf "$packed" --strip-components=3 "rust-1.100.0-dev-$host/rustc/lib/$lib"
  case "$digest" in
    09c701b4a1f6b196d51164e8392adafc2304f7e2c759d2aa524d5c42d2178943)
      expected_llvm=19327450340ce3aac82e30a57a2e028a86ea77d9974e9dc168bf0fa882225f02 ;;
    6948ffc7d33b245bf48fdf770b5913cd536e71aec40a0ea280bd0eb33d4524b8)
      expected_llvm=714780e0f92a97b9ad9fe2c3b178e8be11e1629661a2964c001140c829bc21db ;;
    *) echo "Unverified LLVM archive" >&2; exit 1 ;;
  esac
  echo "$expected_llvm  $kits/$lib" | sha256sum -c -
  sha256sum "$kits/$lib" > "$out/release-llvm.sha256"
fi

load_role() {
  local role=$1 archive="$kits/$2.tar.zst"
  local sdk="$kits/$role"
  sha256sum "$archive" >> "$out/archives.sha256"
  mkdir "$sdk"
  tar --zstd -C "$sdk" --strip-components=1 -xf "$archive"
  (cd "$sdk" && sha256sum --quiet -c manifest.sha256)
  mkdir "$out/sdk-$role"
  cp "$sdk"/{bootstrap.toml,bootstrap.patch,compiler.patch,epoch,manifest.sha256,revision,version.txt} "$out/sdk-$role/"
  if [[ -f "$sdk/profile.sha256" ]]; then
    cp "$sdk/profile.sha256" "$out/sdk-$role/"
  fi
  if [[ -f "$sdk/stage1.sha256" ]]; then
    cp "$sdk"/{stage1.sha256,relocations.txt} "$out/sdk-$role/"
  fi
  if [[ "$role" != control ]]; then
    cmp "$control/epoch" "$sdk/epoch"
    # Share the complete set of standard libraries and the allocator.
    mv "$sdk/lib/rustlib/$host/lib" "$kits/unused-$role-std"
    cp -al "$control/lib/rustlib/$host/lib" "$sdk/lib/rustlib/$host/lib"
    cp "$control/bin/rustc" "$sdk/bin/rustc"
    cmp "$control/bin/rustc" "$sdk/bin/rustc"
    echo "$role consumes the control std" >> "$out/stdlib"
  fi
  if [[ "${RELEASE_LLVM:-}" == true ]]; then
    # Same LLVM version, different library names in CI and release builds.
    # Verify the build receipt above and record the library actually used below.
    grep -qx 'LLVM version: 23.1.5' "$sdk/version.txt"
    for path in libLLVM.so.23.1-rust-1.100.0-beta libLLVM-23-rust-1.100.0-beta.so; do
      test -f "$sdk/lib/$path"
      ln -sf "$kits/$lib" "$sdk/lib/$path"
    done
    ldd -r "$sdk"/lib/librustc_driver-*.so > "$out/sdk-$role/dynamic-link.txt" 2>&1
    if grep -E 'undefined symbol|not found' "$out/sdk-$role/dynamic-link.txt"; then exit 1; fi
    "$sdk/bin/rustc" -vV | grep -qx 'LLVM version: 23.1.5'
    echo 'fn main(){println!("{}", std::env::args().count());}' |
      "$sdk/bin/rustc" --crate-name check_llvm - -o "$kits/check-llvm"
    test "$("$kits/check-llvm" a)" = 2
  fi
}
if [[ -n "${RUSTC_KITS:-}" ]]; then
  control="$kits/control"
  candidate="$kits/candidate"
  load_role control control
  load_role candidate candidate
  if [[ -n "${INTERMEDIATE_KIT:-}" ]]; then
    load_role intermediate pr/candidate
    extra+=(--intermediate "$kits/intermediate")
  fi
  if [[ -n "${SECOND_KIT:-}" ]]; then
    load_role second pr2/candidate
    extra+=(--second "$kits/second")
  fi
  if (( ${#extra[@]} )); then
    extra+=(--pair "$pair")
  fi
fi
for variant in PARENT CANDIDATE; do
  dir="$kits/cargo-$variant"
  if [[ -f "$dir.tar.zst" ]]; then
    mkdir -p "$dir" "$out/cargo-$variant"
    tar -C "$dir" --zstd -xf "$dir.tar.zst"
    (cd "$dir" && sha256sum -c manifest.sha256)
    cp "$dir"/{manifest.sha256,revision,source.patch,source.tree,version.txt} "$out/cargo-$variant/"
    if [[ "$variant" == PARENT ]]; then
      if [[ -n "${INTERMEDIATE_KIT:-}" ]]; then
        cp -a "$out/sdk-control" "$out/sdk-current"
        extra+=(--current "$control" --current-cargo "$dir/cargo")
      fi
      extra+=(--intermediate-cargo "$dir/cargo")
    else
      extra+=(--second-cargo "$dir/cargo" --candidate-cargo "$dir/cargo")
    fi
  fi
done
sha256sum "$control/bin/rustc" | cut -d' ' -f1 > "$out/common-launcher"
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
  --window "${HISTORY_WINDOW:-recent}" \
  --scratch "$RUNNER_TEMP/experiment" \
  --output "$out" \
  --first "$first" --jobs 4 "${extra[@]}"
