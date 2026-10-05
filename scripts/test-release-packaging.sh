#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/ohm-packaging-test.XXXXXXXX")"
trap 'rm -rf "$temporary_directory"' EXIT
toolchain=ohm-9.9.9-1
manifest="$temporary_directory/manifest.json"
cat > "$manifest" <<EOF
{"release":{"toolchain_name":"$toolchain"},"bundled_tools":{"wild":{"version":"0.10.0"}}}
EOF

inputs="$temporary_directory/inputs"
mkdir -p "$inputs" "$temporary_directory/empty"
for target in aarch64-apple-darwin x86_64-unknown-linux-gnu; do
  archive="$toolchain-$target.tar.gz"
  provenance="$toolchain-$target-provenance.json"
  tar -czf "$inputs/$archive" -C "$temporary_directory/empty" .
  printf '{}\n' > "$inputs/$provenance"
  (
    cd "$inputs"
    sha256sum "$archive" > "$archive.sha256"
    sha256sum "$provenance" > "$provenance.sha256"
  )
done

valid="$temporary_directory/valid"
cp -R "$inputs" "$valid"
bash "$script_directory/assemble-release.sh" "$manifest" "$valid" "$toolchain"
(
  cd "$valid"
  sha256sum --check --strict SHA256SUMS
)
grep -Fx "embedded_version=$toolchain" "$valid/ohm-installer.sh"
grep -Fx 'embedded_wild_version=0.10.0' "$valid/ohm-installer.sh"
for target in aarch64-apple-darwin x86_64-unknown-linux-gnu; do
  checksum="$(cut -d ' ' -f 1 "$valid/$toolchain-$target.tar.gz.sha256")"
  variable="embedded_archive_sha256_${target//-/_}=$checksum"
  grep -Fx "$variable" "$valid/ohm-installer.sh"
done
cmp "$manifest" "$valid/$toolchain.json"

for failure in checksum symlink identity; do
  broken="$temporary_directory/$failure"
  cp -R "$inputs" "$broken"
  selected_toolchain=$toolchain
  case "$failure" in
    checksum) printf 'corrupt\n' >> "$broken/$toolchain-aarch64-apple-darwin.tar.gz" ;;
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

# Reject damaged published archives before installing or invoking a compiler.
printf 'corrupt\n' >> "$valid/$toolchain-aarch64-apple-darwin.tar.gz"
if bash "$script_directory/smoke-test-release.sh" "$valid" "$toolchain" \
  aarch64-apple-darwin aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  > "$temporary_directory/smoke.log" 2>&1; then
  echo 'smoke test accepted a corrupted archive' >&2
  exit 1
fi
grep -F 'FAILED' "$temporary_directory/smoke.log"
python3 "$script_directory/test_smoke_compact.py"
echo 'release packaging tests passed'
