#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "$0")" && pwd)"
installer="$script_directory/install.sh"
temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/ohm-installer-test.XXXXXXXX")"
trap 'rm -rf "$temporary_directory"' EXIT

release_directory="$temporary_directory/release"
fixture_directory="$temporary_directory/fixture"
mock_directory="$temporary_directory/mocks"
version="ohm-1.97.1-2"
archive_name="$version-aarch64-apple-darwin.tar.xz"
archive_root="rust-1.97.1-dev-aarch64-apple-darwin"
mkdir -p "$release_directory" "$fixture_directory/$archive_root" "$mock_directory"

cat > "$fixture_directory/$archive_root/install.sh" <<'EOF'
#!/bin/sh
set -eu

prefix=
for argument in "$@"; do
  case "$argument" in
    --prefix=*) prefix=${argument#--prefix=} ;;
  esac
done

if [ -z "$prefix" ]; then
  echo "missing fixture installation prefix" >&2
  exit 1
fi

mkdir -p "$prefix/bin"
for binary in rustc cargo cargo-clippy clippy-driver rustfmt cargo-fmt; do
  if [ "$binary" = rustc ]; then
    printf '#!/bin/sh\nprintf "rustc %%s-dev (ohm installer fixture) (%%s)\\n" "${OHM_TEST_RUSTC_UPSTREAM_VERSION:?}" "${OHM_TEST_RUSTC_BRAND:?}"\n' \
      > "$prefix/bin/$binary"
  else
    printf '#!/bin/sh\nprintf "%s 1.97.1\\n"\n' "$binary" \
      > "$prefix/bin/$binary"
  fi
  chmod +x "$prefix/bin/$binary"
done
EOF
chmod +x "$fixture_directory/$archive_root/install.sh"
tar -cJf "$release_directory/$archive_name" -C "$fixture_directory" "$archive_root"
cp "$installer" "$release_directory/ohm-installer.sh"
printf '{"toolchain":"%s"}\n' "$version" > "$release_directory/$version.json"
printf '{"toolchain":"%s"}\n' "$version" \
  > "$release_directory/$version-aarch64-apple-darwin-provenance.json"
(
  cd "$release_directory"
  shasum -a 256 \
    "$archive_name" \
    ohm-installer.sh \
    "$version.json" \
    "$version-aarch64-apple-darwin-provenance.json" > SHA256SUMS
)

cat > "$mock_directory/uname" <<'EOF'
#!/bin/sh
set -eu

case "${1:-}" in
  -s) printf '%s\n' "${OHM_TEST_SYSTEM:-Darwin}" ;;
  -m) printf '%s\n' "${OHM_TEST_ARCHITECTURE:-arm64}" ;;
  *) echo "unsupported uname argument: ${1:-}" >&2; exit 1 ;;
esac
EOF

cat > "$mock_directory/rustup" <<'EOF'
#!/bin/sh
set -eu

printf '%s\n' "$*" >> "${OHM_TEST_RUSTUP_LOG:?}"
if [ "${1:-}" != "toolchain" ] || [ "${2:-}" != "link" ]; then
  echo "unexpected rustup invocation: $*" >&2
  exit 1
fi

mkdir -p "$RUSTUP_HOME/toolchains"
ln -s "$4" "$RUSTUP_HOME/toolchains/$3"
EOF

cat > "$mock_directory/gh" <<'EOF'
#!/bin/sh
set -eu

printf 'prompt=%s %s\n' "${GH_PROMPT_DISABLED:-}" "$*" >> "${OHM_TEST_GH_LOG:?}"
if [ "${OHM_TEST_GH_FAILURE:-0}" = 1 ]; then
  echo 'GitHub authentication required' >&2
  exit 1
fi

case "${1:-}:${2:-}" in
  release:view)
    printf '%s\n' "${OHM_TEST_VERSION:?}"
    ;;
  release:download)
    shift 2
    pattern=
    output=
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --pattern|-p) pattern=$2; shift 2 ;;
        --output|-O) output=$2; shift 2 ;;
        --repo|-R) shift 2 ;;
        *) shift ;;
      esac
    done
    if [ -z "$pattern" ] || [ -z "$output" ]; then
      echo 'missing release asset pattern or output' >&2
      exit 1
    fi
    cp "$OHM_TEST_RELEASE_DIRECTORY/$pattern" "$output"
    ;;
  run:download)
    shift 2
    run_id=
    artifact_name=
    artifact_pattern=
    output_directory=
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --name|-n) artifact_name=$2; shift 2 ;;
        --pattern|-p) artifact_pattern=$2; shift 2 ;;
        --dir|-D) output_directory=$2; shift 2 ;;
        --repo|-R) shift 2 ;;
        *) run_id=$1; shift ;;
      esac
    done
    if [ "$run_id" != 123456789 ] || [ -z "$output_directory" ]; then
      echo 'unexpected workflow artifact selection' >&2
      exit 1
    fi
    if [ "$artifact_name" != "$OHM_TEST_VERSION-aarch64-apple-darwin" ] && \
       [ "$artifact_pattern" != '*-aarch64-apple-darwin' ]; then
      echo 'unexpected workflow artifact selection' >&2
      exit 1
    fi
    mkdir -p "$output_directory"
    cp "$OHM_TEST_RELEASE_DIRECTORY/"* "$output_directory/"
    ;;
  *) echo "unexpected GitHub CLI invocation: $*" >&2; exit 1 ;;
esac
EOF
chmod +x "$mock_directory/uname" "$mock_directory/rustup" "$mock_directory/gh"

run_case() {
  case_name=$1
  expectation=$2
  shift 2

  case_directory="$temporary_directory/cases/$case_name"
  mkdir -p "$case_directory"
  rustup_log="$case_directory/rustup.log"
  github_log="$case_directory/github.log"
  output="$case_directory/output.log"
  : > "$rustup_log"
  : > "$github_log"

  if env \
    PATH="$mock_directory:$PATH" \
    CARGO_HOME="$case_directory/cargo-home" \
    RUSTUP_HOME="$case_directory/rustup-home" \
    XDG_DATA_HOME="$case_directory/data" \
    GH_PROMPT_DISABLED=1 \
    OHM_TEST_SYSTEM="${OHM_TEST_SYSTEM:-Darwin}" \
    OHM_TEST_ARCHITECTURE="${OHM_TEST_ARCHITECTURE:-arm64}" \
    OHM_TEST_GH_FAILURE="${OHM_TEST_GH_FAILURE:-0}" \
    OHM_TEST_VERSION="${OHM_TEST_VERSION:-$version}" \
    OHM_TEST_RUSTC_BRAND="${OHM_TEST_RUSTC_BRAND:-$version}" \
    OHM_TEST_RUSTC_UPSTREAM_VERSION="${OHM_TEST_RUSTC_UPSTREAM_VERSION:-1.97.1}" \
    OHM_TEST_RELEASE_DIRECTORY="$release_directory" \
    OHM_TEST_RUSTUP_LOG="$rustup_log" \
    OHM_TEST_GH_LOG="$github_log" \
    GH_TOKEN="${OHM_TEST_SECRET:-}" \
    sh "$installer" "$@" > "$output" 2>&1; then
    actual=success
  else
    actual=failure
  fi

  if [ "$actual" != "$expectation" ]; then
    echo "installer test '$case_name' expected $expectation, got $actual" >&2
    sed -n '1,100p' "$output" >&2
    exit 1
  fi
}

assert_contains() {
  if ! grep -F -- "$2" "$1" >/dev/null; then
    echo "expected '$2' in '$1'" >&2
    sed -n '1,100p' "$1" >&2
    exit 1
  fi
}

assert_not_contains() {
  if grep -F -- "$2" "$1" >/dev/null; then
    echo "unexpected '$2' in '$1'" >&2
    exit 1
  fi
}

assert_no_links() {
  if [ -s "$temporary_directory/cases/$1/rustup.log" ]; then
    echo "unexpected rustup changes for '$1'" >&2
    exit 1
  fi
}

OHM_TEST_SYSTEM=Linux
run_case unsupported-platform failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/unsupported-platform/toolchain"
unset OHM_TEST_SYSTEM
assert_no_links unsupported-platform

OHM_TEST_ARCHITECTURE=x86_64
run_case unsupported-architecture failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/unsupported-architecture/toolchain" \
  --no-alias
unset OHM_TEST_ARCHITECTURE
assert_no_links unsupported-architecture

run_case unsafe-version failure --version '../1.97.1-2' \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/unsafe-version/toolchain"
assert_no_links unsafe-version

run_case unsafe-prefix failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix /
assert_no_links unsafe-prefix

run_case unsafe-run-id failure --run '../123456789' --version "$version"
assert_no_links unsafe-run-id
if [ -s "$temporary_directory/cases/unsafe-run-id/github.log" ]; then
  echo 'unsafe workflow run ID unexpectedly accessed GitHub' >&2
  exit 1
fi

run_case missing-checksums failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --prefix "$temporary_directory/cases/missing-checksums/toolchain"
assert_no_links missing-checksums
if [ -s "$temporary_directory/cases/missing-checksums/github.log" ]; then
  echo 'incomplete offline installation unexpectedly accessed GitHub' >&2
  exit 1
fi

run_case missing-archive failure --version "$version" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/missing-archive/toolchain"
assert_no_links missing-archive

bad_checksums="$temporary_directory/bad-checksums"
printf '%064d  %s\n' 0 "$archive_name" > "$bad_checksums"
run_case invalid-checksum failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$bad_checksums" \
  --prefix "$temporary_directory/cases/invalid-checksum/toolchain"
assert_no_links invalid-checksum

duplicate_checksums="$temporary_directory/duplicate-checksums"
cp "$release_directory/SHA256SUMS" "$duplicate_checksums"
(
  cd "$release_directory"
  shasum -a 256 "$archive_name"
) >> "$duplicate_checksums"
run_case duplicate-checksum failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$duplicate_checksums" \
  --prefix "$temporary_directory/cases/duplicate-checksum/toolchain"
assert_no_links duplicate-checksum

ln -s /tmp "$fixture_directory/$archive_root/unsafe-link"
unsafe_archive="$temporary_directory/$archive_name"
tar -cJf "$unsafe_archive" -C "$fixture_directory" "$archive_root"
unsafe_checksums="$temporary_directory/unsafe-checksums"
(
  cd "$temporary_directory"
  shasum -a 256 "$archive_name" > "$unsafe_checksums"
)
run_case unsafe-archive failure --version "$version" \
  --archive "$unsafe_archive" \
  --checksums "$unsafe_checksums" \
  --prefix "$temporary_directory/cases/unsafe-archive/toolchain"
assert_no_links unsafe-archive

OHM_TEST_RUSTC_BRAND=ohm-1.97.1-1
run_case mismatched-rustc-version failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/mismatched-rustc-version/toolchain"
unset OHM_TEST_RUSTC_BRAND
assert_no_links mismatched-rustc-version

OHM_TEST_RUSTC_UPSTREAM_VERSION=1.96.0
run_case mismatched-rustc-upstream failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/mismatched-rustc-upstream/toolchain"
unset OHM_TEST_RUSTC_UPSTREAM_VERSION
assert_no_links mismatched-rustc-upstream

OHM_TEST_RUSTC_BRAND=$version
run_case matching-rustc-version success --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/matching-rustc-version/toolchain" \
  --no-alias
unset OHM_TEST_RUSTC_BRAND
assert_contains "$temporary_directory/cases/matching-rustc-version/rustup.log" \
  "toolchain link $version "

run_case local-no-alias success --version 1.97.1-2 \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/local-no-alias/toolchain" \
  --no-alias
assert_contains "$temporary_directory/cases/local-no-alias/rustup.log" \
  "toolchain link $version "
assert_not_contains "$temporary_directory/cases/local-no-alias/rustup.log" \
  'toolchain link ohm '
if [ -s "$temporary_directory/cases/local-no-alias/github.log" ]; then
  echo 'offline installer unexpectedly accessed GitHub' >&2
  exit 1
fi

run_case local-no-alias success --version 1.97.1-2 \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/local-no-alias/toolchain" \
  --no-alias
assert_no_links local-no-alias

incomplete_prefix="$temporary_directory/cases/incomplete-prefix/toolchain"
mkdir -p "$incomplete_prefix"
run_case incomplete-prefix failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$incomplete_prefix"
assert_no_links incomplete-prefix

existing_alias_directory="$temporary_directory/cases/replace-alias/rustup-home/toolchains"
existing_alias_target="$temporary_directory/cases/replace-alias/previous-toolchain"
mkdir -p "$existing_alias_directory" "$existing_alias_target"
ln -s "$existing_alias_target" "$existing_alias_directory/ohm"
run_case replace-alias success --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/replace-alias/toolchain"
assert_contains "$temporary_directory/cases/replace-alias/rustup.log" \
  'toolchain link ohm '
if [ "$(readlink "$existing_alias_directory/ohm")" != \
     "$temporary_directory/cases/replace-alias/toolchain" ]; then
  echo 'existing custom rustup alias was not updated to the new Ohm toolchain' >&2
  exit 1
fi

managed_alias_directory="$temporary_directory/cases/managed-alias/rustup-home/toolchains/ohm"
mkdir -p "$managed_alias_directory"
run_case managed-alias failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/managed-alias/toolchain"
if [ ! -d "$managed_alias_directory" ] || [ -L "$managed_alias_directory" ]; then
  echo 'installer replaced a managed rustup toolchain' >&2
  exit 1
fi

run_case workflow-artifact success --run 123456789 --version 1.97.1-2
assert_contains "$temporary_directory/cases/workflow-artifact/rustup.log" \
  "toolchain link $version "
assert_contains "$temporary_directory/cases/workflow-artifact/rustup.log" \
  'toolchain link ohm '
assert_contains "$temporary_directory/cases/workflow-artifact/github.log" \
  'prompt=1 run download 123456789 '
assert_contains "$temporary_directory/cases/workflow-artifact/github.log" \
  "$version-aarch64-apple-darwin"
assert_not_contains "$temporary_directory/cases/workflow-artifact/github.log" \
  'release '

run_case workflow-artifact-inferred-version success --run 123456789 --no-alias
assert_contains "$temporary_directory/cases/workflow-artifact-inferred-version/github.log" \
  '--pattern *-aarch64-apple-darwin'
assert_contains "$temporary_directory/cases/workflow-artifact-inferred-version/rustup.log" \
  "toolchain link $version "

run_case workflow-artifact-no-alias success \
  --run 123456789 --version "$version" --no-alias
assert_contains "$temporary_directory/cases/workflow-artifact-no-alias/github.log" \
  'prompt=1 run download 123456789 '
assert_not_contains "$temporary_directory/cases/workflow-artifact-no-alias/rustup.log" \
  'toolchain link ohm '

OHM_TEST_GH_FAILURE=1
OHM_TEST_SECRET='ohm-private-auth-secret-do-not-print'
run_case missing-authentication failure --run 123456789 --version "$version"
unset OHM_TEST_GH_FAILURE
assert_no_links missing-authentication
assert_not_contains "$temporary_directory/cases/missing-authentication/output.log" \
  "$OHM_TEST_SECRET"
assert_not_contains "$temporary_directory/cases/missing-authentication/github.log" \
  "$OHM_TEST_SECRET"
unset OHM_TEST_SECRET

echo 'Ohm installer tests passed'
