#!/usr/bin/env bash
set -euo pipefail

# A Rust release opts into source-built LLVM by pinning the Ohm submodule.
checkout="${1:?expected a Rust checkout}"
repository="$(git --no-replace-objects -C "$checkout" config --blob HEAD:.gitmodules --get submodule.src/llvm-project.url 2>/dev/null || true)"
case "${repository%.git}" in
  https://github.com/astral-experiments/ohm-llvm) ;;
  *) exit 0 ;;
esac

read -r mode type revision path <<< "$(git --no-replace-objects -C "$checkout" ls-tree HEAD -- src/llvm-project)"
if [[ "$mode" != 160000 || "$type" != commit || ! "$revision" =~ ^[0-9a-f]{40}$ || "$path" != src/llvm-project ]]; then
  echo 'Ohm LLVM must be pinned by the Rust src/llvm-project gitlink' >&2
  exit 1
fi
printf '%s\n' "$revision"
