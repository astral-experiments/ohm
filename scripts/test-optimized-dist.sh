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
with (checkout / "commands.jsonl").open("a", encoding="utf-8") as output:
    json.dump(
        {
            "kind": "opt-dist",
            "arguments": sys.argv[1:],
            "environment": dict(os.environ),
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

if [[ "${1:-}" != '--version' ]]; then
  echo "unexpected LLVM fixture invocation: $*" >&2
  exit 1
fi

case "$(basename -- "$0")" in
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
  local output="$4"

  python3 - "$trace" "$bootstrap_config" "$rust_checkout" "$toolchain" \
    "$target" "$expected_llvm_directory" "$expect_bolt" "$output" <<'PY'
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
    raise SystemExit("upstream rustc PGO requires Rust's profiler runtime")
generated["build"]["description"] = original["build"]["description"]
if generated != original:
    raise SystemExit("generated bootstrap configuration changed more than its build description")

optimized = events[1]
arguments = optimized["arguments"]
if not arguments or arguments[0] != "local":
    raise SystemExit(f"expected upstream opt-dist local: {arguments}")
separator = arguments.index("--")
pipeline_arguments = arguments[1:separator]
distribution_arguments = arguments[separator + 1 :]

if option(pipeline_arguments, "--target-triple") != target:
    raise SystemExit("opt-dist used the wrong host target")
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
if option(distribution_arguments, "--target") != target:
    raise SystemExit("final distribution used the wrong target")
if option(distribution_arguments, "--set") != f"build.description={toolchain}":
    raise SystemExit("final distribution changed the immutable toolchain identity")
if distribution_arguments[-1] != "extended":
    raise SystemExit("optimized releases must contain the complete extended distribution")

environment = optimized["environment"]
if environment.get("RUST_BOOTSTRAP_CONFIG") != str(generated_config):
    raise SystemExit("internal PGO stages will not inherit the complete release configuration")
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
PY

  if ! cmp -s "$bootstrap_config" "$test_directory/original-bootstrap.toml"; then
    echo 'optimized build modified the pinned release bootstrap configuration' >&2
    exit 1
  fi
}

linux_target='x86_64-unknown-linux-gnu'
macos_target='aarch64-apple-darwin'

: > "$trace"
linux_output="$test_directory/linux-output.log"
run_optimized_build "$linux_target" "$linux_output"
assert_optimized_build "$linux_target" "$bolt_directory" true "$linux_output"

if [[ ! "$bolt_directory/bin/llvm-profdata" -ef \
  "$rust_checkout/build/$linux_target/ci-llvm/bin/llvm-profdata" ]]; then
  echo 'Linux BOLT did not use the exact matching Rust LLVM profile tool' >&2
  exit 1
fi

: > "$trace"
macos_output="$test_directory/macos-output.log"
run_optimized_build "$macos_target" "$macos_output"
assert_optimized_build \
  "$macos_target" \
  "$rust_checkout/build/$macos_target/ci-llvm" \
  false \
  "$macos_output"

expect_failure() {
  local description="$1"
  local target="$2"
  shift 2

  if run_optimized_build "$target" "$test_directory/failure-output.log" "$@"; then
    echo "optimized release accepted $description" >&2
    exit 1
  fi
}

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

echo 'optimized release build tests passed'
