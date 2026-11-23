#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/ohm-packaging-test.XXXXXXXX")"
trap 'rm -rf "$temporary_directory"' EXIT

# Store readelf output as fixture data to test dependency selection on either host.
llvm_fixture="$temporary_directory/llvm"
mkdir -p "$llvm_fixture/sdk/rustc/bin" "$llvm_fixture/sdk/rustc/lib"
cat > "$llvm_fixture/readelf" <<'EOF'
#!/usr/bin/env bash
cat -- "${!#}"
EOF
chmod +x "$llvm_fixture/readelf"
printf '(NEEDED) Shared library: [librustc_driver-test.so]\n' > "$llvm_fixture/sdk/rustc/bin/rustc"
printf '(NEEDED) Shared library: [libLLVM.so.active]\n' > "$llvm_fixture/sdk/rustc/lib/librustc_driver-test.so"
for active in 2.34 2.17; do
  stale=2.17
  if [[ "$active" == 2.17 ]]; then stale=2.34; fi
  printf 'Name: GLIBC_%s\n' "$active" > "$llvm_fixture/sdk/rustc/lib/libLLVM.so.active"
  printf 'Name: GLIBC_%s\n' "$stale" > "$llvm_fixture/sdk/rustc/lib/libLLVM.so.stale"
  tar -czf "$llvm_fixture/sdk.tar.gz" -C "$llvm_fixture" sdk/rustc/lib/libLLVM.so.stale \
    sdk/rustc/bin/rustc sdk/rustc/lib/librustc_driver-test.so sdk/rustc/lib/libLLVM.so.active
  if python3 "$script_directory/verify-linux-llvm.py" "$llvm_fixture/sdk.tar.gz" "$llvm_fixture/readelf" \
    > "$llvm_fixture/result" 2>&1; then
    [[ "$active" == 2.17 ]]
  else
    [[ "$active" == 2.34 ]]
    grep -Fq 'above the glibc 2.17 baseline' "$llvm_fixture/result"
  fi
done

# A loader can use a build path on the runner even when the SDK won't work elsewhere.
for dependency in /build/libzstd.so.1 build/libhelper.so; do
  printf 'Name: GLIBC_2.17\n(NEEDED) Shared library: [%s]\n' "$dependency" \
    > "$llvm_fixture/sdk/rustc/lib/libLLVM.so.active"
  tar -czf "$llvm_fixture/sdk.tar.gz" -C "$llvm_fixture" sdk
  if python3 "$script_directory/verify-linux-llvm.py" "$llvm_fixture/sdk.tar.gz" "$llvm_fixture/readelf" \
    > "$llvm_fixture/result" 2>&1; then
    echo "accepted a path in DT_NEEDED: $dependency" >&2
    exit 1
  fi
  grep -Fq "$dependency" "$llvm_fixture/result"
done

toolchain=ohm-9.9.9-1
manifest="$temporary_directory/manifest.json"$'\n'
cat > "$manifest" <<EOF
{"release":{"toolchain_name":"$toolchain"},"bundled_tools":{"wild":{"version":"0.10.0"}}}
EOF

cp "$manifest" "${manifest%$'\n'}"
printf '\n' >> "$manifest"

inputs="$temporary_directory/inputs"
mkdir -p "$inputs" "$temporary_directory/empty"
for target in aarch64-apple-darwin x86_64-unknown-linux-gnu; do
  archive="$toolchain-$target.tar.gz"
  provenance="$toolchain-$target-provenance.json"
  if [[ "$target" == x86_64-unknown-linux-gnu ]]; then
    mkdir -p "$llvm_fixture/sdk/cargo/bin"
    printf 'Name: GLIBC_2.9  Flags: none\n' > "$llvm_fixture/sdk/cargo/bin/cargo"
    printf 'Name: GLIBC_2.38  Flags: none\nName: GLIBC_2.39  Flags: WEAK\n' \
      >> "$llvm_fixture/sdk/rustc/lib/librustc_driver-test.so"
    printf 'Name: GLIBC_2.17  Flags: none\n' > "$llvm_fixture/sdk/rustc/lib/libLLVM.so.active"
    printf 'Name: GLIBC_2.42  Flags: none\n' > "$llvm_fixture/sdk/rustc/lib/libLLVM.so.stale"
    tar -czf "$inputs/$archive" -C "$llvm_fixture" sdk
  else
    tar -czf "$inputs/$archive" -C "$temporary_directory/empty" .
  fi
  printf '{}\n' > "$inputs/$provenance"
  (
    cd "$inputs"
    sha256sum "$archive" > "$archive.sha256"
    sha256sum "$provenance" > "$provenance.sha256"
  )
done

export PATH="$llvm_fixture:$PATH"
valid="$temporary_directory/valid"
cp -R "$inputs" "$valid"
mkdir "$temporary_directory/search"
cp -R "$inputs" "$temporary_directory/search/valid"
(
  cd -- "$temporary_directory"
  CDPATH="$temporary_directory/search" bash "$script_directory/assemble-release.sh" "$manifest" valid "$toolchain"
)
test ! -e "$temporary_directory/search/valid/SHA256SUMS"
(
  cd "$valid"
  sha256sum --check --strict SHA256SUMS
)
grep -Fx "embedded_version=$toolchain" "$valid/ohm-installer.sh"
grep -Fx "embedded_minimum_glibc=2.38" "$valid/ohm-installer.sh"
grep -Fx 'embedded_wild_version=0.10.0' "$valid/ohm-installer.sh"
for target in aarch64-apple-darwin x86_64-unknown-linux-gnu; do
  checksum="$(cut -d ' ' -f 1 "$valid/$toolchain-$target.tar.gz.sha256")"
  variable="embedded_archive_sha256_${target//-/_}=$checksum"
  grep -Fx "$variable" "$valid/ohm-installer.sh"
done
cmp "$manifest" "$valid/$toolchain.json"

# Resolve both the installer template and the output directory through the symlinks.
paths="$temporary_directory/paths"
mkdir -p "$paths/scripts" "$paths/valid"
ln -s "$script_directory" "$paths/commands"
ln -s "$temporary_directory/empty" "$paths/assets"
bash "$paths/commands/../scripts/assemble-release.sh" "$manifest" "$paths/assets/../valid" "$toolchain"
test ! -e "$paths/valid/SHA256SUMS"

linked="$temporary_directory/linked"
cp -R "$inputs" "$linked"
archive="$toolchain-x86_64-unknown-linux-gnu.tar.gz"
ln "$linked/$archive" "$linked/ohm-installer.sh"
ln -s "$archive" "$linked/$toolchain.json"
ln "$linked/$archive" "$linked/SHA256SUMS"
bash "$script_directory/assemble-release.sh" "$manifest" "$linked" "$toolchain"
cmp "$inputs/$archive" "$linked/$archive"
for output in ohm-installer.sh "$toolchain.json" SHA256SUMS; do
  test ! -L "$linked/$output"
  cmp "$valid/$output" "$linked/$output"
done

for failure in checksum wrong-archive wrong-provenance symlink identity; do
  broken="$temporary_directory/$failure"
  cp -R "$inputs" "$broken"
  selected_toolchain=$toolchain
  case "$failure" in
    checksum) printf 'corrupt\n' >> "$broken/$toolchain-aarch64-apple-darwin.tar.gz" ;;
    wrong-archive)
      cp "$broken/$toolchain-aarch64-apple-darwin.tar.gz.sha256" \
        "$broken/$toolchain-x86_64-unknown-linux-gnu.tar.gz.sha256"
      ;;
    wrong-provenance)
      cp "$broken/$toolchain-aarch64-apple-darwin-provenance.json.sha256" \
        "$broken/$toolchain-x86_64-unknown-linux-gnu-provenance.json.sha256"
      ;;
    symlink)
      rm "$broken/$toolchain-aarch64-apple-darwin-provenance.json"
      ln -s "$inputs/$toolchain-aarch64-apple-darwin-provenance.json" \
        "$broken/$toolchain-aarch64-apple-darwin-provenance.json"
      ;;
    identity) selected_toolchain=ohm-9.9.9-2 ;;
  esac
  if bash "$script_directory/assemble-release.sh" "$manifest" "$broken" "$selected_toolchain" \
    > "$temporary_directory/$failure.log" 2>&1; then
    echo "assembly accepted invalid $failure input" >&2
    exit 1
  fi
  test ! -e "$broken/ohm-installer.sh"
done

# Reject damaged release inputs before installing or invoking a compiler.
for asset in "$toolchain-aarch64-apple-darwin.tar.gz" "$toolchain.json" ohm-installer.sh; do
  cp "$valid/$asset" "$temporary_directory/original"
  printf '\n' >> "$valid/$asset"
  if bash "$script_directory/smoke-test-release.sh" "$valid" "$toolchain" \
    aarch64-apple-darwin aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    > "$temporary_directory/smoke.log" 2>&1; then
    echo "smoke test accepted a corrupted $asset" >&2
    exit 1
  fi
  grep -Fx "$asset: FAILED" "$temporary_directory/smoke.log"
  mv "$temporary_directory/original" "$valid/$asset"
done

# Check the release directory and Cargo settings passed to the smoke test subprocesses.
candidate="$temporary_directory/candidate%20assets"
cp -R "$valid" "$candidate"
cat > "$candidate/ohm-installer.sh" <<'EOF'
for key in CARGO_BUILD_TARGET CARGO_TARGET_DIR CARGO_BUILD_TARGET_DIR CARGO_BUILD_BUILD_DIR; do
  if printenv "$key" >/dev/null; then
    echo "smoke test inherited $key" >&2
    exit 1
  fi
done
printf '%s\n' "$OHM_DOWNLOAD_URL"
exit 42
EOF
(cd "$candidate" && sha256sum ohm-installer.sh "$toolchain.json" > SHA256SUMS)
status=0
CARGO_BUILD_TARGET=aarch64-apple-darwin CARGO_TARGET_DIR=target \
  CARGO_BUILD_TARGET_DIR=artifacts CARGO_BUILD_BUILD_DIR=build \
  bash "$script_directory/smoke-test-release.sh" "$paths/assets/../candidate%20assets" "$toolchain" \
    aarch64-apple-darwin aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    > "$temporary_directory/smoke.log" 2>&1 || status=$?
if [[ "$status" != 42 ]]; then
  cat "$temporary_directory/smoke.log" >&2
  exit 1
fi
grep -E '^file://.*/candidate%2520assets$' "$temporary_directory/smoke.log"
echo 'release packaging tests passed'
