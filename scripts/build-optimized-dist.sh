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

llvm_revision="$("$script_directory/ohm-llvm-revision.sh" "$rust_checkout")"
build_llvm=false
train_llvm=false
host_llvm_dir=
bootstrap_targets=(opt-dist src/llvm-project)
if [[ -n "$llvm_revision" ]]; then
  build_llvm=true
  bootstrap_targets=(opt-dist)
  # Keep the profile merger outside the LLVM output that opt-dist rebuilds.
  host_llvm_dir="${OHM_HOST_LLVM_DIR:?source-built LLVM requires the pinned release tools}"
  if [[ "$use_bolt" == true ]]; then
    train_llvm=true
    llvm_image="${OHM_LLVM_BUILD_IMAGE:?Linux LLVM requires the Rust distribution image}"
    llvm_cmake=(LLVM_ENABLE_ZLIB=FORCE_ON)
  else
    # Rust builds Apple LLVM as a shared Release library with the system
    # Clang. Its arm64 distribution supports macOS 11.
    DEVELOPER_DIR="$("$script_directory/release-xcode.sh")"
    export DEVELOPER_DIR
    SDKROOT="$(xcrun --sdk macosx --show-sdk-path)"
    export SDKROOT
    llvm_cmake=(CMAKE_C_COMPILER=/usr/bin/clang CMAKE_CXX_COMPILER=/usr/bin/clang++
      CMAKE_OSX_DEPLOYMENT_TARGET=11.0 "CMAKE_OSX_SYSROOT=$SDKROOT")
    if ! command -v ninja >/dev/null; then
      build_tools="$rust_checkout/build/ohm-llvm-build-tools"
      uv venv --allow-existing --python python3 "$build_tools"
      uv pip install --only-binary :all: --python "$build_tools/bin/python" ninja==1.13.0
      export PATH="$build_tools/bin:$PATH"
    fi
  fi
  git -C "$rust_checkout" submodule update --init --depth 1 -- src/llvm-project
  llvm_checkout="$rust_checkout/src/llvm-project"
  if [[ "$(git -C "$llvm_checkout" rev-parse HEAD)" != "$llvm_revision" ||
    -n "$(git -C "$llvm_checkout" status --porcelain --untracked-files=all)" ]]; then
    echo "expected clean Ohm LLVM checkout at $llvm_revision" >&2
    exit 1
  fi

  source_major="$(sed -nE 's/^[[:space:]]*set\(LLVM_VERSION_MAJOR ([0-9]+)\)$/\1/p' "$llvm_checkout/cmake/Modules/LLVMVersion.cmake")"
  host_version="$("$host_llvm_dir/bin/llvm-profdata" --version)"
  if [[ ! "$host_version" =~ LLVM[[:space:]]version[[:space:]]([0-9]+)\. || "${BASH_REMATCH[1]}" != "$source_major" ]]; then
    echo "host LLVM profile tool must match pinned LLVM major version $source_major" >&2
    exit 1
  fi
  echo "Building Ohm LLVM $llvm_revision"
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
if ! awk -v toolchain="$toolchain" -v use_mimalloc="$use_mimalloc" -v build_llvm="$build_llvm" -v train_llvm="$train_llvm" '
  /^description[[:space:]]*=[[:space:]]*"Ohm"[[:space:]]*$/ {
    print "description = \"" toolchain "\""
    replacements++
    next
  }
  /^download-ci-llvm[[:space:]]*=[[:space:]]*true[[:space:]]*$/ && build_llvm == "true" {
    print "download-ci-llvm = false"
    print "link-shared = true"
    print "static-libstdcpp = true"
    if (train_llvm == "true") {
      print "thin-lto = true"
      print "libzstd = true"
      print "ninja = false"
    }
    llvm_replacements++
    next
  }
  { print }
  /^\[rust\][[:space:]]*$/ && use_mimalloc == "true" {
    print "mimalloc = true"
    allocator_replacements++
  }
  END {
    if (replacements != 1 || (build_llvm == "true" && llvm_replacements != 1)) exit 1
    if (use_mimalloc == "true" && allocator_replacements != 1) exit 1
  }
' "$bootstrap_config" >"$release_config"; then
  echo 'release bootstrap configuration is missing a required release setting' >&2
  exit 1
fi

if [[ "$build_llvm" == true ]]; then
  python3 - "${llvm_cmake[@]}" >> "$release_config" <<'PYCONF'
import json
import sys

print("\n[llvm.build-config]")
for entry in sys.argv[1:]:
    key, value = entry.split("=", 1)
    print(f"{key} = {json.dumps(value)}")
PYCONF
fi

export RUST_BOOTSTRAP_CONFIG="$release_config"
if [[ -n "${TMPDIR:-}" && "$TMPDIR" != /* ]]; then
  export TMPDIR="$PWD/$TMPDIR"
fi
cd -- "$rust_checkout"

# Historical toolchains also fetch Rust's matching CI LLVM here. A fork-backed
# build lets opt-dist compile and train the pinned source in its normal stages.
python3 "$rust_checkout/x.py" build \
  --ci false \
  --config "$release_config" \
  --build-dir "$build_dir" \
  --host "$target" \
  --target "$target" \
  "${bootstrap_targets[@]}"

opt_dist="$build_dir/$target/stage1-tools-bin/opt-dist"
if [[ ! -x "$opt_dist" ]]; then
  echo "optimized distribution tool was not built: $opt_dist" >&2
  exit 1
fi

llvm_dir="${host_llvm_dir:-$build_dir/$target/ci-llvm}"
llvm_profdata="$llvm_dir/bin/llvm-profdata"
if [[ ! -x "$llvm_profdata" ]]; then
  echo "matching LLVM profile tool is missing: $llvm_profdata" >&2
  exit 1
fi

release_name="${toolchain#ohm-}"
manifest="$script_directory/../toolchains/${release_name%-*}/${release_name##*-}.json"
prepare_relocated_dependencies=false
if [[ -f "$manifest" ]]; then
  prepare_relocated_dependencies="$(jq -r '.prepare_relocated_pgo_dependencies // false' "$manifest")"
fi
if [[ "$use_bolt" == true || "$build_llvm" == true || "$prepare_relocated_dependencies" == true ]]; then
  work_directory="$(mktemp -d "${TMPDIR:-/tmp}/ohm-opt-dist.XXXXXX")"
  llvm_container=
  trap 'if [[ -n "$llvm_container" ]]; then docker rm -f "$llvm_container" >/dev/null || true; fi; rm -rf -- "$work_directory"' EXIT
fi

if [[ "$train_llvm" == true ]]; then
  # LLVM and standalone LLD share a CMake installation and Clang toolchain.
  # Mount the Rust tree at the same path so bootstrap and opt-dist can use
  # their installed outputs and profiles on the host.
  llvm_container="$(docker run --detach --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" --env HOME=/tmp \
    --volume "$rust_checkout:$rust_checkout" --workdir "$rust_checkout" \
    "$llvm_image" /bin/sleep infinity)"
  docker exec -i "$llvm_container" /rustroot/bin/clang++ -fsyntax-only -x c++ - <<'HEADERS'
#include <features.h>
#include <iosfwd>
static_assert(__GLIBC__ == 2 && __GLIBC_MINOR__ == 17, "expected the CentOS 7 C headers");
static_assert(_GLIBCXX_RELEASE == 9, "expected the Rust distribution C++ headers");
HEADERS
fi

if [[ "$build_llvm" == true ]]; then
  # Bootstrap's llvm.build-config applies only to core LLVM. Standalone LLD
  # and other CMake projects from the same gitlink need the same host tools.
  if [[ "$train_llvm" == true ]]; then
    native_cmake=(-DCMAKE_C_COMPILER=/rustroot/bin/clang -DCMAKE_CXX_COMPILER=/rustroot/bin/clang++
      -DCMAKE_ASM_COMPILER=/rustroot/bin/clang -DCMAKE_AR=/rustroot/bin/llvm-ar -DCMAKE_RANLIB=/rustroot/bin/llvm-ranlib)
  else
    native_cmake=("${llvm_cmake[@]/#/-D}" -DCMAKE_ASM_COMPILER=/usr/bin/clang
      -DCMAKE_AR=/usr/bin/ar -DCMAKE_RANLIB=/usr/bin/ranlib)
  fi
  cmake_directory="$work_directory/cmake"
  mkdir -p "$cmake_directory"
  {
    printf '#!/usr/bin/env bash\nset -eu\n'
    printf 'llvm_source=%q\ncontainer=%q\nhost_cmake=%q\n' \
      "$rust_checkout/src/llvm-project" "$llvm_container" "$(command -v cmake)"
    printf 'native_cmake=('
    printf ' %q' "${native_cmake[@]}"
    printf ' )\n'
    cat <<'CMAKE'
source_dir=
cache=
configure=false
case "${1:-}" in
  --build | --install) cache="${2:-.}/CMakeCache.txt" ;;
  -S) source_dir="${2:-}"; configure=true ;;
  /*) source_dir="$1"; configure=true ;;
  *) cache="$PWD/CMakeCache.txt" ;;
esac
if [[ "$configure" == false && -f "$cache" ]]; then
  source_dir="$(sed -n 's/^CMAKE_HOME_DIRECTORY:INTERNAL=//p' "$cache")"
fi
case "$source_dir" in
  "$llvm_source" | "$llvm_source/"*) ;;
  *) exec "$host_cmake" "$@" ;;
esac
if [[ "$configure" == true ]]; then
  set -- "$@" "${native_cmake[@]}"
fi
if [[ -n "$container" ]]; then
  exec docker exec --workdir "$PWD" "$container" /usr/local/bin/cmake "$@"
fi
exec "$host_cmake" "$@"
CMAKE
  } > "$cmake_directory/cmake"
  chmod +x "$cmake_directory/cmake"
  export PATH="$cmake_directory:$PATH"
fi

if [[ "$use_bolt" == true ]]; then
  llvm_version="$("$llvm_profdata" --version)"
  if [[ ! "$llvm_version" =~ LLVM[[:space:]]version[[:space:]]([0-9]+)\. ]]; then
    echo "could not determine LLVM major version: $llvm_profdata" >&2
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
    echo "LLVM BOLT major version $bolt_major does not match LLVM $llvm_major" >&2
    exit 1
  fi

  merge_version="$("$bolt_llvm_dir/bin/merge-fdata" --version)"
  if [[ ! "$merge_version" =~ LLVM[[:space:]]version[[:space:]]([0-9]+)\. ]]; then
    echo "could not determine LLVM merge-fdata major version: $bolt_llvm_dir/bin/merge-fdata" >&2
    exit 1
  fi
  merge_major="${BASH_REMATCH[1]}"

  if [[ "$llvm_major" != "$merge_major" ]]; then
    echo "LLVM merge-fdata major version $merge_major does not match LLVM $llvm_major" >&2
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

opt_dist_arguments=(
  local
  --target-triple "$target"
  --std-target wasm32-unknown-unknown
  --checkout-dir "$rust_checkout"
  --llvm-dir "$llvm_dir"
  --artifact-dir build/opt-artifacts
  --build-dir build
  --build-llvm="$train_llvm"
  --llvm-shared="$build_llvm"
)
if [[ "$use_bolt" == true ]]; then
  opt_dist_arguments+=(--use-bolt)
fi

if [[ "$prepare_relocated_dependencies" == true ]]; then
  # rustc-perf moves each benchmark after preparing its dependencies. A build
  # script can embed that original path. Prepare the moved dependencies before
  # the profiler starts, keeping the upstream collector and the Rust checkout intact.
  perf_path=src/tools/rustc-perf
  perf_revision="$(git --no-replace-objects -C "$rust_checkout" rev-parse "HEAD:$perf_path")"
  perf_source="$rust_checkout/$perf_path"
  perf_checkout="$work_directory/rustc-perf"
  mkdir -- "$perf_checkout"
  if [[ ! -e "$perf_source/.git" ]]; then
    # Read the committed gitlink even if the caller staged a different revision or removal.
    (
      export GIT_INDEX_FILE="$perf_checkout/index"
      git --no-replace-objects -C "$rust_checkout" read-tree HEAD
      git --no-replace-objects -C "$rust_checkout" submodule update --init --checkout --depth 1 -- "$perf_path"
    )
    rm -- "$perf_checkout/index"
  fi
  if ! git --no-replace-objects -C "$perf_source" cat-file -e "$perf_revision^{commit}" 2>/dev/null; then
    # Supply the revision on stdin so Git selects the checkout's usual fetch remote.
    git --no-replace-objects -C "$perf_source" fetch --depth 1 --no-tags --no-write-fetch-head --stdin <<< "$perf_revision"
  fi
  # Isolate info/attributes while retaining the Git directory that selects
  # worktree-specific settings and conditional remotes for partial clones.
  (
    cd -P -- "$perf_source"
    git_dir="$(git rev-parse --absolute-git-dir)"
    common_dir="$(git rev-parse --git-common-dir)"
    common_dir="$(cd -P -- "$common_dir" && printf '%s/' "$PWD")"
    archive_common="$work_directory/collector.git"
    mkdir -- "$archive_common"
    ln -s -- "${common_dir}objects" "${common_dir}refs" "${common_dir}packed-refs" \
      "${common_dir}shallow" "${common_dir}reftable" "$archive_common/"
    git config --file "$archive_common/config" include.path "${common_dir}config"
    # Git selects the repository format before it follows config includes.
    while IFS= read -r -d '' setting; do
      key="${setting%%$'\n'*}"
      if [[ "$setting" == "$key" ]]; then
        value=true # A Git configuration key without a value is true.
      else
        value="${setting#*$'\n'}"
      fi
      git config --file "$archive_common/config" "$key" "$value"
    done < <(git config --local --no-includes --null --get-regexp '^(core\.repositoryformatversion$|extensions\.)')
    unset GIT_INDEX_FILE
    GIT_DIR="$git_dir" GIT_COMMON_DIR="$archive_common" GIT_WORK_TREE="$perf_source" \
      GIT_ATTR_NOSYSTEM=1 GIT_ATTR_SOURCE="$perf_revision" \
      git --no-replace-objects -c core.attributesFile=/dev/null archive "$perf_revision" | tar -x -C "$perf_checkout"
  )
  patch -d "$perf_checkout" -t -N -F 0 -p1 -i "$script_directory/../release/rustc-perf-relocated-dependencies.patch"
  opt_dist_arguments+=(--rustc-perf-checkout-dir "$perf_checkout")
fi

# This compiler rechecks dependencies with native inputs. rustc-perf expects
# the selected crate to be the only one compiled during each training run.
case "$toolchain" in
  ohm-1.99.0-20 | ohm-1.99.0-21)
    pinned_rust="$(jq -er '.sources.rust.revision' "$manifest")"
    if [[ "$(git --no-replace-objects -C "$rust_checkout" rev-parse --verify HEAD)" == "$pinned_rust" ]]; then
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
if [[ "$train_llvm" == true ]]; then
  components+=(llvm)
fi
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
      component == "llvm" && index($0, "_ZN4llvm") { primary = 1 }
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
