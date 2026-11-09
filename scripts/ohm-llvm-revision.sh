#!/usr/bin/env bash
set -euo pipefail
# A release launched by a Git hook inherits the caller's repository and object store.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE
unset GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_QUARANTINE_PATH
# The LLVM gitlink path is fixed even when the caller uses a different pathspec mode.
unset GIT_LITERAL_PATHSPECS GIT_GLOB_PATHSPECS GIT_NOGLOB_PATHSPECS GIT_ICASE_PATHSPECS

# A Rust release opts into source-built LLVM by pinning the Ohm submodule.
checkout="${1:?expected a Rust checkout}"
modules=(git --no-replace-objects -C "$checkout" config --blob HEAD:.gitmodules)
if ! path_key="$("${modules[@]}" --name-only --get-regexp '^submodule\..*\.path$' '^src/llvm-project$' 2>/dev/null)"; then
  exit 0
fi
repository="$("${modules[@]}" --get "${path_key%.path}.url")"
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
