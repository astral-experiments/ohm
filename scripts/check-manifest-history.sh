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

path_to_root="$(git rev-parse --show-cdup)"
cd -P -- "./$path_to_root"

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
    pinned:pinned)
      if cmp -s <(git show "$base_revision:$manifest") "$manifest"; then
        continue
      fi

      release_tag="$(git show "$base_revision:$manifest" | jq -er '.release.toolchain_name')"
      if git show-ref --verify --quiet "refs/tags/$release_tag"; then
        echo "published toolchain manifest changed: $manifest" >&2
        exit 1
      fi

      rustfmt_repository='https://github.com/astral-sh/ohm-rustfmt'
      revision_fields='
        del(
          .sources.rust.revision,
          .sources.cargo.revision,
          .sources.clippy.revision,
          .sources.rustfmt.revision
        )
      '
      previous_identity="$(
        git show "$base_revision:$manifest" |
          jq -S --arg repository "$rustfmt_repository" "
            if .sources | has(\"rustfmt\") then
              .
            else
              .sources.rustfmt = {repository: \$repository}
            end |
            $revision_fields
          "
      )"
      current_identity="$(jq -S "$revision_fields" "$manifest")"
      if [[ "$previous_identity" != "$current_identity" ]]; then
        echo "unpublished pinned manifest changed beyond its source revisions: $manifest" >&2
        exit 1
      fi
      ;;
    draft:draft)
      if ! cmp -s <(git show "$base_revision:$manifest") "$manifest"; then
        echo "existing draft manifest changed: $manifest" >&2
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
