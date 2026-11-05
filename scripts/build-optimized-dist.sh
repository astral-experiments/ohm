#!/usr/bin/env bash
set -euo pipefail
unset CDPATH
# Bootstrap and collect profiles from the requested checkout, even inside a Git hook.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR
unset GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_QUARANTINE_PATH

if [[ $# -ne 4 ]]; then
  echo 'usage: build-optimized-dist.sh TARGET TOOLCHAIN RUST_CHECKOUT BOOTSTRAP_CONFIG' >&2
  exit 2
fi

target="$1"
toolchain="$2"
rust_checkout="$3"
bootstrap_config="$4"

case "$target" in
  aarch64-apple-darwin) use_bolt=false ;;
  x86_64-unknown-linux-gnu) use_bolt=true ;;
  *)
    echo "unsupported optimized release target: $target" >&2
    exit 1
    ;;
esac

if [[ ! "$toolchain" =~ ^ohm-[0-9]+\.[0-9]+\.[0-9]+-[1-9][0-9]*$ ]]; then
  echo "invalid Ohm toolchain name: $toolchain" >&2
  exit 1
fi

if [[ ! -d "$rust_checkout" || ! -f "$rust_checkout/x.py" ]]; then
  echo "invalid Rust checkout: $rust_checkout" >&2
  exit 1
fi

if [[ ! -f "$bootstrap_config" ]]; then
  echo "release bootstrap configuration not found: $bootstrap_config" >&2
  exit 1
fi

# A NUL delimiter preserves trailing newlines in the physical directory name.
IFS= read -r -d '' rust_checkout < <(cd -P -- "$rust_checkout" && printf '%s\0' "$PWD")
script_path="${BASH_SOURCE[0]}"
[[ "$script_path" == */* ]] || script_path="./$script_path"
IFS= read -r -d '' script_directory < <(cd -P -- "${script_path%/*}/" && printf '%s\0' "$PWD")
if [[ "$bootstrap_config" != /* ]]; then
  bootstrap_config="$PWD/$bootstrap_config"
fi

# Older immutable Rust source revisions only train rustc. Detect the explicit
# component-training contract before bootstrapping so those releases remain
# reproducible without weakening verification for newer source revisions.
component_pgo=false
if [[ -f "$rust_checkout/src/tools/opt-dist/component-pgo-v1" ]]; then
  component_pgo=true
fi

# Keep older pinned sources reproducible; the marker guarantees that rustc can
# select mimalloc without changing the allocator used by rustdoc and Clippy.
use_mimalloc=false
if [[ "$target" == x86_64-unknown-linux-gnu && \
  -f "$rust_checkout/compiler/rustc/mimalloc-v1" ]]; then
  use_mimalloc=true
fi

if [[ "$use_bolt" == true ]]; then
  if [[ -z "${OHM_BOLT_LLVM_DIR:-}" ]]; then
    echo 'Linux optimized releases require OHM_BOLT_LLVM_DIR' >&2
    exit 1
  fi

  if [[ ! -d "$OHM_BOLT_LLVM_DIR" ]]; then
    echo "LLVM BOLT directory not found: $OHM_BOLT_LLVM_DIR" >&2
    exit 1
  fi

  IFS= read -r -d '' bolt_llvm_dir < <(cd -P -- "$OHM_BOLT_LLVM_DIR" && printf '%s\0' "$PWD")
  for bolt_binary in llvm-bolt merge-fdata; do
    if [[ ! -x "$bolt_llvm_dir/bin/$bolt_binary" ]]; then
      echo "required LLVM BOLT executable not found: $bolt_llvm_dir/bin/$bolt_binary" >&2
      exit 1
    fi
  done

  if [[ ! -f "$bolt_llvm_dir/lib/libbolt_rt_instr.a" ]]; then
    echo "LLVM BOLT instrumentation runtime not found: $bolt_llvm_dir/lib/libbolt_rt_instr.a" >&2
    exit 1
  fi
fi

build_dir="$rust_checkout/build"
mkdir -p "$build_dir"
release_config="$build_dir/ohm-release-bootstrap.toml"

# Keep the complete release configuration visible to both bootstrap.py and the
# Rust bootstrap executable. bootstrap.py does not resolve TOML includes, so an
# include-based override would silently drop release-critical configuration.
if ! awk -v toolchain="$toolchain" -v use_mimalloc="$use_mimalloc" '
  /^description[[:space:]]*=[[:space:]]*"Ohm"[[:space:]]*$/ {
    print "description = \"" toolchain "\""
    replacements++
    next
  }
  { print }
  /^\[rust\][[:space:]]*$/ && use_mimalloc == "true" {
    print "mimalloc = true"
    allocator_replacements++
  }
  END {
    if (replacements != 1) exit 1
    if (use_mimalloc == "true" && allocator_replacements != 1) exit 1
  }
' "$bootstrap_config" >"$release_config"; then
  echo 'release bootstrap configuration must contain exactly one Ohm build description' >&2
  exit 1
fi

export RUST_BOOTSTRAP_CONFIG="$release_config"
if [[ -n "${TMPDIR:-}" && "$TMPDIR" != /* ]]; then
  export TMPDIR="$PWD/$TMPDIR"
fi
cd -- "$rust_checkout"

# `opt-dist` is a bootstrap-only tool and does not itself require LLVM. Ask for
# LLVM explicitly so bootstrap downloads its already-optimized CI artifact
# before the optimization pipeline needs the matching llvm-profdata executable.
python3 "$rust_checkout/x.py" build \
  --ci false \
  --config "$release_config" \
  --build-dir "$build_dir" \
  --host "$target" \
  --target "$target" \
  opt-dist \
  src/llvm-project

opt_dist="$build_dir/$target/stage1-tools-bin/opt-dist"
if [[ ! -x "$opt_dist" ]]; then
  echo "optimized distribution tool was not built: $opt_dist" >&2
  exit 1
fi

ci_llvm_dir="$build_dir/$target/ci-llvm"
llvm_profdata="$ci_llvm_dir/bin/llvm-profdata"
if [[ ! -x "$llvm_profdata" ]]; then
  echo "matching CI LLVM profile tool was not downloaded: $llvm_profdata" >&2
  exit 1
fi

release_name="${toolchain#ohm-}"
manifest="$script_directory/../toolchains/${release_name%-*}/${release_name##*-}.json"
prepare_relocated_dependencies=false
if [[ -f "$manifest" ]]; then
  prepare_relocated_dependencies="$(jq -r '.prepare_relocated_pgo_dependencies // false' "$manifest")"
fi
if [[ "$use_bolt" == true || "$prepare_relocated_dependencies" == true ]]; then
  work_directory="$(mktemp -d "${TMPDIR:-/tmp}/ohm-opt-dist.XXXXXX")"
  trap 'rm -rf -- "$work_directory"' EXIT
fi

llvm_dir="$ci_llvm_dir"
if [[ "$use_bolt" == true ]]; then
  llvm_version="$("$llvm_profdata" --version)"
  if [[ ! "$llvm_version" =~ LLVM[[:space:]]version[[:space:]]([0-9]+)\. ]]; then
    echo "could not determine downloaded LLVM major version: $llvm_profdata" >&2
    exit 1
  fi
  llvm_major="${BASH_REMATCH[1]}"

  bolt_version="$("$bolt_llvm_dir/bin/llvm-bolt" --version)"
  if [[ ! "$bolt_version" =~ LLVM[[:space:]]version[[:space:]]([0-9]+)\. ]]; then
    echo "could not determine LLVM BOLT major version: $bolt_llvm_dir/bin/llvm-bolt" >&2
    exit 1
  fi
  bolt_major="${BASH_REMATCH[1]}"

  if [[ "$llvm_major" != "$bolt_major" ]]; then
    echo "LLVM BOLT major version $bolt_major does not match downloaded LLVM $llvm_major" >&2
    exit 1
  fi

  merge_version="$("$bolt_llvm_dir/bin/merge-fdata" --version)"
  if [[ ! "$merge_version" =~ LLVM[[:space:]]version[[:space:]]([0-9]+)\. ]]; then
    echo "could not determine LLVM merge-fdata major version: $bolt_llvm_dir/bin/merge-fdata" >&2
    exit 1
  fi
  merge_major="${BASH_REMATCH[1]}"

  if [[ "$llvm_major" != "$merge_major" ]]; then
    echo "LLVM merge-fdata major version $merge_major does not match downloaded LLVM $llvm_major" >&2
    exit 1
  fi

  # Pair the shared BOLT installation with this checkout's matching profile tool.
  llvm_dir="$work_directory/llvm"
  mkdir -p -- "$llvm_dir/bin"
  ln -s -- "$llvm_profdata" "$bolt_llvm_dir/bin/llvm-bolt" "$bolt_llvm_dir/bin/merge-fdata" "$llvm_dir/bin/"
  ln -s -- "$bolt_llvm_dir/lib" "$llvm_dir/lib"
fi

# Upstream opt-dist logs every environment variable before doing any work.
# Never pass GitHub tokens, signing material, or publication credentials into
# that process; retain only explicitly reviewed build-system variables.
safe_environment=(
  "PATH=$PATH"
  "HOME=$HOME"
  "RUST_BOOTSTRAP_CONFIG=$release_config"
  'DIST_TRY_BUILD=0'
  'GITHUB_ACTIONS=false'
)

for variable in \
  USER \
  LOGNAME \
  LANG \
  LC_ALL \
  LC_CTYPE \
  TERM \
  TMPDIR \
  RUNNER_TEMP \
  GITHUB_STEP_SUMMARY \
  CARGO_HOME \
  RUSTUP_HOME \
  CC \
  CXX \
  AR \
  RANLIB \
  CFLAGS \
  CXXFLAGS \
  LDFLAGS \
  DEVELOPER_DIR \
  SDKROOT \
  MACOSX_DEPLOYMENT_TARGET \
  MACOSX_STD_DEPLOYMENT_TARGET; do
  if [[ ${!variable+x} == x ]]; then
    safe_environment+=("$variable=${!variable}")
  fi
done

# LLVM has already been optimized by Rust's CI. Reuse it instead of rebuilding
# or reprofiling it. Mark it non-shared for opt-dist's purposes so its first
# rustc stage does not override settings that are incompatible with CI LLVM.
opt_dist_arguments=(
  local
  --target-triple "$target"
  --std-target wasm32-unknown-unknown
  --checkout-dir "$rust_checkout"
  --llvm-dir "$llvm_dir"
  --artifact-dir build/opt-artifacts
  --build-dir build
  --build-llvm=false
  --llvm-shared=false
)
if [[ "$use_bolt" == true ]]; then
  opt_dist_arguments+=(--use-bolt)
fi

if [[ "$prepare_relocated_dependencies" == true ]]; then
  # rustc-perf moves each benchmark after preparing its dependencies. A build
  # script can embed that original path. Prepare the moved dependencies before
  # the profiler starts, keeping the upstream collector and the Rust checkout intact.
  perf_path=src/tools/rustc-perf
  perf_revision="$(git -C "$rust_checkout" rev-parse "HEAD:$perf_path")"
  perf_source="$rust_checkout/$perf_path"
  perf_checkout="$work_directory/rustc-perf"
  mkdir -- "$perf_checkout"
  if [[ ! -e "$perf_source/.git" ]]; then
    # Read the committed gitlink even if the caller staged a different revision or removal.
    (
      export GIT_INDEX_FILE="$perf_checkout/index"
      git -C "$rust_checkout" read-tree HEAD
      git -C "$rust_checkout" submodule update --init --checkout --depth 1 -- "$perf_path"
    )
    rm -- "$perf_checkout/index"
  fi
  if ! git -C "$perf_source" cat-file -e "$perf_revision^{commit}" 2>/dev/null; then
    # Supply the revision on stdin so Git selects the checkout's usual fetch remote.
    git -C "$perf_source" fetch --depth 1 --no-tags --no-write-fetch-head --stdin <<< "$perf_revision"
  fi
  git -C "$perf_source" archive "$perf_revision" | tar -x -C "$perf_checkout"
  patch -d "$perf_checkout" -t -N -F 0 -p1 -i "$script_directory/../release/rustc-perf-relocated-dependencies.patch"
  opt_dist_arguments+=(--rustc-perf-checkout-dir "$perf_checkout")
fi

# This compiler rechecks dependencies with native inputs. rustc-perf expects
# the selected crate to be the only one compiled during each training run.
case "$toolchain" in
  ohm-1.99.0-20 | ohm-1.99.0-21)
    pinned_rust="$(jq -er '.sources.rust.revision' "$manifest")"
    if [[ "$(git -C "$rust_checkout" rev-parse --verify HEAD)" == "$pinned_rust" ]]; then
      opt_dist_arguments+=(--benchmark-cargo-config unstable.ohm-defaults=false)
    fi
    ;;
esac

dist_arguments=(--set "build.description=$toolchain")
if [[ -n "${OHM_WILD_LINKER_DIR:-}" ]]; then
  if [[ "$target" != x86_64-unknown-linux-gnu || ! -x "$OHM_WILD_LINKER_DIR/wild" ]]; then
    echo 'bundled Wild requires a Linux x86-64 target and an executable payload' >&2
    exit 1
  fi
  for license in LICENSE-APACHE LICENSE-MIT; do
    [[ -f "$OHM_WILD_LINKER_DIR/$license" ]] || {
      echo "missing Wild license: $license" >&2
      exit 1
    }
  done
  dist_arguments+=(--set "target.$target.ohm-wild-linker=$OHM_WILD_LINKER_DIR")
  # PGO runs the newly built Cargo before the distribution installs Wild into
  # its sysroot. Use LLD for training; the packaged Cargo retains its Wild default.
  safe_environment+=('CARGO_UNSTABLE_OHM_LINKER=lld')
fi

env -i "${safe_environment[@]}" \
  "$opt_dist" "${opt_dist_arguments[@]}" \
  -- \
  python3 "$rust_checkout/x.py" dist \
  --ci false \
  --config "$release_config" \
  --build-dir "$build_dir" \
  --host "$target" \
  --target "$target,wasm32-unknown-unknown" \
  "${dist_arguments[@]}" \
  extended

# Cargo is instrumented alongside rustc and consumes the merged rustc profile.
# Likewise, cargo-fmt and rustfmt share the formatting profile. Check executed
# crate symbols instead of merely accepting any nonempty LLVM profile: another
# instrumented process can otherwise create a valid but unrelated profile.
components=(rustc)
if [[ "$component_pgo" == true ]]; then
  components+=(rustdoc clippy rustfmt)
fi

for component in "${components[@]}"; do
  profile="$build_dir/opt-artifacts/$component-pgo.profdata"
  if [[ ! -f "$profile" || -L "$profile" || ! -s "$profile" ]]; then
    echo "optimized release has a missing or invalid merged $component PGO profile: $profile" >&2
    exit 1
  fi

  # `llvm-profdata show --covered --function=...` ignores its function filter,
  # so inspect the complete covered-function stream once per merged profile.
  if ! "$llvm_profdata" show --covered "$profile" | awk \
    -v component="$component" \
    -v component_pgo="$component_pgo" '
      component == "rustc" && index($0, "rustc_driver") { primary = 1 }
      component == "rustc" && index($0, "_5cargo") { cargo = 1 }
      component == "rustdoc" && index($0, "_7rustdoc") { primary = 1 }
      component == "clippy" && index($0, "_12clippy_lints") { primary = 1 }
      component == "rustfmt" &&
          (index($0, "_15rustfmt_nightly") || index($0, "_7rustfmt")) {
        primary = 1
      }
      component == "rustfmt" && index($0, "_9cargo_fmt") { cargo_fmt = 1 }
      END {
        if (!primary) {
          print "no executed " component " functions in merged PGO profile" > "/dev/stderr"
          exit 1
        }
        if (component == "rustc" && component_pgo == "true" && !cargo) {
          print "no executed Cargo functions in shared rustc PGO profile" > "/dev/stderr"
          exit 1
        }
        if (component == "rustfmt" && !cargo_fmt) {
          print "no executed cargo-fmt functions in shared rustfmt PGO profile" > "/dev/stderr"
          exit 1
        }
      }
    '; then
    echo "optimized release has a corrupt or incomplete merged $component PGO profile: $profile" >&2
    exit 1
  fi
done

if [[ "$component_pgo" == true ]]; then
  echo 'verified executed PGO profile coverage for rustc, rustdoc, Cargo, Clippy, rustfmt, and cargo-fmt'
else
  echo 'verified executed rustc PGO profile coverage for a legacy Rust source revision'
fi
