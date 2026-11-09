#!/usr/bin/env bash
set -euo pipefail
# A Git hook can supply its own repository, temporary index and object store.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE
unset GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_QUARANTINE_PATH
# Use the verifier's own pathspecs, including its exclusions for overlaid tools.
unset GIT_LITERAL_PATHSPECS GIT_GLOB_PATHSPECS GIT_NOGLOB_PATHSPECS GIT_ICASE_PATHSPECS
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
script_path="${BASH_SOURCE[0]}"
[[ "$script_path" == */* ]] || script_path="./$script_path"
IFS= read -r -d '' script_dir < <(cd -P -- "${script_path%/*}/" && printf '%s\0' "$PWD")

"$script_dir/validate-release-manifest.sh" --require-pinned "$manifest"

rust_revision="$(jq -er '.sources.rust.revision' "$manifest")"
cargo_revision="$(jq -er '.sources.cargo.revision' "$manifest")"
clippy_revision="$(jq -er '.sources.clippy.revision' "$manifest")"
rustfmt_revision="$(jq -er '.sources.rustfmt.revision' "$manifest")"
rust_version="$(jq -er '.release.upstream_rust_version' "$manifest")"
expected_cargo_repository="$(jq -er '.sources.cargo.repository' "$manifest")"

verify_clean_checkout() {
  local checkout="$1" checkout_status entry submodule
  # Check path case, executable bits and symlinks even when the checkout ignores them.
  local worktree_config=(-c core.ignoreCase=false -c core.fileMode=true -c core.symlinks=true)
  shift
  checkout_status="$(git -C "$checkout" "${worktree_config[@]}" status --porcelain --untracked-files=normal --ignored=matching \
    --ignore-submodules=none -- "$@")"
  if [[ -n "$checkout_status" ]]; then
    echo "source checkout is not clean: $checkout" >&2
    exit 1
  fi

  # Compare the bytes on disk with the pinned tree, independently of the
  # checkout's index, config and unversioned attributes.
  if ! (
    temporary_repo="$(mktemp -d)" || exit 1
    temporary_repo="$(cd -P -- "$temporary_repo" && pwd -P)" || exit 1
    trap 'rm -rf -- "$temporary_repo"' EXIT
    cd -P -- "$checkout" || exit 1
    revision="$(git rev-parse HEAD)" || exit 1
    format="$(git config --local --default sha1 --get extensions.objectFormat)" || exit 1
    objects="$(git rev-parse --git-path objects)" || exit 1
    objects="$(cd -P -- "$objects" && printf '%s/' "$PWD")" || exit 1
    unset GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_ATTR_SOURCE
    export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_ATTR_NOSYSTEM=1
    GIT_DEFAULT_HASH="$format" git init --bare --quiet --template= "$temporary_repo" || exit 1
    export GIT_DIR="$temporary_repo" GIT_WORK_TREE=. GIT_OBJECT_DIRECTORY="$objects"
    git read-tree "$revision" || exit 1

    mkdir -p -- "$GIT_DIR/info" || exit 1
    printf '%s\n' '* -text -crlf !eol -ident !filter !working-tree-encoding' > "$GIT_DIR/info/attributes" || exit 1
    git "${worktree_config[@]}" diff --raw --no-abbrev -z --no-renames --no-ext-diff --no-textconv \
      --ignore-submodules=none "$revision" -- "$@" > "$GIT_DIR/changes" || exit 1
    : > "$GIT_DIR/info/attributes" || exit 1

    # Committed attributes may legitimately expand an object during checkout.
    # Recreate that output only for regular files whose raw contents differ.
    while IFS= read -r -d '' change && IFS= read -r -d '' path; do
      read -r old_mode new_mode object _ status <<< "${change#:}"
      [[ "$status" == M && "$old_mode" == "$new_mode" && "$old_mode" == 100* ]] || exit 1
      actual="$(git hash-object --no-filters -- "$path")" || exit 1
      expected="$(GIT_ATTR_SOURCE="$revision" git -c core.attributesFile=/dev/null \
        cat-file --filters --path="$path" "$object" | git hash-object --stdin)" || exit 1
      [[ "$actual" == "$expected" ]] || exit 1
    done < "$GIT_DIR/changes"
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
      elif [[ -d "$submodule" ]] && ! (
        # Git ignores the contents of an uninitialized submodule.
        shopt -s dotglob nullglob
        set -- "$submodule"/*
        [[ $# -eq 0 && -r "$submodule" && -x "$submodule" ]]
      ); then
        echo "cannot verify an uninitialized source submodule: $submodule" >&2
        exit 1
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

modules=(git -C "$rust_checkout" config --blob HEAD:.gitmodules)
path_key="$("${modules[@]}" --name-only --get-regexp '^submodule\..*\.path$' '^src/tools/cargo$')"
cargo_repository="$("${modules[@]}" --get "${path_key%.path}.url")"
case "$cargo_repository" in
  git@github.com:*) cargo_repository="https://github.com/${cargo_repository#git@github.com:}" ;;
esac
cargo_repository="${cargo_repository%.git}"

if [[ "$cargo_repository" != "$expected_cargo_repository" ]]; then
  echo "ohm-rust Cargo submodule uses $cargo_repository, expected $expected_cargo_repository" >&2
  exit 1
fi

echo "verified ohm-rust $rust_revision with ohm-cargo $cargo_revision, ohm-rust-clippy $clippy_revision, and ohm-rustfmt $rustfmt_revision"
