#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo 'usage: tag-release-sources.sh <release-manifest>' >&2
  exit 1
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo 'GH_TOKEN is required to tag release sources' >&2
  exit 1
fi

manifest="$1"
toolchain_name="$(jq -er '.release.toolchain_name' "$manifest")"
if [[ ! "$toolchain_name" =~ ^ohm-[0-9]+\.[0-9]+\.[0-9]+-[1-9][0-9]*$ ]]; then
  echo "invalid release toolchain name: $toolchain_name" >&2
  exit 1
fi

source_repositories="$(
  jq -er '
    if .status != "pinned" then
      error("release manifest must be pinned")
    else
      .sources as $sources |
      [
        {key: "rust", repository: "astral-sh/ohm-rust"},
        {key: "cargo", repository: "astral-sh/ohm-cargo"},
        {key: "clippy", repository: "astral-sh/ohm-rust-clippy"},
        {key: "rustfmt", repository: "astral-sh/ohm-rustfmt"}
      ][] |
      . as $source |
      $sources[$source.key] as $value |
      if $value.repository != ("https://github.com/" + $source.repository) then
        error("unexpected source repository: " + $source.key)
      elif ($value.revision | type != "string") or
           ($value.revision | test("^[0-9a-f]{40}$") | not) then
        error("invalid source revision: " + $source.key)
      else
        [$source.repository, $value.revision] | @tsv
      end
    end
  ' "$manifest"
)"

while IFS=$'\t' read -r repository revision; do
  existing_revision="$(
    gh api "repos/$repository/git/matching-refs/tags/$toolchain_name" \
      --jq ".[] | select(.ref == \"refs/tags/$toolchain_name\") | .object.sha"
  )"

  if [[ "$existing_revision" == "$revision" ]]; then
    echo "$repository: reusing $toolchain_name at $revision"
  elif [[ -n "$existing_revision" ]]; then
    echo "$repository: $toolchain_name points at $existing_revision, expected $revision" >&2
    exit 1
  else
    gh api --method POST "repos/$repository/git/refs" \
      -f "ref=refs/tags/$toolchain_name" \
      -f "sha=$revision" \
      --silent
    echo "$repository: tagged $toolchain_name at $revision"
  fi
done <<< "$source_repositories"
