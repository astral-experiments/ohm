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
export CARGO_BUILD_BUILD_DIR="$smoke_root/shared"
export CARGO_TARGET_DIR="$smoke_root/donor-target"
export CARGO_HOME="$smoke_root/cargo-home"
export CARGO_TERM_COLOR=never
mkdir -p "$CARGO_HOME"

rustc +"$toolchain" -Z help | grep -F 'ohm-cloned-query-cache-prefix' >/dev/null
mkdir -p "$smoke_root/donor/src"
cd "$smoke_root/donor"
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

cargo +"$toolchain" build --offline -vv 2>&1 | tee "$smoke_root/defaults.log"
grep -E 'Running .*--crate-name ohm_worktree_smoke ' "$smoke_root/defaults.log" \
  | grep -F -- '-Zohm-cloned-query-cache-prefix ' >/dev/null
[[ "$("$CARGO_TARGET_DIR/debug/ohm-worktree-smoke")" == 1 ]]
cargo +"$toolchain" clippy --offline -- -D warnings
donor_namespace=
for namespace in "$CARGO_BUILD_BUILD_DIR/debug/build/workspaces/"*; do
  [[ -d "$namespace" ]] || continue
  [[ -z "$donor_namespace" ]]
  donor_namespace="$namespace"
done
[[ -n "$donor_namespace" && -d "$donor_namespace/.ohm-clippy-v1" ]]
[[ ! -e "$donor_namespace/.ohm-worktree-seed-deny-v7" ]]

# Record the original files, including Clippy's private cache. New child files
# are excluded from this list; all recorded donor bytes must remain unchanged.
find "$CARGO_BUILD_BUILD_DIR" -name query-cache.bin -type f \
  -exec shasum -a 256 {} + > "$smoke_root/donor-cache.sha256"
[[ -s "$smoke_root/donor-cache.sha256" ]]

# Automatic imports must clone their payloads, or leave the recipient unseeded.
cargo +"$toolchain" worktree add --detach "$smoke_root/automatic-child" \
  --target-dir "$smoke_root/automatic-target" HEAD 2>&1 | tee "$smoke_root/automatic-seed.log"
automatic_seeded=false
if grep -E 'Seeded [1-9][0-9]* files' "$smoke_root/automatic-seed.log" >/dev/null; then
  grep -E '[1-9][0-9]* reflinked files' "$smoke_root/automatic-seed.log" >/dev/null
  automatic_seeded=true
else
  grep -F 'build profiles without copy-on-write support' "$smoke_root/automatic-seed.log" >/dev/null
  for namespace in "$CARGO_BUILD_BUILD_DIR/debug/build/workspaces/"*; do
    [[ ! -d "$namespace" || "$namespace" == "$donor_namespace" ]]
  done
  for namespace in "$CARGO_BUILD_BUILD_DIR/debug/incremental/"*; do
    [[ ! -d "$namespace" || "${namespace##*/}" == "${donor_namespace##*/}" ]]
  done
fi
for stage in "$CARGO_BUILD_BUILD_DIR/debug/build/workspaces/.ohm-worktree-seed-"*; do
  [[ ! -e "$stage" ]]
done
export CARGO_TARGET_DIR="$smoke_root/automatic-target"
cd "$smoke_root/automatic-child"
cargo +"$toolchain" build --offline -vv 2>&1 | tee "$smoke_root/automatic-child.log"
if "$automatic_seeded"; then
  grep -F 'Fresh ohm-worktree-smoke ' "$smoke_root/automatic-child.log" >/dev/null
else
  grep -F 'Compiling ohm-worktree-smoke ' "$smoke_root/automatic-child.log" >/dev/null
fi
[[ "$("$CARGO_TARGET_DIR/debug/ohm-worktree-smoke")" == 1 ]]
automatic_namespace=
for namespace in "$CARGO_BUILD_BUILD_DIR/debug/build/workspaces/"*; do
  [[ -d "$namespace" && "$namespace" != "$donor_namespace" ]] || continue
  [[ -z "$automatic_namespace" ]]
  automatic_namespace="$namespace"
done
[[ -n "$automatic_namespace" && ! -e "$automatic_namespace/.ohm-clippy-v1" ]]
[[ ! -e "$CARGO_BUILD_BUILD_DIR/debug/incremental/${automatic_namespace##*/}/.ohm-clippy-v1" ]]

# Explicit copying keeps the full reuse/isolation check active on non-CoW CI.
export CARGO_TARGET_DIR="$smoke_root/donor-target"
cd "$smoke_root/donor"
cargo +"$toolchain" worktree add --detach "$smoke_root/child" \
  --copy-build-state --target-dir "$smoke_root/child-target" HEAD 2>&1 | tee "$smoke_root/seed.log"
grep -E 'Seeded [1-9][0-9]* files' "$smoke_root/seed.log" >/dev/null
child_namespace=
for namespace in "$CARGO_BUILD_BUILD_DIR/debug/build/workspaces/"*; do
  [[ -d "$namespace" && "$namespace" != "$donor_namespace" && "$namespace" != "$automatic_namespace" ]] || continue
  [[ -z "$child_namespace" ]]
  child_namespace="$namespace"
done
[[ -n "$child_namespace" && ! -e "$child_namespace/.ohm-clippy-v1" ]]
[[ ! -e "$CARGO_BUILD_BUILD_DIR/debug/incremental/${child_namespace##*/}/.ohm-clippy-v1" ]]
export CARGO_TARGET_DIR="$smoke_root/child-target"
cd "$smoke_root/child"
cargo +"$toolchain" build --offline -vv 2>&1 | tee "$smoke_root/child.log"
grep -F 'Fresh ohm-worktree-smoke ' "$smoke_root/child.log" >/dev/null
[[ "$("$CARGO_TARGET_DIR/debug/ohm-worktree-smoke")" == 1 ]]

# A child must discover its own lint configuration even after the donor ran
# Clippy. Diagnostics and lint state must never arrive through a build seed.
printf 'disallowed-names = ["smoke_local"]\n' > clippy.toml
if cargo +"$toolchain" clippy --offline -- -D warnings > "$smoke_root/lint.log" 2>&1; then
  echo 'Clippy ignored the child worktree configuration' >&2
  exit 1
fi
grep -F 'smoke_local' "$smoke_root/lint.log" >/dev/null
grep -F 'disallowed' "$smoke_root/lint.log" >/dev/null
rm clippy.toml
cargo +"$toolchain" clippy --offline -- -D warnings

cat > src/main.rs <<'EOF'
fn main() {
    let smoke_local = 2;
    println!("{smoke_local}");
}
EOF
cargo +"$toolchain" build --offline
[[ "$("$CARGO_TARGET_DIR/debug/ohm-worktree-smoke")" == 2 ]]
[[ "$("$smoke_root/donor-target/debug/ohm-worktree-smoke")" == 1 ]]
shasum -a 256 --check "$smoke_root/donor-cache.sha256"

# Check opt-out through the installed Cargo, independently of artifact reuse.
CARGO_TARGET_DIR="$smoke_root/disabled-target" \
  CARGO_BUILD_BUILD_DIR="$smoke_root/disabled-build" \
  cargo +"$toolchain" -Zohm-defaults=no build --offline -vv \
  2>&1 | tee "$smoke_root/disabled.log"
if grep -F -- '-Zohm-cloned-query-cache-prefix' "$smoke_root/disabled.log"; then
  echo 'query-cache cloning was enabled with Ohm defaults disabled' >&2
  exit 1
fi
echo 'Installed worktree cache smoke test passed'
