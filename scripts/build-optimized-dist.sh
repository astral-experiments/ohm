#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo 'usage: build-optimized-dist.sh TARGET TOOLCHAIN RUST_CHECKOUT BOOTSTRAP_CONFIG' >&2
  exit 2
fi

target="$1"
toolchain="$2"
rust_checkout="$3"
bootstrap_config="$4"
script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
stage0_cargo_proxy="$script_directory/pgo-stage0-cargo.py"
development_runner="$script_directory/profile-development-workflows.py"

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

if [[ ! -x "$stage0_cargo_proxy" || ! -x "$development_runner" ]]; then
  echo 'Ohm development profiling tools are missing or not executable' >&2
  exit 1
fi

if [[ ${OHM_DEVELOPMENT_SOURCE_ROOT+x} == x ]]; then
  if [[ ! -d "$OHM_DEVELOPMENT_SOURCE_ROOT" ]]; then
    echo "local development corpus root not found: $OHM_DEVELOPMENT_SOURCE_ROOT" >&2
    exit 1
  fi
  OHM_DEVELOPMENT_SOURCE_ROOT="$(cd -- "$OHM_DEVELOPMENT_SOURCE_ROOT" && pwd -P)"
fi

rust_checkout="$(cd -- "$rust_checkout" && pwd -P)"
bootstrap_config="$(
  cd -- "$(dirname -- "$bootstrap_config")"
  printf '%s/%s\n' "$PWD" "$(basename -- "$bootstrap_config")"
)"

if [[ "$use_bolt" == true ]]; then
  if [[ -z "${OHM_BOLT_LLVM_DIR:-}" ]]; then
    echo 'Linux optimized releases require OHM_BOLT_LLVM_DIR' >&2
    exit 1
  fi

  if [[ ! -d "$OHM_BOLT_LLVM_DIR" ]]; then
    echo "LLVM BOLT directory not found: $OHM_BOLT_LLVM_DIR" >&2
    exit 1
  fi

  bolt_llvm_dir="$(cd -- "$OHM_BOLT_LLVM_DIR" && pwd -P)"
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
if ! awk -v toolchain="$toolchain" '
  /^description[[:space:]]*=[[:space:]]*"Ohm"[[:space:]]*$/ {
    print "description = \"" toolchain "\""
    replacements++
    next
  }
  { print }
  END { if (replacements != 1) exit 1 }
' "$bootstrap_config" >"$release_config"; then
  echo 'release bootstrap configuration must contain exactly one Ohm build description' >&2
  exit 1
fi

export RUST_BOOTSTRAP_CONFIG="$release_config"
cd -- "$rust_checkout"

# `opt-dist` is a bootstrap-only tool and does not itself require LLVM. Ask for
# LLVM explicitly so bootstrap downloads its already-optimized CI artifact
# before the optimization pipeline needs the matching llvm-profdata executable.
# Build Cargo with stage zero so the release configuration's ohm-defaults
# feature is available without building an additional compiler first.
python3 "$rust_checkout/x.py" build \
  --ci false \
  --config "$release_config" \
  --build-dir "$build_dir" \
  --host "$target" \
  --target "$target" \
  --stage 1 \
  opt-dist \
  src/llvm-project \
  src/tools/cargo

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

target_build_dir="$build_dir/$target"
upstream_stage0_root="$target_build_dir/stage0"
upstream_stage0_cargo="$upstream_stage0_root/bin/cargo"
upstream_stage0_rustc="$upstream_stage0_root/bin/rustc"
ohm_cargo="$target_build_dir/stage1-tools-bin/cargo"

if [[ ! -x "$upstream_stage0_cargo" || ! -x "$upstream_stage0_rustc" ]]; then
  echo "upstream stage-zero compiler tools were not downloaded: $upstream_stage0_root" >&2
  exit 1
fi
if [[ ! -d "$upstream_stage0_root/lib" ]]; then
  echo "upstream stage-zero compiler libraries are missing: $upstream_stage0_root/lib" >&2
  exit 1
fi
if [[ ! -x "$ohm_cargo" ]]; then
  echo "feature-enabled stage-one Ohm Cargo was not built: $ohm_cargo" >&2
  exit 1
fi

stage0_proxy_root="$target_build_dir/ohm-pgo-stage0"
mkdir -p "$stage0_proxy_root/bin"

ensure_stage0_link() {
  local destination="$1"
  local source="$2"

  if [[ -e "$destination" || -L "$destination" ]]; then
    if [[ ! "$destination" -ef "$source" ]]; then
      echo "stage-zero profiling link has an unexpected destination: $destination" >&2
      return 1
    fi
  else
    ln -s "$source" "$destination"
  fi
}

ensure_stage0_link "$stage0_proxy_root/bin/cargo" "$stage0_cargo_proxy"
ensure_stage0_link "$stage0_proxy_root/bin/rustc" "$upstream_stage0_rustc"
for directory in lib libexec etc share; do
  if [[ -d "$upstream_stage0_root/$directory" ]]; then
    ensure_stage0_link \
      "$stage0_proxy_root/$directory" \
      "$upstream_stage0_root/$directory"
  fi
done

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

  bolt_profdata="$bolt_llvm_dir/bin/llvm-profdata"
  if [[ -e "$bolt_profdata" || -L "$bolt_profdata" ]]; then
    if [[ ! "$bolt_profdata" -ef "$llvm_profdata" ]]; then
      echo "LLVM BOLT profile tool does not match downloaded Rust LLVM: $bolt_profdata" >&2
      exit 1
    fi
  else
    ln -s "$llvm_profdata" "$bolt_profdata"
  fi

  llvm_dir="$bolt_llvm_dir"
fi

# Upstream opt-dist logs every environment variable before doing any work.
# Never pass GitHub tokens, signing material, or publication credentials into
# that process; retain only explicitly reviewed build-system variables.
safe_environment=(
  "PATH=$PATH"
  "HOME=$HOME"
  "RUST_BOOTSTRAP_CONFIG=$release_config"
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
  CARGO_BUILD_JOBS \
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
  MACOSX_STD_DEPLOYMENT_TARGET \
  OHM_DEVELOPMENT_SOURCE_ROOT; do
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
  --checkout-dir "$rust_checkout"
  --llvm-dir "$llvm_dir"
  --artifact-dir build/opt-artifacts
  --build-dir build
  --stage0-root "$stage0_proxy_root"
  --build-llvm=false
  --llvm-shared=false
)
if [[ "$use_bolt" == true ]]; then
  opt_dist_arguments+=(--use-bolt)
fi

env -i "${safe_environment[@]}" \
  "$opt_dist" "${opt_dist_arguments[@]}" \
  -- \
  python3 "$rust_checkout/x.py" dist \
  --ci false \
  --config "$release_config" \
  --build-dir "$build_dir" \
  --host "$target" \
  --target "$target" \
  --set "build.description=$toolchain" \
  extended
