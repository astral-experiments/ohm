#!/usr/bin/env bash
set -euo pipefail

# Rust 1.99.0 builds its Apple Silicon distribution with this Xcode and SDK.
expected=$'Xcode 26.2\nBuild version 17C52'
for developer in /Applications/Xcode_26.2.app/Contents/Developer \
  "${DEVELOPER_DIR:-$(xcode-select -p)}" /Applications/Xcode*.app/Contents/Developer; do
  [[ -d "$developer" ]] || continue
  version="$(DEVELOPER_DIR="$developer" xcodebuild -version 2>/dev/null)" || continue
  [[ "$version" == "$expected" ]] || continue
  sdk="$(DEVELOPER_DIR="$developer" xcrun --sdk macosx --show-sdk-version 2>/dev/null)" || continue
  if [[ "$sdk" == 26.2 ]]; then
    printf '%s\n' "$developer"
    exit 0
  fi
done

echo 'Ohm LLVM for Rust 1.99.0 requires Xcode 26.2 (17C52) with macOS SDK 26.2' >&2
exit 1
