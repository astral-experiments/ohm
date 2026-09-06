#!/usr/bin/env bash
# Check the installed toolchain, including Cargo's defaults and bundled Clippy.
set -euo pipefail

toolchain="${1:?usage: smoke-worktree-cache.sh TOOLCHAIN EMPTY_DIRECTORY}"
smoke_root="${2:?usage: smoke-worktree-cache.sh TOOLCHAIN EMPTY_DIRECTORY}"
if [[ -e "$smoke_root" ]]; then
  echo "smoke directory already exists: $smoke_root" >&2
  exit 1
fi
mkdir -p "$smoke_root"
smoke_root="$(cd "$smoke_root" && pwd -P)"

unset RUSTC RUSTDOC RUSTC_WRAPPER RUSTC_WORKSPACE_WRAPPER RUSTC_BOOTSTRAP
unset RUSTFLAGS CARGO_BUILD_RUSTFLAGS CARGO_ENCODED_RUSTFLAGS CARGO_INCREMENTAL
unset CARGO_UNSTABLE_OHM_DEFAULTS CARGO_UNSTABLE_OHM_WORKTREE_SEEDS
unset CARGO_UNSTABLE_OHM_SHARED_REGISTRY_CACHE
unset LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
unset DYLD_FORCE_FLAT_NAMESPACE DYLD_VERSIONED_LIBRARY_PATH DYLD_VERSIONED_FRAMEWORK_PATH
unset DYLD_IMAGE_SUFFIX DYLD_ROOT_PATH
unset CARGO_UNSTABLE_OHM_CLIPPY_SEED_ISOLATION __CARGO_OHM_CLIPPY_SEED_ISOLATION
unset __CARGO_OHM_DEFAULTS __CARGO_OHM_WORKTREE_SEEDS
export CARGO_HOME="$smoke_root/cargo-home"
export CARGO_TERM_COLOR=never
mkdir -p "$CARGO_HOME"
rustc +"$toolchain" -Z help | grep -F 'ohm-cloned-query-cache-prefix' >/dev/null

# Use a fresh donor for each mode: an earlier non-isolated Clippy invocation
# permanently marks that namespace as ineligible for importing.
check_worktree_cache() (
  case_root="$smoke_root/$1"
  isolation="${2:-}"
  cargo_cmd() {
    if [[ -n "$isolation" ]]; then
      cargo +"$toolchain" "-Zohm-clippy-seed-isolation=$isolation" "$@"
    else
      cargo +"$toolchain" "$@"
    fi
  }
  export CARGO_BUILD_BUILD_DIR="$case_root/shared"
  export CARGO_TARGET_DIR="$case_root/donor-target"
  mkdir -p "$case_root/donor/src"
  cd "$case_root/donor"
  cat > Cargo.toml <<'EOF'
[package]
name = "ohm-worktree-smoke"
version = "0.0.0"
edition = "2024"
EOF
  cat > src/main.rs <<'EOF'
fn main() {
    let smoke_local = 1;
    println!("{smoke_local}");
}
EOF
  printf '/target\n' > .gitignore
  git init --quiet
  git add Cargo.toml src/main.rs .gitignore
  git -c user.name='Ohm smoke test' -c user.email='ohm-smoke@example.invalid' \
    -c core.hooksPath=/dev/null commit --quiet -m 'Add worktree smoke fixture'

  cargo_cmd build --offline -vv 2>&1 | tee "$case_root/defaults.log"
  grep -E 'Running .*--crate-name ohm_worktree_smoke ' "$case_root/defaults.log" \
    | grep -F -- '-Zohm-cloned-query-cache-prefix ' >/dev/null
  [[ "$("$CARGO_TARGET_DIR/debug/ohm-worktree-smoke")" == 1 ]]
  cargo_cmd clippy --offline -- -D warnings
  donor_namespace=
  for namespace in "$CARGO_BUILD_BUILD_DIR/debug/build/workspaces/"*; do
    [[ -d "$namespace" ]] || continue
    [[ -z "$donor_namespace" ]]
    donor_namespace="$namespace"
  done
  [[ -n "$donor_namespace" ]]
  isolated=false
  if [[ -d "$donor_namespace/.ohm-clippy-v1" ]]; then
    isolated=true
    if compgen -G "$donor_namespace/.ohm-worktree-seed-deny-v*" >/dev/null; then
      echo 'Isolated Clippy marked ordinary build state as ineligible' >&2
      exit 1
    fi
  else
    [[ -z "$isolation" ]]
    compgen -G "$donor_namespace/.ohm-worktree-seed-deny-v*" >/dev/null
  fi

  # Include private Clippy caches in the donor immutability check.
  find "$CARGO_BUILD_BUILD_DIR" -name query-cache.bin -type f \
    -exec shasum -a 256 {} + > "$case_root/donor-cache.sha256"
  [[ -s "$case_root/donor-cache.sha256" ]]
  cargo_cmd worktree add --detach "$case_root/child" \
    --target-dir "$case_root/child-target" HEAD 2>&1 | tee "$case_root/seed.log"
  if "$isolated"; then
    grep -E 'Seeded [1-9][0-9]* files' "$case_root/seed.log" >/dev/null
    if [[ -z "$isolation" ]]; then
      grep -E '[1-9][0-9]* reflinked files' "$case_root/seed.log" >/dev/null
    fi
  else
    grep -F 'no compatible build snapshot seeded' "$case_root/seed.log" >/dev/null
  fi
  export CARGO_TARGET_DIR="$case_root/child-target"
  cd "$case_root/child"
  cargo_cmd build --offline -vv 2>&1 | tee "$case_root/child.log"
  if "$isolated"; then
    grep -F 'Fresh ohm-worktree-smoke ' "$case_root/child.log" >/dev/null
  else
    grep -F 'Compiling ohm-worktree-smoke ' "$case_root/child.log" >/dev/null
  fi
  [[ "$("$CARGO_TARGET_DIR/debug/ohm-worktree-smoke")" == 1 ]]
  child_namespace=
  for namespace in "$CARGO_BUILD_BUILD_DIR/debug/build/workspaces/"*; do
    [[ -d "$namespace" && "$namespace" != "$donor_namespace" ]] || continue
    [[ -z "$child_namespace" ]]
    child_namespace="$namespace"
  done
  [[ -n "$child_namespace" && ! -e "$child_namespace/.ohm-clippy-v1" ]]
  [[ ! -e "$CARGO_BUILD_BUILD_DIR/debug/incremental/${child_namespace##*/}/.ohm-clippy-v1" ]]

  # Imported build state must not suppress the child's own lint configuration.
  printf 'disallowed-names = ["smoke_local"]\n' > clippy.toml
  if cargo_cmd clippy --offline -- -D warnings > "$case_root/lint.log" 2>&1; then
    echo 'Clippy ignored the child worktree configuration' >&2
    exit 1
  fi
  grep -F 'smoke_local' "$case_root/lint.log" >/dev/null
  grep -F 'disallowed' "$case_root/lint.log" >/dev/null
  rm clippy.toml
  cargo_cmd clippy --offline -- -D warnings
  cat > src/main.rs <<'EOF'
fn main() {
    let smoke_local = 2;
    println!("{smoke_local}");
}
EOF
  cargo_cmd build --offline
  [[ "$("$CARGO_TARGET_DIR/debug/ohm-worktree-smoke")" == 2 ]]
  [[ "$("$case_root/donor-target/debug/ohm-worktree-smoke")" == 1 ]]
  shasum -a 256 --check "$case_root/donor-cache.sha256"

  CARGO_TARGET_DIR="$case_root/disabled-target" \
    CARGO_BUILD_BUILD_DIR="$case_root/disabled-build" \
    cargo +"$toolchain" -Zohm-defaults=no build --offline -vv \
    2>&1 | tee "$case_root/disabled.log"
  if grep -F -- '-Zohm-cloned-query-cache-prefix' "$case_root/disabled.log"; then
    echo 'query-cache cloning was enabled with Ohm defaults disabled' >&2
    exit 1
  fi
)

# Defaults isolate Clippy only on clone-capable storage. Explicit isolation also
# exercises ordinary snapshot copying on filesystems without cloning.
check_worktree_cache automatic
check_worktree_cache explicit yes
echo 'Installed worktree cache smoke test passed'
