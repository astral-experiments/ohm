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
archive_name="$version-aarch64-apple-darwin.tar.gz"
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
tar -czf "$release_directory/$archive_name" -C "$fixture_directory" "$archive_root"
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

cat > "$mock_directory/sysctl" <<'EOF'
#!/bin/sh
set -eu

if [ "${1:-}" != -n ] || [ "${2:-}" != hw.optional.arm64 ]; then
  echo "unexpected sysctl invocation: $*" >&2
  exit 1
fi

printf '%s\n' "${OHM_TEST_APPLE_SILICON:-0}"
EOF

cat > "$mock_directory/rustup" <<'EOF'
#!/bin/sh
set -eu

printf '%s\n' "$*" >> "${OHM_TEST_RUSTUP_LOG:?}"
if [ "${1:-}" != "toolchain" ] || [ "${2:-}" != "link" ]; then
  echo "unexpected rustup invocation: $*" >&2
  exit 1
fi

if [ "$3" = ohm ] && [ "${OHM_TEST_RUSTUP_ALIAS_FAILURE:-0}" = 1 ] && \
   [ ! -e "$OHM_TEST_RUSTUP_LOG.alias-failed" ]; then
  : > "$OHM_TEST_RUSTUP_LOG.alias-failed"
  echo 'mock rustup alias registration failed' >&2
  exit 1
fi

mkdir -p "$RUSTUP_HOME/toolchains"
ln -s "$4" "$RUSTUP_HOME/toolchains/$3"
EOF

cat > "$mock_directory/curl" <<'EOF'
#!/bin/sh
set -eu

printf '%s\n' "$*" >> "${OHM_TEST_CURL_LOG:?}"
output=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --fail|--silent|--show-error|--location|--tlsv1.2|-fsSL|--retry-all-errors)
      shift
      ;;
    --proto) shift 2 ;;
    --retry|--retry-delay|--connect-timeout|--max-time) shift 2 ;;
    --output|-o) output=$2; shift 2 ;;
    https://*) url=$1; shift ;;
    *) echo "unexpected curl argument: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$output" ] || [ -z "$url" ]; then
  echo 'missing curl output or URL' >&2
  exit 1
fi

case "$url" in
  https://api.github.com/repos/astral-sh/ohm/releases/latest)
    if [ "${OHM_TEST_CURL_FAILURE:-}" = latest ]; then
      echo 'GitHub latest release request failed' >&2
      exit 22
    fi
    printf '{"tag_name":"%s"}\n' "$OHM_TEST_VERSION" > "$output"
    ;;
  "https://github.com/astral-sh/ohm/releases/download/$OHM_TEST_VERSION/$OHM_TEST_VERSION-aarch64-apple-darwin.tar.gz")
    if [ "${OHM_TEST_CURL_FAILURE:-}" = archive ]; then
      echo 'public archive download failed' >&2
      exit 22
    fi
    cp "$OHM_TEST_RELEASE_DIRECTORY/$OHM_TEST_VERSION-aarch64-apple-darwin.tar.gz" \
      "$output"
    ;;
  "https://github.com/astral-sh/ohm/releases/download/$OHM_TEST_VERSION/SHA256SUMS")
    if [ "${OHM_TEST_CURL_FAILURE:-}" = checksums ]; then
      echo 'public checksum download failed' >&2
      exit 22
    fi
    if [ "${OHM_TEST_PUBLIC_BAD_CHECKSUM:-0}" = 1 ]; then
      printf '%064d  %s-aarch64-apple-darwin.tar.gz\n' 0 "$OHM_TEST_VERSION" \
        > "$output"
    else
      cp "$OHM_TEST_RELEASE_DIRECTORY/SHA256SUMS" "$output"
    fi
    ;;
  *) echo "unexpected public release URL: $url" >&2; exit 1 ;;
esac
EOF

cat > "$mock_directory/mkdir" <<'EOF'
#!/bin/sh
set -eu

if [ "${OHM_TEST_ACTIVATION_RACE:-0}" = 1 ]; then
  destination=
  for argument in "$@"; do
    destination=$argument
  done

  if [ "$destination" = "${OHM_TEST_ACTIVATION_DESTINATION:-}" ]; then
    /bin/mkdir -p "$destination"
    printf '%s\n' 'preserve the competing destination' > "$destination/race-marker"
  fi
fi

exec /bin/mkdir "$@"
EOF

cat > "$mock_directory/mv" <<'EOF'
#!/bin/sh
set -eu

if [ "${OHM_TEST_ACTIVATION_RACE:-0}" = 1 ]; then
  destination=
  for argument in "$@"; do
    destination=$argument
  done

  if [ "$destination" = "${OHM_TEST_ACTIVATION_DESTINATION:-}" ]; then
    mkdir -p "$destination"
    printf '%s\n' 'preserve the competing destination' > "$destination/race-marker"
  fi
fi

exec /bin/mv "$@"
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
chmod +x "$mock_directory/uname" "$mock_directory/sysctl" "$mock_directory/rustup" \
  "$mock_directory/curl" "$mock_directory/mkdir" "$mock_directory/mv" \
  "$mock_directory/gh"

run_case() {
  case_name=$1
  expectation=$2
  shift 2

  case_directory="$temporary_directory/cases/$case_name"
  mkdir -p "$case_directory"
  rustup_log="$case_directory/rustup.log"
  github_log="$case_directory/github.log"
  curl_log="$case_directory/curl.log"
  output="$case_directory/output.log"
  : > "$rustup_log"
  : > "$github_log"
  : > "$curl_log"

  if env \
    PATH="$mock_directory:$PATH" \
    CARGO_HOME="$case_directory/cargo-home" \
    RUSTUP_HOME="$case_directory/rustup-home" \
    XDG_DATA_HOME="$case_directory/data" \
    GH_PROMPT_DISABLED=1 \
    OHM_TEST_SYSTEM="${OHM_TEST_SYSTEM:-Darwin}" \
    OHM_TEST_ARCHITECTURE="${OHM_TEST_ARCHITECTURE:-arm64}" \
    OHM_TEST_APPLE_SILICON="${OHM_TEST_APPLE_SILICON:-0}" \
    OHM_TEST_GH_FAILURE="${OHM_TEST_GH_FAILURE:-0}" \
    OHM_TEST_CURL_FAILURE="${OHM_TEST_CURL_FAILURE:-}" \
    OHM_TEST_PUBLIC_BAD_CHECKSUM="${OHM_TEST_PUBLIC_BAD_CHECKSUM:-0}" \
    OHM_TEST_VERSION="${OHM_TEST_VERSION:-$version}" \
    OHM_TEST_RUSTC_BRAND="${OHM_TEST_RUSTC_BRAND:-$version}" \
    OHM_TEST_RUSTC_UPSTREAM_VERSION="${OHM_TEST_RUSTC_UPSTREAM_VERSION:-1.97.1}" \
    OHM_TEST_RUSTUP_ALIAS_FAILURE="${OHM_TEST_RUSTUP_ALIAS_FAILURE:-0}" \
    OHM_TEST_ACTIVATION_RACE="${OHM_TEST_ACTIVATION_RACE:-0}" \
    OHM_TEST_ACTIVATION_DESTINATION="${OHM_TEST_ACTIVATION_DESTINATION:-}" \
    OHM_TEST_RELEASE_DIRECTORY="$release_directory" \
    OHM_TEST_RUSTUP_LOG="$rustup_log" \
    OHM_TEST_GH_LOG="$github_log" \
    OHM_TEST_CURL_LOG="$curl_log" \
    GH_TOKEN="${OHM_TEST_SECRET:-}" \
    sh "${OHM_TEST_INSTALLER:-$installer}" "$@" > "$output" 2>&1; then
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

run_case help success --help
assert_contains "$temporary_directory/cases/help/output.log" 'Usage: install.sh'
assert_no_links help

truncated_installer="$temporary_directory/truncated-installer.sh"
awk '
  /^main "\$@"/ { found = 1; exit }
  { print }
  END { if (!found) exit 1 }
' "$installer" > "$truncated_installer"
OHM_TEST_INSTALLER=$truncated_installer
run_case truncated-installer failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/truncated-installer/toolchain"
unset OHM_TEST_INSTALLER
assert_no_links truncated-installer
if [ -e "$temporary_directory/cases/truncated-installer/toolchain" ]; then
  echo 'truncated installer unexpectedly installed a toolchain' >&2
  exit 1
fi

saved_path=$PATH
mv "$mock_directory/rustup" "$mock_directory/rustup-hidden"
PATH=/usr/bin:/bin
run_case missing-rustup failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/missing-rustup/toolchain"
PATH=$saved_path
mv "$mock_directory/rustup-hidden" "$mock_directory/rustup"
assert_no_links missing-rustup
if [ -e "$temporary_directory/cases/missing-rustup/toolchain" ]; then
  echo 'installer wrote a toolchain before checking for rustup' >&2
  exit 1
fi
if [ -s "$temporary_directory/cases/missing-rustup/curl.log" ]; then
  echo 'installer downloaded an archive before checking for rustup' >&2
  exit 1
fi

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

OHM_TEST_ARCHITECTURE=x86_64
OHM_TEST_APPLE_SILICON=1
run_case rosetta-apple-silicon success --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/rosetta-apple-silicon/toolchain" \
  --no-alias
unset OHM_TEST_ARCHITECTURE OHM_TEST_APPLE_SILICON
assert_contains "$temporary_directory/cases/rosetta-apple-silicon/rustup.log" \
  "toolchain link $version "

run_case public-latest success
assert_contains "$temporary_directory/cases/public-latest/curl.log" \
  'https://api.github.com/repos/astral-sh/ohm/releases/latest'
assert_contains "$temporary_directory/cases/public-latest/curl.log" \
  "https://github.com/astral-sh/ohm/releases/download/$version/$archive_name"
assert_contains "$temporary_directory/cases/public-latest/curl.log" \
  "https://github.com/astral-sh/ohm/releases/download/$version/SHA256SUMS"
assert_contains "$temporary_directory/cases/public-latest/curl.log" '--retry '
assert_contains "$temporary_directory/cases/public-latest/rustup.log" \
  "toolchain link $version "
assert_contains "$temporary_directory/cases/public-latest/rustup.log" \
  'toolchain link ohm '
if [ -s "$temporary_directory/cases/public-latest/github.log" ]; then
  echo 'public installation unexpectedly required GitHub CLI authentication' >&2
  exit 1
fi

run_case public-pinned success --version 1.97.1-2 --no-alias
assert_not_contains "$temporary_directory/cases/public-pinned/curl.log" \
  'api.github.com'
assert_contains "$temporary_directory/cases/public-pinned/curl.log" \
  "https://github.com/astral-sh/ohm/releases/download/$version/$archive_name"
assert_not_contains "$temporary_directory/cases/public-pinned/rustup.log" \
  'toolchain link ohm '
if [ -s "$temporary_directory/cases/public-pinned/github.log" ]; then
  echo 'version-pinned public installation unexpectedly used GitHub CLI' >&2
  exit 1
fi

archive_checksum="$(awk -v archive="$archive_name" '$2 == archive { print $1 }' \
  "$release_directory/SHA256SUMS")"
embedded_installer="$temporary_directory/embedded-installer.sh"
sed \
  -e "s/^embedded_version=$/embedded_version=$version/" \
  -e "s/^embedded_archive_sha256=$/embedded_archive_sha256=$archive_checksum/" \
  "$installer" > "$embedded_installer"
assert_contains "$embedded_installer" "embedded_version=$version"
assert_contains "$embedded_installer" "embedded_archive_sha256=$archive_checksum"

OHM_TEST_INSTALLER=$embedded_installer
run_case embedded-public-latest success
unset OHM_TEST_INSTALLER
assert_not_contains "$temporary_directory/cases/embedded-public-latest/curl.log" \
  'api.github.com'
assert_not_contains "$temporary_directory/cases/embedded-public-latest/curl.log" \
  'SHA256SUMS'
assert_contains "$temporary_directory/cases/embedded-public-latest/curl.log" \
  "https://github.com/astral-sh/ohm/releases/download/$version/$archive_name"
assert_contains "$temporary_directory/cases/embedded-public-latest/rustup.log" \
  "toolchain link $version "
if [ -s "$temporary_directory/cases/embedded-public-latest/github.log" ]; then
  echo 'embedded release installer unexpectedly used GitHub CLI' >&2
  exit 1
fi

OHM_TEST_INSTALLER=$embedded_installer
run_case mismatched-embedded-version failure --version ohm-1.97.1-1
unset OHM_TEST_INSTALLER
assert_no_links mismatched-embedded-version
if [ -s "$temporary_directory/cases/mismatched-embedded-version/curl.log" ]; then
  echo 'mismatched embedded installer version unexpectedly downloaded an archive' >&2
  exit 1
fi

bad_embedded_installer="$temporary_directory/bad-embedded-installer.sh"
sed "s/^embedded_archive_sha256=.*/embedded_archive_sha256=$(printf '%064d' 0)/" \
  "$embedded_installer" > "$bad_embedded_installer"
OHM_TEST_INSTALLER=$bad_embedded_installer
run_case mismatched-embedded-checksum failure
unset OHM_TEST_INSTALLER
assert_no_links mismatched-embedded-checksum

OHM_TEST_VERSION=../../unsafe
run_case unsafe-public-version failure
unset OHM_TEST_VERSION
assert_no_links unsafe-public-version

OHM_TEST_CURL_FAILURE=latest
run_case latest-release-failure failure
unset OHM_TEST_CURL_FAILURE
assert_no_links latest-release-failure

OHM_TEST_CURL_FAILURE=archive
run_case public-archive-failure failure --version "$version"
unset OHM_TEST_CURL_FAILURE
assert_no_links public-archive-failure

OHM_TEST_CURL_FAILURE=checksums
run_case public-checksums-failure failure --version "$version"
unset OHM_TEST_CURL_FAILURE
assert_no_links public-checksums-failure

OHM_TEST_PUBLIC_BAD_CHECKSUM=1
run_case public-checksum-mismatch failure --version "$version"
unset OHM_TEST_PUBLIC_BAD_CHECKSUM
assert_no_links public-checksum-mismatch

run_case unsafe-version failure --version '../1.97.1-2' \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/unsafe-version/toolchain"
assert_no_links unsafe-version

multiline_version="$(printf '%s\n%s' "$version" invalid)"
run_case multiline-version failure --version "$multiline_version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/multiline-version/toolchain"
assert_no_links multiline-version
assert_not_contains "$temporary_directory/cases/multiline-version/curl.log" 'https://'

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

multiline_run_id="$(printf '123456789\ninvalid')"
run_case multiline-run-id failure --run "$multiline_run_id" --version "$version"
assert_no_links multiline-run-id
if [ -s "$temporary_directory/cases/multiline-run-id/github.log" ]; then
  echo 'multiline workflow run ID unexpectedly accessed GitHub' >&2
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
tar -czf "$unsafe_archive" -C "$fixture_directory" "$archive_root"
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

run_case trailing-slash-prefix success --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/trailing-slash-prefix/toolchain/" \
  --no-alias
if [ ! -x "$temporary_directory/cases/trailing-slash-prefix/toolchain/bin/rustc" ]; then
  echo 'trailing-slash prefix did not receive the installed toolchain' >&2
  exit 1
fi

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

activation_race_prefix="$temporary_directory/cases/activation-race/toolchain"
OHM_TEST_ACTIVATION_RACE=1
OHM_TEST_ACTIVATION_DESTINATION=$activation_race_prefix
run_case activation-race failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$activation_race_prefix" \
  --no-alias
unset OHM_TEST_ACTIVATION_RACE OHM_TEST_ACTIVATION_DESTINATION
assert_no_links activation-race
if [ ! -f "$activation_race_prefix/race-marker" ] || \
   [ -e "$activation_race_prefix/bin/rustc" ]; then
  echo 'installer overwrote the competing activation destination' >&2
  exit 1
fi

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

failing_alias_directory="$temporary_directory/cases/failed-alias/rustup-home/toolchains"
failing_alias_target="$temporary_directory/cases/failed-alias/previous-toolchain"
mkdir -p "$failing_alias_directory" "$failing_alias_target"
ln -s "$failing_alias_target" "$failing_alias_directory/ohm"
OHM_TEST_RUSTUP_ALIAS_FAILURE=1
run_case failed-alias failure --version "$version" \
  --archive "$release_directory/$archive_name" \
  --checksums "$release_directory/SHA256SUMS" \
  --prefix "$temporary_directory/cases/failed-alias/toolchain"
unset OHM_TEST_RUSTUP_ALIAS_FAILURE
if [ ! -L "$failing_alias_directory/ohm" ] || \
   [ "$(readlink "$failing_alias_directory/ohm")" != "$failing_alias_target" ]; then
  echo 'failed rustup registration replaced the existing Ohm alias' >&2
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
