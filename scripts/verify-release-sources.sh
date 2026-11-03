#!/usr/bin/env bash
set -euo pipefail
# Release revisions name the original objects, even in checkouts with replacement refs.
export GIT_NO_REPLACE_OBJECTS=1
unset CDPATH

if [[ $# -ne 5 ]]; then
  echo "usage: verify-release-sources.sh MANIFEST OHM_RUST_CHECKOUT OHM_CARGO_CHECKOUT OHM_CLIPPY_CHECKOUT OHM_RUSTFMT_CHECKOUT" >&2
  exit 2
fi

manifest="$1"
rust_checkout="$2"
cargo_checkout="$3"
clippy_checkout="$4"
rustfmt_checkout="$5"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

"$script_dir/validate-release-manifest.sh" --require-pinned "$manifest"

rust_revision="$(jq -er '.sources.rust.revision' "$manifest")"
cargo_revision="$(jq -er '.sources.cargo.revision' "$manifest")"
clippy_revision="$(jq -er '.sources.clippy.revision' "$manifest")"
rustfmt_revision="$(jq -er '.sources.rustfmt.revision' "$manifest")"
rust_version="$(jq -er '.release.upstream_rust_version' "$manifest")"
expected_cargo_repository="$(jq -er '.sources.cargo.repository' "$manifest")"

verify_clean_checkout() {
  local checkout="$1" checkout_status hidden_entries entry submodule
  # Release builds depend on the executable bits and symlinks in the pinned tree.
  local mode_config=(-c core.fileMode=true -c core.symlinks=true)
  shift
  checkout_status="$(git -C "$checkout" "${mode_config[@]}" status --porcelain --untracked-files=normal \
    --ignore-submodules=none -- "$@")"
  if [[ -n "$checkout_status" ]]; then
    echo "source checkout is not clean: $checkout" >&2
    exit 1
  fi

  # Status omits changes to assume-unchanged and skip-worktree entries.
  hidden_entries="$(git -C "$checkout" ls-files -v -- "$@" |
    awk '/^[a-zS] / { hidden = 1 } END { print hidden + 0 }')"
  if [[ "$hidden_entries" == 1 ]] && ! (
    index_directory="$(mktemp -d)" || exit 1
    trap 'rm -rf -- "$index_directory"' EXIT
    GIT_INDEX_FILE="$(cd -- "$index_directory" && pwd -P)/index" || exit 1
    export GIT_INDEX_FILE
    git -C "$checkout" -c core.sparseCheckout=false read-tree HEAD &&
      git -C "$checkout" "${mode_config[@]}" -c core.sparseCheckout=false diff --no-ext-diff --no-textconv --quiet --ignore-submodules=none HEAD -- "$@"
  ); then
    echo "could not verify tracked source files against HEAD: $checkout" >&2
    exit 1
  fi

  # Git applies each submodule's own ignore settings when checking its children.
  git -C "$checkout" ls-files --stage -z -- "$@" |
    while IFS= read -r -d '' entry; do
      [[ "$entry" == '160000 '* ]] || continue
      submodule="$checkout/${entry#*$'\t'}"
      if [[ -e "$submodule/.git" ]]; then
        verify_clean_checkout "$submodule" .
      fi
    done
}

for checkout in "$rust_checkout" "$cargo_checkout" "$clippy_checkout" "$rustfmt_checkout"; do
  if ! git -C "$checkout" rev-parse --show-toplevel >/dev/null 2>&1 ||
    [[ -n "$(git -C "$checkout" rev-parse --show-prefix)" ]]; then
    echo "not the root of a Git worktree: $checkout" >&2
    exit 1
  fi

  checkout_paths=(.)
  if [[ "$checkout" == "$rust_checkout" ]]; then
    if [[ "$clippy_checkout" -ef "$rust_checkout/src/tools/clippy" ]]; then
      checkout_paths+=(':(exclude)src/tools/clippy')
    fi

    if [[ "$rustfmt_checkout" -ef "$rust_checkout/src/tools/rustfmt" ]]; then
      checkout_paths+=(':(exclude)src/tools/rustfmt')
    fi
  fi
  verify_clean_checkout "$checkout" "${checkout_paths[@]}"
done

actual_rust_revision="$(git -C "$rust_checkout" rev-parse HEAD)"
actual_cargo_revision="$(git -C "$cargo_checkout" rev-parse HEAD)"

if [[ "$actual_rust_revision" != "$rust_revision" ]]; then
  echo "ohm-rust is at $actual_rust_revision, expected $rust_revision" >&2
  exit 1
fi

if [[ "$actual_cargo_revision" != "$cargo_revision" ]]; then
  echo "ohm-cargo is at $actual_cargo_revision, expected $cargo_revision" >&2
  exit 1
fi

actual_clippy_revision="$(git -C "$clippy_checkout" rev-parse HEAD)"
if [[ "$actual_clippy_revision" != "$clippy_revision" ]]; then
  echo "ohm-rust-clippy is at $actual_clippy_revision, expected $clippy_revision" >&2
  exit 1
fi

actual_rustfmt_revision="$(git -C "$rustfmt_checkout" rev-parse HEAD)"
if [[ "$actual_rustfmt_revision" != "$rustfmt_revision" ]]; then
  echo "ohm-rustfmt is at $actual_rustfmt_revision, expected $rustfmt_revision" >&2
  exit 1
fi

actual_rust_version="$(tr -d '\r\n' <"$rust_checkout/src/version")"
if [[ "$actual_rust_version" != "$rust_version" ]]; then
  echo "ohm-rust reports version $actual_rust_version, expected $rust_version" >&2
  exit 1
fi

gitlink="$(git -C "$rust_checkout" ls-tree HEAD -- src/tools/cargo)"
read -r gitlink_mode gitlink_type gitlink_revision gitlink_path <<<"$gitlink"

if [[ "$gitlink_mode" != "160000" || "$gitlink_type" != "commit" || "$gitlink_path" != "src/tools/cargo" ]]; then
  echo "ohm-rust does not contain a src/tools/cargo gitlink" >&2
  exit 1
fi

if [[ "$gitlink_revision" != "$cargo_revision" ]]; then
  echo "ohm-rust pins Cargo $gitlink_revision, expected $cargo_revision" >&2
  exit 1
fi

cargo_repository="$(git -C "$rust_checkout" config -f .gitmodules --get submodule.src/tools/cargo.url)"
case "$cargo_repository" in
  git@github.com:*) cargo_repository="https://github.com/${cargo_repository#git@github.com:}" ;;
esac
cargo_repository="${cargo_repository%.git}"

if [[ "$cargo_repository" != "$expected_cargo_repository" ]]; then
  echo "ohm-rust Cargo submodule uses $cargo_repository, expected $expected_cargo_repository" >&2
  exit 1
fi

echo "verified ohm-rust $rust_revision with ohm-cargo $cargo_revision, ohm-rust-clippy $clippy_revision, and ohm-rustfmt $rustfmt_revision"
