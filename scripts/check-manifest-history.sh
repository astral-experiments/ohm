#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: check-manifest-history.sh BASE_REVISION" >&2
  exit 2
fi

base_revision="$1"
zero_revision="0000000000000000000000000000000000000000"

if [[ -z "$base_revision" || "$base_revision" == "$zero_revision" ]]; then
  echo "no previous coordinator revision; all manifests are new"
  exit 0
fi

if ! git cat-file -e "$base_revision^{commit}" 2>/dev/null; then
  echo "base revision is not available: $base_revision" >&2
  exit 1
fi

while IFS= read -r manifest; do
  case "$manifest" in
    toolchains/*/*.json) ;;
    *) continue ;;
  esac

  if [[ ! -f "$manifest" ]]; then
    echo "existing toolchain manifest was deleted: $manifest" >&2
    exit 1
  fi

  previous_status="$(git show "$base_revision:$manifest" | jq -er '.status')"
  current_status="$(jq -er '.status' "$manifest")"

  case "$previous_status:$current_status" in
    pinned:pinned | draft:draft)
      if ! cmp -s <(git show "$base_revision:$manifest") "$manifest"; then
        echo "existing $previous_status manifest changed: $manifest" >&2
        exit 1
      fi
      ;;
    draft:pinned)
      previous_identity="$(git show "$base_revision:$manifest" | jq -S 'del(.status, .sources)')"
      current_identity="$(jq -S 'del(.status, .sources)' "$manifest")"
      if [[ "$previous_identity" != "$current_identity" ]]; then
        echo "draft-to-pinned transition changed release identity: $manifest" >&2
        exit 1
      fi
      ;;
    *)
      echo "invalid manifest status transition $previous_status -> $current_status: $manifest" >&2
      exit 1
      ;;
  esac
done < <(git ls-tree -r --name-only "$base_revision" -- toolchains)

echo "verified toolchain manifest history against $base_revision"
