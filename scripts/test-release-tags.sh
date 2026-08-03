#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/ohm-release-tags.XXXXXX")"
trap 'rm -rf -- "$test_root"' EXIT

mkdir -p "$test_root/bin"
cat > "$test_root/bin/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

[[ "$1" == api ]] || exit 2
shift
method=GET
if [[ "$1" == --method ]]; then
  method="$2"
  shift 2
fi

endpoint="$1"
shift
repository="${endpoint#repos/}"
repository="${repository%%/git/*}"
state_path="${OHM_TEST_ROOT:?}/${repository//\//-}"

if [[ "$repository" == "${OHM_TEST_FAIL_REPOSITORY:-}" ]]; then
  echo 'simulated GitHub API failure' >&2
  exit 1
fi

if [[ "$method" == GET ]]; then
  [[ "$endpoint" == repos/*/git/matching-refs/tags/* ]] || exit 2
  if [[ -f "$state_path" ]]; then
    head -n 1 "$state_path"
  fi
elif [[ "$method" == POST ]]; then
  [[ "$endpoint" == repos/*/git/refs ]] || exit 2
  revision=
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -f)
        if [[ "$2" == sha=* ]]; then
          revision="${2#sha=}"
        fi
        shift 2
        ;;
      --silent) shift ;;
      *) exit 2 ;;
    esac
  done
  [[ -n "$revision" ]] || exit 2
  printf '%s\n' "$revision" > "$state_path"
  printf '%s\n' "$repository" >> "${OHM_TEST_ROOT:?}/created"
else
  exit 2
fi
EOF
chmod +x "$test_root/bin/gh"

export PATH="$test_root/bin:$PATH"
export GH_TOKEN='ohm-release-test-token'
export OHM_TEST_ROOT="$test_root"
manifest="$repository_root/toolchains/1.97.1/1.json"

assert_creation_count() {
  local expected="$1"
  local actual
  actual="$(wc -l < "$test_root/created" | tr -d '[:space:]')"
  if [[ "$actual" != "$expected" ]]; then
    echo "expected $expected created tags, found $actual" >&2
    exit 1
  fi
}

"$script_dir/tag-release-sources.sh" "$manifest"
assert_creation_count 4
expected_revisions="$(
  jq -er '
    .sources[] |
    [(.repository | ltrimstr("https://github.com/")), .revision] |
    @tsv
  ' "$manifest"
)"
while IFS=$'\t' read -r repository revision; do
  [[ "$(head -n 1 "$test_root/${repository//\//-}")" == "$revision" ]]
done <<< "$expected_revisions"

"$script_dir/tag-release-sources.sh" "$manifest"
assert_creation_count 4

rm -- "$test_root/astral-sh-ohm-rustfmt"
"$script_dir/tag-release-sources.sh" "$manifest"
assert_creation_count 5

rust_revision="$(jq -r '.sources.rust.revision' "$manifest")"
printf '%040d\n' 0 > "$test_root/astral-sh-ohm-rust"
if "$script_dir/tag-release-sources.sh" "$manifest" >/dev/null 2>&1; then
  echo 'source tagging accepted a conflicting existing tag' >&2
  exit 1
fi
assert_creation_count 5
printf '%s\n' "$rust_revision" > "$test_root/astral-sh-ohm-rust"

rm -- "$test_root/astral-sh-ohm-cargo"
if OHM_TEST_FAIL_REPOSITORY=astral-sh/ohm-cargo \
  "$script_dir/tag-release-sources.sh" "$manifest" >/dev/null 2>&1; then
  echo 'source tagging treated a GitHub API failure as a missing tag' >&2
  exit 1
fi
assert_creation_count 5
[[ ! -e "$test_root/astral-sh-ohm-cargo" ]]

invalid_manifest="$test_root/invalid.json"
jq '.sources.cargo.repository = "https://github.com/astral-sh/unexpected"' \
  "$manifest" > "$invalid_manifest"
if "$script_dir/tag-release-sources.sh" "$invalid_manifest" >/dev/null 2>&1; then
  echo 'source tagging accepted an unexpected repository' >&2
  exit 1
fi
assert_creation_count 5

jq '.sources.rustfmt.revision = "invalid"' "$manifest" > "$invalid_manifest"
if "$script_dir/tag-release-sources.sh" "$invalid_manifest" >/dev/null 2>&1; then
  echo 'source tagging accepted an invalid revision' >&2
  exit 1
fi
assert_creation_count 5

echo 'release source tagging tests passed'
