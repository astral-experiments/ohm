#!/usr/bin/env bash
set -euo pipefail
unset CDPATH

if [[ $# -ne 3 ]]; then
  echo "usage: assemble-release.sh MANIFEST RELEASE_DIRECTORY TOOLCHAIN" >&2
  exit 2
fi
script_path="${BASH_SOURCE[0]}"
[[ "$script_path" == */* ]] || script_path="./$script_path"
IFS= read -r -d '' script_directory < <(cd -P -- "${script_path%/*}/" && printf '%s\0' "$PWD")
manifest=$1
if [[ "$manifest" != /* ]]; then
  manifest="$PWD/$manifest"
fi
OHM_TOOLCHAIN=$3
if [[ ! "$OHM_TOOLCHAIN" =~ ^ohm-[0-9]+\.[0-9]+\.[0-9]+-[1-9][0-9]*$ ]]; then
  echo "invalid toolchain name: $OHM_TOOLCHAIN" >&2
  exit 1
fi
jq -e --arg toolchain "$OHM_TOOLCHAIN" '.release.toolchain_name == $toolchain' "$manifest" >/dev/null
cd -P -- "$2"

targets=(aarch64-apple-darwin x86_64-unknown-linux-gnu)
for target in "${targets[@]}"; do
  archive_name="$OHM_TOOLCHAIN-$target.tar.gz"
  provenance_name="$OHM_TOOLCHAIN-$target-provenance.json"

  for asset in \
    "$archive_name" \
    "$archive_name.sha256" \
    "$provenance_name" \
    "$provenance_name.sha256"; do
    if [[ ! -f "$asset" || -L "$asset" ]]; then
      echo "missing or unsafe release asset: $asset" >&2
      exit 1
    fi
  done

  for asset in "$archive_name" "$provenance_name"; do
    if ! sha256sum "$asset" | cmp -s - "$asset.sha256"; then
      echo "checksum file does not match $asset: $asset.sha256" >&2
      exit 1
    fi
  done
done

macos_archive="$OHM_TOOLCHAIN-aarch64-apple-darwin.tar.gz"
linux_archive="$OHM_TOOLCHAIN-x86_64-unknown-linux-gnu.tar.gz"
macos_sha256="$(awk '{print $1}' "$macos_archive.sha256")"
linux_sha256="$(awk '{print $1}' "$linux_archive.sha256")"
wild_version="$(jq -r '.bundled_tools.wild.version // empty' "$manifest")"

manifest_name="$OHM_TOOLCHAIN.json"
outputs=(ohm-installer.sh "$manifest_name" SHA256SUMS)
for output in "${outputs[@]}"; do
  if [[ -d "$output" && ! -L "$output" ]]; then
    echo "release output is a directory: $output" >&2
    exit 1
  fi
done
staging="$(mktemp -d .ohm-release.XXXXXXXX)"
trap 'rm -rf -- "$staging"' EXIT
installer="$staging/ohm-installer.sh"

awk -v version="$OHM_TOOLCHAIN" \
  -v macos_sha256="$macos_sha256" \
  -v linux_sha256="$linux_sha256" \
  -v wild_version="$wild_version" '
  $0 == "embedded_wild_version=" {
    print "embedded_wild_version=" wild_version
    ++wild_count
    next
  }
  $0 == "embedded_version=" {
    print "embedded_version=" version
    ++version_count
    next
  }
  $0 == "embedded_archive_sha256_aarch64_apple_darwin=" {
    print "embedded_archive_sha256_aarch64_apple_darwin=" macos_sha256
    ++macos_count
    next
  }
  $0 == "embedded_archive_sha256_x86_64_unknown_linux_gnu=" {
    print "embedded_archive_sha256_x86_64_unknown_linux_gnu=" linux_sha256
    ++linux_count
    next
  }
  { print }
  END {
    if (version_count != 1 || macos_count != 1 || linux_count != 1 || wild_count != 1) {
      exit 1
    }
  }
' "$script_directory/install.sh" > "$installer"
sh -n "$installer"
grep -Fx "embedded_version=$OHM_TOOLCHAIN" "$installer" >/dev/null
grep -Fx "embedded_archive_sha256_aarch64_apple_darwin=$macos_sha256" \
  "$installer" >/dev/null
grep -Fx "embedded_archive_sha256_x86_64_unknown_linux_gnu=$linux_sha256" \
  "$installer" >/dev/null

cp "$manifest" "$staging/$manifest_name"
{
  sha256sum "$macos_archive" "$macos_archive.sha256" "$linux_archive" "$linux_archive.sha256"
  (cd -- "$staging" && sha256sum ohm-installer.sh "$manifest_name")
  sha256sum "$OHM_TOOLCHAIN-aarch64-apple-darwin-provenance.json" \
    "$OHM_TOOLCHAIN-x86_64-unknown-linux-gnu-provenance.json"
} > "$staging/SHA256SUMS"

# Publish the checksum list last, after replacing the two files it describes.
for output in "${outputs[@]}"; do
  mv -f -- "$staging/$output" .
done
sha256sum --check --strict SHA256SUMS
