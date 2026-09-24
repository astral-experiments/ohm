#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_directory/.." && pwd)"
test_directory="$(mktemp -d "${TMPDIR:-/tmp}/ohm-optimized-dist.XXXXXX")"
trap 'rm -rf -- "$test_directory"' EXIT

rust_checkout="$test_directory/rust checkout"
bolt_directory="$test_directory/llvm bolt"
bootstrap_config="$test_directory/bootstrap.toml"
toolchain='ohm-1.97.1-16'
trace="$rust_checkout/commands.jsonl"

mkdir -p "$rust_checkout" "$bolt_directory/bin" "$bolt_directory/lib"
cp "$repository_root/release/bootstrap.toml" "$bootstrap_config"
cp "$bootstrap_config" "$test_directory/original-bootstrap.toml"

cat > "$rust_checkout/x.py" <<'PY'
#!/usr/bin/env python3
import json
import os
import pathlib
import shutil
import sys

checkout = pathlib.Path(__file__).resolve().parent
arguments = sys.argv[1:]

if "opt-dist" not in arguments or "src/llvm-project" not in arguments:
    raise SystemExit("bootstrap must build opt-dist and download the matching LLVM")

build_directory = pathlib.Path(arguments[arguments.index("--build-dir") + 1])
target = arguments[arguments.index("--target") + 1]
config = arguments[arguments.index("--config") + 1]
if os.environ.get("RUST_BOOTSTRAP_CONFIG") != config:
    raise SystemExit("bootstrap did not inherit the release configuration")

with (checkout / "commands.jsonl").open("a", encoding="utf-8") as output:
    json.dump(
        {
            "kind": "bootstrap",
            "arguments": arguments,
            "bootstrap_config": os.environ.get("RUST_BOOTSTRAP_CONFIG"),
        },
        output,
    )
    output.write("\n")

tools = build_directory / target / "stage1-tools-bin"
tools.mkdir(parents=True, exist_ok=True)
shutil.copy2(checkout / "fixture-opt-dist", tools / "opt-dist")

llvm = build_directory / target / "ci-llvm" / "bin"
llvm.mkdir(parents=True, exist_ok=True)
if os.environ.get("FIXTURE_SKIP_PROFDATA") != "1":
    shutil.copy2(checkout / "fixture-llvm-tool", llvm / "llvm-profdata")
PY

cat > "$rust_checkout/fixture-opt-dist" <<'PY'
#!/usr/bin/env python3
import json
import os
import pathlib
import sys

checkout = pathlib.Path(__file__).resolve().parents[3]
arguments = sys.argv[1:]
artifact_directory = checkout / arguments[arguments.index("--artifact-dir") + 1]
artifact_directory.mkdir(parents=True, exist_ok=True)


def fixture_component(name: str) -> str:
    marker = checkout / f"fixture-{name}-pgo-component"
    return marker.read_text(encoding="utf-8").strip() if marker.exists() else ""


component_pgo = (checkout / "src/tools/opt-dist/component-pgo-v1").is_file()
profiles = {"rustc": "rustc"}
if component_pgo:
    profiles.update({"rustdoc": "rustdoc", "cargo": "rustc"})
    if os.environ.get("DIST_TRY_BUILD", "0") == "0":
        profiles.update({component: component for component in ("clippy", "rustfmt")})

profile_functions = {
    "rustc": ["_RNvCs_17rustc_driver_impl12run_compiler"],
    "rustdoc": ["_RNvCs_7rustdoc4main"],
    "clippy": ["_RNvCs_12clippy_lints4main"],
    "rustfmt": ["_RNvCs_15rustfmt_nightly6format", "_RNvCs_9cargo_fmt11incremental"],
}
if component_pgo:
    profile_functions["rustc"].append("_RNvCs_5cargo4main")

missing_component = fixture_component("missing")
empty_component = fixture_component("empty")
symlink_component = fixture_component("symlink")
corrupt_component = fixture_component("corrupt")
wrong_component = fixture_component("wrong")
missing_coverage = fixture_component("missing-coverage")
for component in ("rustc", "rustdoc", "clippy", "rustfmt"):
    profile = artifact_directory / f"{component}-pgo.profdata"
    profile.unlink(missing_ok=True)
    if component not in profiles or component == missing_component:
        continue
    if component == symlink_component:
        external_profile = checkout / "fixture-external.profdata"
        external_profile.write_bytes(b"fixture external profile\n")
        profile.symlink_to(external_profile)
    elif component == empty_component:
        profile.write_bytes(b"")
    elif component == corrupt_component:
        profile.write_bytes(b"not a valid LLVM instrumentation profile\n")
    else:
        function_component = component
        if component == wrong_component:
            function_component = {
                "rustc": "rustdoc",
                "rustdoc": "rustc",
                "clippy": "rustfmt",
                "rustfmt": "clippy",
            }[component]
        functions = profile_functions[function_component]
        if missing_coverage == "cargo" and component == "rustc":
            functions = [function for function in functions if "_5cargo" not in function]
        if missing_coverage == "cargo-fmt" and component == "rustfmt":
            functions = [function for function in functions if "_9cargo_fmt" not in function]
        profile.write_text(
            "fixture LLVM instrumentation profile\n" + "\n".join(functions) + "\n",
            encoding="utf-8",
        )

with (checkout / "commands.jsonl").open("a", encoding="utf-8") as output:
    json.dump(
        {
            "kind": "opt-dist",
            "arguments": arguments,
            "environment": dict(os.environ),
            "profiles": profiles,
        },
        output,
    )
    output.write("\n")

# Real opt-dist prints every inherited environment variable without redaction.
for key, value in sorted(os.environ.items()):
    print(f"{key}={value}")
PY

cat > "$rust_checkout/fixture-llvm-tool" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

tool="$(basename -- "$0")"
if [[ "$tool" == 'llvm-profdata' && "${1:-}" == 'show' ]]; then
  if [[ $# -ne 3 || "$2" != '--covered' ]]; then
    echo "unexpected LLVM profile fixture invocation: $*" >&2
    exit 1
  fi

  if ! IFS= read -r profile_header < "$3" || \
    [[ "$profile_header" != 'fixture LLVM instrumentation profile' ]]; then
    echo "invalid instrumentation profile: $3" >&2
    exit 1
  fi

  tail -n +2 "$3"
  exit 0
fi

if [[ "${1:-}" != '--version' ]]; then
  echo "unexpected LLVM fixture invocation: $*" >&2
  exit 1
fi

case "$tool" in
  llvm-bolt) version="${FIXTURE_BOLT_MAJOR:-22}.1.8" ;;
  merge-fdata) version="${FIXTURE_MERGE_MAJOR:-22}.1.8" ;;
  llvm-profdata) version="${FIXTURE_PROFDATA_MAJOR:-22}.1.6-rust-1.97.1-stable" ;;
  *)
    echo "unexpected LLVM fixture tool: $0" >&2
    exit 1
    ;;
esac

printf 'LLVM (http://llvm.org/):\n  LLVM version %s\n' "$version"
SH

chmod +x "$rust_checkout/fixture-opt-dist" "$rust_checkout/fixture-llvm-tool"
cp "$rust_checkout/fixture-llvm-tool" "$bolt_directory/bin/llvm-bolt"
cp "$rust_checkout/fixture-llvm-tool" "$bolt_directory/bin/merge-fdata"
touch "$bolt_directory/lib/libbolt_rt_instr.a"

run_optimized_build() {
  local target="$1"
  local output="$2"
  shift 2

  env \
    OHM_BOLT_LLVM_DIR="$bolt_directory" \
    OHM_RELEASE_APP_PRIVATE_KEY='fixture-private-key-must-not-leak' \
    MIRROR_R2_SECRET_ACCESS_KEY='fixture-r2-secret-must-not-leak' \
    GH_TOKEN='fixture-github-token-must-not-leak' \
    ACTIONS_RUNTIME_TOKEN='fixture-runtime-token-must-not-leak' \
    EXAMPLE_PASSWORD='fixture-password-must-not-leak' \
    UNRELATED_ENVIRONMENT_VALUE='fixture-unrelated-value-must-not-leak' \
    DIST_TRY_BUILD=1 \
    DEVELOPER_DIR='/fixture/Xcode.app/Contents/Developer' \
    MACOSX_STD_DEPLOYMENT_TARGET='11.0' \
    "$@" \
    bash "$script_directory/build-optimized-dist.sh" \
    "$target" "$toolchain" "$rust_checkout" "$bootstrap_config" \
    > "$output" 2>&1
}

assert_optimized_build() {
  local target="$1"
  local expected_llvm_directory="$2"
  local expect_bolt="$3"
  local component_pgo="$4"
  local output="$5"

  python3 - "$trace" "$bootstrap_config" "$rust_checkout" "$toolchain" \
    "$target" "$expected_llvm_directory" "$expect_bolt" "$component_pgo" "$output" <<'PY'
import json
import pathlib
import sys
import tomllib

(
    trace_path,
    original_config,
    checkout,
    toolchain,
    target,
    expected_llvm,
    expect_bolt,
    component_pgo,
    output_path,
) = sys.argv[1:]
checkout = pathlib.Path(checkout).resolve()
generated_config = checkout / "build" / "ohm-release-bootstrap.toml"
events = [
    json.loads(line)
    for line in pathlib.Path(trace_path).read_text(encoding="utf-8").splitlines()
]
if [event["kind"] for event in events] != ["bootstrap", "opt-dist"]:
    raise SystemExit(f"expected one bootstrap and one opt-dist invocation: {events}")


def option(arguments: list[str], name: str) -> str:
    for index, argument in enumerate(arguments):
        if argument == name:
            return arguments[index + 1]
        if argument.startswith(f"{name}="):
            return argument[len(name) + 1 :]
    raise SystemExit(f"missing {name} in {arguments}")


bootstrap = events[0]
bootstrap_arguments = bootstrap["arguments"]
if not bootstrap_arguments or bootstrap_arguments[0] != "build":
    raise SystemExit(f"expected an upstream bootstrap build: {bootstrap_arguments}")
if bootstrap_arguments[-2:] != ["opt-dist", "src/llvm-project"]:
    raise SystemExit(f"bootstrap must explicitly request opt-dist and LLVM: {bootstrap_arguments}")
if option(bootstrap_arguments, "--ci") != "false":
    raise SystemExit("bootstrap must not impersonate Rust's protected CI")
if option(bootstrap_arguments, "--config") != str(generated_config):
    raise SystemExit("bootstrap did not use the generated complete release configuration")
if option(bootstrap_arguments, "--build-dir") != str(checkout / "build"):
    raise SystemExit("bootstrap used an unexpected build directory")
if option(bootstrap_arguments, "--host") != target:
    raise SystemExit("bootstrap used the wrong host")
if option(bootstrap_arguments, "--target") != target:
    raise SystemExit("bootstrap used the wrong target")
if bootstrap["bootstrap_config"] != str(generated_config):
    raise SystemExit("bootstrap did not inherit the complete release configuration")

original = tomllib.loads(pathlib.Path(original_config).read_text(encoding="utf-8"))
generated = tomllib.loads(generated_config.read_text(encoding="utf-8"))
if generated.get("build", {}).get("description") != toolchain:
    raise SystemExit("optimized bootstrap did not preserve the immutable toolchain identity")
if generated.get("build", {}).get("metrics") is not True:
    raise SystemExit("upstream opt-dist requires bootstrap build metrics")
if generated.get("build", {}).get("profiler") is not True:
    raise SystemExit("component-specific PGO requires Rust's profiler runtime")
if generated.get("build", {}).get("cargo-native-static") is not True:
    raise SystemExit("optimized Cargo must retain its static native dependencies")
if generated.get("build", {}).get("locked-deps") is not True:
    raise SystemExit("component PGO must preserve locked release dependencies")
if generated.get("llvm", {}).get("download-ci-llvm") is not True:
    raise SystemExit("component PGO must reuse Rust's optimized CI LLVM")
if generated.get("rust", {}).get("lld") is not True:
    raise SystemExit("Wasm builds require the bundled rust-lld linker")
if generated.get("target", {}).get("wasm32-unknown-unknown", {}).get("profiler") is not False:
    raise SystemExit("the bare Wasm target must not build the native profiling runtime")
required_tools = {
    "analysis", "cargo", "clippy", "rust-analyzer-proc-macro-srv", "rustdoc", "rustfmt"
}
if not required_tools.issubset(generated.get("build", {}).get("tools", [])):
    raise SystemExit("component PGO must preserve every packaged release tool")
if "ohm-defaults" not in generated.get("build", {}).get("tool", {}).get(
    "cargo", {}
).get("features", []):
    raise SystemExit("optimized Cargo must preserve Ohm's default features")
generated["build"]["description"] = original["build"]["description"]
supports_mimalloc = (checkout / "compiler/rustc/mimalloc-v1").is_file()
if target == "x86_64-unknown-linux-gnu" and supports_mimalloc:
    if generated["rust"].pop("mimalloc", None) is not True:
        raise SystemExit("Linux rustc must use the supported mimalloc allocator")
if generated["rust"].get("jemalloc") is not True:
    raise SystemExit("rustdoc and Clippy must retain jemalloc")
if generated != original:
    raise SystemExit("generated bootstrap configuration changed unrelated release settings")

optimized = events[1]
arguments = optimized["arguments"]
expected_profiles = {"rustc": "rustc"}
if component_pgo == "true":
    expected_profiles.update(
        {
            "rustdoc": "rustdoc",
            "cargo": "rustc",
            "clippy": "clippy",
            "rustfmt": "rustfmt",
        }
    )
if optimized.get("profiles") != expected_profiles:
    raise SystemExit(f"release produced unexpected PGO component profiles: {optimized}")
for component in set(expected_profiles.values()):
    profile = checkout / "build" / "opt-artifacts" / f"{component}-pgo.profdata"
    if not profile.is_file() or profile.is_symlink() or profile.stat().st_size == 0:
        raise SystemExit(f"release has an invalid {component} PGO profile: {profile}")
if (checkout / "build" / "opt-artifacts" / "cargo-pgo.profdata").exists():
    raise SystemExit("Cargo must consume rustc's profile instead of a separate Cargo profile")
if component_pgo == "false":
    for component in ("rustdoc", "clippy", "rustfmt"):
        if (checkout / "build" / "opt-artifacts" / f"{component}-pgo.profdata").exists():
            raise SystemExit(f"legacy Rust revision unexpectedly produced a {component} profile")
if not arguments or arguments[0] != "local":
    raise SystemExit(f"expected upstream opt-dist local: {arguments}")
separator = arguments.index("--")
pipeline_arguments = arguments[1:separator]
distribution_arguments = arguments[separator + 1 :]

if option(pipeline_arguments, "--target-triple") != target:
    raise SystemExit("opt-dist used the wrong host target")
if option(pipeline_arguments, "--std-target") != "wasm32-unknown-unknown":
    raise SystemExit("opt-dist must build Wasm std before preserving stage1 for packaging")
if option(pipeline_arguments, "--checkout-dir") != str(checkout):
    raise SystemExit("opt-dist used the wrong pinned Rust checkout")
if option(pipeline_arguments, "--llvm-dir") != str(pathlib.Path(expected_llvm).resolve()):
    raise SystemExit("opt-dist used the wrong matching LLVM installation")
if option(pipeline_arguments, "--artifact-dir") != "build/opt-artifacts":
    raise SystemExit("optimization artifacts escaped the isolated Rust build directory")
if option(pipeline_arguments, "--build-dir") != "build":
    raise SystemExit("opt-dist used a build directory inconsistent with bootstrap")
if option(pipeline_arguments, "--build-llvm") != "false":
    raise SystemExit("opt-dist must reuse Rust's matching preoptimized CI LLVM")
if option(pipeline_arguments, "--llvm-shared") != "false":
    raise SystemExit("opt-dist must not override downloaded CI LLVM settings")
if ("--use-bolt" in pipeline_arguments) != (expect_bolt == "true"):
    raise SystemExit(f"incorrect target-specific BOLT selection: {pipeline_arguments}")
for unsupported_argument in (
    "--run-tests",
    "--rustc-perf-checkout-dir",
    "--benchmark-cargo-config",
):
    if any(
        argument == unsupported_argument
        or argument.startswith(f"{unsupported_argument}=")
        for argument in pipeline_arguments
    ):
        raise SystemExit(f"opt-dist unexpectedly overrides Rust's upstream defaults: {unsupported_argument}")

if distribution_arguments[:3] != ["python3", str(checkout / "x.py"), "dist"]:
    raise SystemExit(f"opt-dist did not preserve the full x.py distribution command: {distribution_arguments}")
if option(distribution_arguments, "--ci") != "false":
    raise SystemExit("final distribution must not impersonate Rust's protected CI")
if option(distribution_arguments, "--config") != str(generated_config):
    raise SystemExit("final distribution did not use the complete release configuration")
if option(distribution_arguments, "--build-dir") != str(checkout / "build"):
    raise SystemExit("final distribution used an inconsistent build directory")
if option(distribution_arguments, "--host") != target:
    raise SystemExit("final distribution used the wrong host")
if option(distribution_arguments, "--target") != f"{target},wasm32-unknown-unknown":
    raise SystemExit("final distribution must include the host and Wasm targets")
if option(distribution_arguments, "--set") != f"build.description={toolchain}":
    raise SystemExit("final distribution changed the immutable toolchain identity")
if distribution_arguments[-1] != "extended":
    raise SystemExit("optimized releases must contain the complete extended distribution")

environment = optimized["environment"]
if environment.get("RUST_BOOTSTRAP_CONFIG") != str(generated_config):
    raise SystemExit("internal PGO stages will not inherit the complete release configuration")
if environment.get("DIST_TRY_BUILD") != "0":
    raise SystemExit("release mode must never skip optional Clippy or rustfmt profiles")
if environment.get("GITHUB_ACTIONS") != "false":
    raise SystemExit("internal PGO stages would incorrectly impersonate Rust's protected CI")
if environment.get("DEVELOPER_DIR") != "/fixture/Xcode.app/Contents/Developer":
    raise SystemExit("internal PGO stages changed the selected macOS developer tools")
if environment.get("MACOSX_STD_DEPLOYMENT_TARGET") != "11.0":
    raise SystemExit("internal PGO stages changed the macOS standard-library deployment target")
for sensitive in (
    "OHM_RELEASE_APP_PRIVATE_KEY",
    "MIRROR_R2_SECRET_ACCESS_KEY",
    "GH_TOKEN",
    "ACTIONS_RUNTIME_TOKEN",
    "EXAMPLE_PASSWORD",
    "UNRELATED_ENVIRONMENT_VALUE",
    "OHM_BOLT_LLVM_DIR",
):
    if sensitive in environment:
        raise SystemExit(f"upstream opt-dist would expose an inherited environment value: {sensitive}")

output = pathlib.Path(output_path).read_text(encoding="utf-8")
if "must-not-leak" in output:
    raise SystemExit("upstream opt-dist printed an inherited release credential")
if component_pgo == "true":
    if "verified executed PGO profile coverage for rustc, rustdoc, Cargo, Clippy, rustfmt, and cargo-fmt" not in output:
        raise SystemExit("component-specific release did not verify every executed tool")
elif "verified executed rustc PGO profile coverage for a legacy Rust source revision" not in output:
    raise SystemExit("legacy release did not verify its executed rustc profile")
PY

  if ! cmp -s "$bootstrap_config" "$test_directory/original-bootstrap.toml"; then
    echo 'optimized build modified the pinned release bootstrap configuration' >&2
    exit 1
  fi
}

linux_target='x86_64-unknown-linux-gnu'
macos_target='aarch64-apple-darwin'
component_pgo_marker="$rust_checkout/src/tools/opt-dist/component-pgo-v1"

: > "$trace"
legacy_linux_output="$test_directory/legacy-linux-output.log"
run_optimized_build "$linux_target" "$legacy_linux_output"
assert_optimized_build "$linux_target" "$bolt_directory" true false "$legacy_linux_output"

if [[ ! "$bolt_directory/bin/llvm-profdata" -ef \
  "$rust_checkout/build/$linux_target/ci-llvm/bin/llvm-profdata" ]]; then
  echo 'Linux BOLT did not use the exact matching Rust LLVM profile tool' >&2
  exit 1
fi

: > "$trace"
legacy_macos_output="$test_directory/legacy-macos-output.log"
run_optimized_build "$macos_target" "$legacy_macos_output"
assert_optimized_build \
  "$macos_target" \
  "$rust_checkout/build/$macos_target/ci-llvm" \
  false \
  false \
  "$legacy_macos_output"

mkdir -p "$(dirname -- "$component_pgo_marker")"
printf '%s\n' 'fixture component-specific PGO capability' > "$component_pgo_marker"

: > "$trace"
linux_output="$test_directory/linux-output.log"
run_optimized_build "$linux_target" "$linux_output"
assert_optimized_build "$linux_target" "$bolt_directory" true true "$linux_output"

: > "$trace"
macos_output="$test_directory/macos-output.log"
run_optimized_build "$macos_target" "$macos_output"
assert_optimized_build \
  "$macos_target" \
  "$rust_checkout/build/$macos_target/ci-llvm" \
  false \
  true \
  "$macos_output"

allocator_marker="$rust_checkout/compiler/rustc/mimalloc-v1"
mkdir -p "$(dirname -- "$allocator_marker")"
touch "$allocator_marker"

: > "$trace"
mimalloc_linux_output="$test_directory/mimalloc-linux-output.log"
run_optimized_build "$linux_target" "$mimalloc_linux_output"
assert_optimized_build "$linux_target" "$bolt_directory" true true "$mimalloc_linux_output"

: > "$trace"
mimalloc_macos_output="$test_directory/mimalloc-macos-output.log"
run_optimized_build "$macos_target" "$mimalloc_macos_output"
assert_optimized_build "$macos_target" "$rust_checkout/build/$macos_target/ci-llvm" false true "$mimalloc_macos_output"

rm "$allocator_marker"

expect_failure() {
  local description="$1"
  local target="$2"
  shift 2

  if run_optimized_build "$target" "$test_directory/failure-output.log" "$@"; then
    echo "optimized release accepted $description" >&2
    exit 1
  fi
}

for component in rustc rustdoc clippy rustfmt; do
  printf '%s\n' "$component" > "$rust_checkout/fixture-missing-pgo-component"
  expect_failure "a missing $component profile" "$linux_target"
  : > "$rust_checkout/fixture-missing-pgo-component"

  printf '%s\n' "$component" > "$rust_checkout/fixture-empty-pgo-component"
  expect_failure "an empty $component profile" "$macos_target"
  : > "$rust_checkout/fixture-empty-pgo-component"

  printf '%s\n' "$component" > "$rust_checkout/fixture-corrupt-pgo-component"
  expect_failure "a corrupt $component profile" "$linux_target"
  : > "$rust_checkout/fixture-corrupt-pgo-component"

  printf '%s\n' "$component" > "$rust_checkout/fixture-wrong-pgo-component"
  expect_failure "a valid $component profile containing another component's functions" "$macos_target"
  : > "$rust_checkout/fixture-wrong-pgo-component"
done

printf '%s\n' 'rustfmt' > "$rust_checkout/fixture-symlink-pgo-component"
expect_failure 'a rustfmt profile escaping the artifact directory' "$linux_target"
: > "$rust_checkout/fixture-symlink-pgo-component"

printf '%s\n' 'cargo' > "$rust_checkout/fixture-missing-coverage-pgo-component"
expect_failure 'a rustc profile without executed Cargo coverage' "$linux_target"
: > "$rust_checkout/fixture-missing-coverage-pgo-component"

printf '%s\n' 'cargo-fmt' > "$rust_checkout/fixture-missing-coverage-pgo-component"
expect_failure 'a rustfmt profile without executed cargo-fmt coverage' "$macos_target"
: > "$rust_checkout/fixture-missing-coverage-pgo-component"

expect_failure 'an unsupported host target' 'aarch64-unknown-linux-gnu'

for missing_binary in llvm-bolt merge-fdata; do
  mv "$bolt_directory/bin/$missing_binary" \
    "$bolt_directory/bin/$missing_binary.hidden"
  expect_failure "a missing $missing_binary executable" "$linux_target"
  mv "$bolt_directory/bin/$missing_binary.hidden" \
    "$bolt_directory/bin/$missing_binary"
done

mv "$bolt_directory/lib/libbolt_rt_instr.a" \
  "$bolt_directory/lib/libbolt_rt_instr.a.hidden"
expect_failure 'a missing BOLT instrumentation runtime' "$linux_target"
mv "$bolt_directory/lib/libbolt_rt_instr.a.hidden" \
  "$bolt_directory/lib/libbolt_rt_instr.a"

expect_failure 'a mismatched LLVM BOLT major version' "$linux_target" \
  FIXTURE_BOLT_MAJOR=21
expect_failure 'a mismatched BOLT profile merger major version' "$linux_target" \
  FIXTURE_MERGE_MAJOR=21

macos_profdata="$rust_checkout/build/$macos_target/ci-llvm/bin/llvm-profdata"
mv "$macos_profdata" "$macos_profdata.hidden"
expect_failure 'a missing matching macOS LLVM profile tool' "$macos_target" \
  FIXTURE_SKIP_PROFDATA=1
mv "$macos_profdata.hidden" "$macos_profdata"

if env OHM_BOLT_LLVM_DIR="$bolt_directory" \
  bash "$script_directory/build-optimized-dist.sh" \
  "$linux_target" 'ohm-1.97.1-16"; injected = true' \
  "$rust_checkout" "$bootstrap_config" \
  > "$test_directory/failure-output.log" 2>&1; then
  echo 'optimized release accepted an unsafe toolchain identity' >&2
  exit 1
fi

wild_directory="$test_directory/wild payload"
mkdir -p "$wild_directory"
cp "$rust_checkout/fixture-llvm-tool" "$wild_directory/wild"
touch "$wild_directory/LICENSE-APACHE" "$wild_directory/LICENSE-MIT"
run_optimized_build "$linux_target" "$test_directory/wild-output.log" \
  OHM_WILD_LINKER_DIR="$wild_directory"
python3 - "$trace" "$wild_directory" <<'PY'
import json
import pathlib
import sys
events = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines()]
event = events[-1]
assert f"target.x86_64-unknown-linux-gnu.ohm-wild-linker={sys.argv[2]}" in event["arguments"]
assert "OHM_WILD_LINKER_DIR" not in event["environment"]
assert event["environment"]["CARGO_UNSTABLE_OHM_LINKER"] == "lld"
PY
expect_failure 'a Wild payload on macOS' "$macos_target" OHM_WILD_LINKER_DIR="$wild_directory"

echo 'optimized release build tests passed'
