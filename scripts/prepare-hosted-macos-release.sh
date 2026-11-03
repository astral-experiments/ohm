#!/usr/bin/env bash
set -euo pipefail

# Hosted macOS images ship several Xcode versions on one volume. Keep the selected
# toolchain and its SDK, and free the other installations for profile training.
if [[ ${GITHUB_ACTIONS:-} != true || ${RUNNER_ENVIRONMENT:-} != github-hosted || ${RUNNER_OS:-} != macOS ]]; then
  echo 'This step requires an ephemeral GitHub-hosted macOS runner.' >&2
  exit 1
fi
selected=$(cd -P "$(xcode-select --print-path)/../.." && pwd -P)
if [[ $(dirname "$selected") != /Applications || $(basename "$selected") != Xcode*.app || ! -x "$selected/Contents/Developer/usr/bin/xcodebuild" ]]; then
  echo "Unrecognized active Xcode bundle: $selected" >&2
  exit 1
fi
printf 'Keeping %s\n' "$selected"
for bundle in /Applications/Xcode*.app; do
  if [[ -d "$bundle" && ! -L "$bundle" && ! "$bundle" -ef "$selected" ]]; then
    printf 'Removing inactive %s\n' "$bundle"
    sudo -n rm -rf "$bundle"
  fi
done
xcodebuild -version
test -x "$(xcrun --find clang)"
test -d "$(xcrun --sdk macosx --show-sdk-path)"
df -h "${GITHUB_WORKSPACE:?}"
free_kib=$(df -Pk "$GITHUB_WORKSPACE" | awk 'NR == 2 { print $4 }')
if [[ ! "$free_kib" =~ ^[0-9]+$ ]] || ((free_kib < 50 * 1024 * 1024)); then
  echo 'The distribution build requires at least 50 GiB free.' >&2
  exit 1
fi
