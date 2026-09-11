#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: assemble-release.sh MANIFEST RELEASE_DIRECTORY TOOLCHAIN" >&2
  exit 2
fi
script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
manifest="$(cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")"
OHM_TOOLCHAIN=$3
if [[ ! "$OHM_TOOLCHAIN" =~ ^ohm-[0-9]+\.[0-9]+\.[0-9]+-[1-9][0-9]*$ ]]; then
  echo "invalid toolchain name: $OHM_TOOLCHAIN" >&2
  exit 1
fi
jq -e --arg toolchain "$OHM_TOOLCHAIN" '.release.toolchain_name == $toolchain' "$manifest" >/dev/null
cd -- "$2"

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

  sha256sum --check --strict "$archive_name.sha256" "$provenance_name.sha256"
done

macos_archive="$OHM_TOOLCHAIN-aarch64-apple-darwin.tar.gz"
linux_archive="$OHM_TOOLCHAIN-x86_64-unknown-linux-gnu.tar.gz"
macos_sha256="$(awk '{print $1}' "$macos_archive.sha256")"
linux_sha256="$(awk '{print $1}' "$linux_archive.sha256")"
wild_version="$(jq -r '.bundled_tools.wild.version // empty' "$manifest")"

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
' "$script_directory/install.sh" > ohm-installer.sh
sh -n ohm-installer.sh
grep -Fx "embedded_version=$OHM_TOOLCHAIN" ohm-installer.sh >/dev/null
grep -Fx "embedded_archive_sha256_aarch64_apple_darwin=$macos_sha256" \
  ohm-installer.sh >/dev/null
grep -Fx "embedded_archive_sha256_x86_64_unknown_linux_gnu=$linux_sha256" \
  ohm-installer.sh >/dev/null

manifest_name="$OHM_TOOLCHAIN.json"
cp "$manifest" "$manifest_name"
sha256sum \
  "$macos_archive" \
  "$macos_archive.sha256" \
  "$linux_archive" \
  "$linux_archive.sha256" \
  ohm-installer.sh \
  "$manifest_name" \
  "$OHM_TOOLCHAIN-aarch64-apple-darwin-provenance.json" \
  "$OHM_TOOLCHAIN-x86_64-unknown-linux-gnu-provenance.json" > SHA256SUMS
sha256sum --check --strict SHA256SUMS
