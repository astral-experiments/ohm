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
linux_archive_name="$version-x86_64-unknown-linux-gnu.tar.gz"
linux_archive_root="rust-1.97.1-dev-x86_64-unknown-linux-gnu"
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

# The distribution installer splits its script path and evaluates --prefix.
case "$0:$prefix" in
  *[[:space:]]*|*'$('*)
    echo 'unsafe characters in the distribution installer arguments' >&2
    exit 1
    ;;
esac

mkdir -p "$prefix/bin"
for binary in rustc rustdoc cargo cargo-clippy clippy-driver rustfmt cargo-fmt; do
  if [ "$binary" = rustdoc ] && [ "${OHM_TEST_RUSTDOC:-present}" = missing ]; then
    continue
  fi

  if [ "$binary" = rustc ]; then
    printf '#!/bin/sh\nprintf "rustc %%s-dev (ohm installer fixture) (%%s)\\n" "${OHM_TEST_RUSTC_UPSTREAM_VERSION:?}" "${OHM_TEST_RUSTC_BRAND:?}"\n' \
      > "$prefix/bin/$binary"
  elif [ "$binary" = rustdoc ] && [ "${OHM_TEST_RUSTDOC:-present}" = broken ]; then
    printf '#!/bin/sh\nexit 1\n' > "$prefix/bin/$binary"
  else
    printf '#!/bin/sh\nprintf "%s 1.97.1\\n"\n' "$binary" \
      > "$prefix/bin/$binary"
  fi
  chmod +x "$prefix/bin/$binary"
done
if [ "${OHM_TEST_WILD:-missing}" != missing ]; then
  wild_directory=$prefix/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld
  mkdir -p "$wild_directory"
  printf '#!/bin/sh\nprintf "Wild %s (compatible with GNU linkers)\\n"\n' "$OHM_TEST_WILD" > "$wild_directory/ld.bfd"
  chmod +x "$wild_directory/ld.bfd"
fi
EOF
chmod +x "$fixture_directory/$archive_root/install.sh"
tar -czf "$release_directory/$archive_name" -C "$fixture_directory" "$archive_root"
archive_checksum="$(shasum -a 256 "$release_directory/$archive_name" | awk '{ print $1 }')"
mkdir -p "$fixture_directory/$linux_archive_root"
cp "$fixture_directory/$archive_root/install.sh" "$fixture_directory/$linux_archive_root/install.sh"
tar -czf "$release_directory/$linux_archive_name" -C "$fixture_directory" "$linux_archive_root"
linux_archive_checksum="$(shasum -a 256 "$release_directory/$linux_archive_name" | awk '{ print $1 }')"
source_installer=$installer
installer="$temporary_directory/release-installer.sh"
sed \
  -e "s/^embedded_version=$/embedded_version=$version/" \
  -e "s/^embedded_archive_sha256_aarch64_apple_darwin=$/embedded_archive_sha256_aarch64_apple_darwin=$archive_checksum/" \
  -e "s/^embedded_archive_sha256_x86_64_unknown_linux_gnu=$/embedded_archive_sha256_x86_64_unknown_linux_gnu=$linux_archive_checksum/" \
  "$source_installer" > "$installer"

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

cat > "$mock_directory/ldd" <<'EOF'
#!/bin/sh
set -eu

case "${OHM_TEST_LIBC:-glibc}" in
  glibc) printf '%s\n' 'ldd (GNU libc) 2.39' ;;
  musl) printf '%s\n' 'musl libc (x86_64)' ;;
  *) echo "unsupported libc fixture: $OHM_TEST_LIBC" >&2; exit 1 ;;
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

if [ "$3" = ohm ] && [ "${OHM_TEST_RUSTUP_ALIAS_FAILURE:-0}" = 1 ]; then
  echo 'mock rustup alias registration failed' >&2
  exit 1
fi

mkdir -p "$RUSTUP_HOME/toolchains"
if [ -n "${OHM_TEST_RUSTUP_RACER:-}" ] && [ "$3" = "$OHM_TEST_VERSION" ]; then
  ln -s "$OHM_TEST_RUSTUP_RACER/other" "$OHM_TEST_RUSTUP_RACER/rustup-home/toolchains/$3"
fi
ln -sfn "$4" "$RUSTUP_HOME/toolchains/$3"
EOF

cat > "$mock_directory/curl" <<'EOF'
#!/bin/sh
set -eu

printf '%s\n' "$*" >> "${OHM_TEST_CURL_LOG:?}"
output=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --fail|--silent|--progress-bar|--show-error|--location|--tlsv1.2|-fsSL|--retry-all-errors)
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

case "$OHM_TEST_SYSTEM" in
  Linux) target=x86_64-unknown-linux-gnu ;;
  *) target=aarch64-apple-darwin ;;
esac
expected_archive="$OHM_TEST_VERSION-$target.tar.gz"
expected_url="https://labs.astral.sh/ohm/releases/$OHM_TEST_VERSION/$expected_archive"
[ "$url" = "$expected_url" ] || { echo "unexpected public release URL: $url" >&2; exit 1; }
[ "${OHM_TEST_CURL_FAILURE:-0}" != 1 ] || { echo 'public archive download failed' >&2; exit 22; }
cp "$OHM_TEST_RELEASE_DIRECTORY/$expected_archive" "$output"
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

chmod +x "$mock_directory/uname" "$mock_directory/sysctl" "$mock_directory/ldd" \
  "$mock_directory/rustup" \
  "$mock_directory/curl" "$mock_directory/mkdir"

run_case() {
  case_name=$1
  expectation=$2
  shift 2

  case_directory="$temporary_directory/cases/$case_name"
  mkdir -p "$case_directory"
  rustup_log="$case_directory/rustup.log"
  curl_log="$case_directory/curl.log"
  output="$case_directory/output.log"
  : > "$rustup_log"
  : > "$curl_log"

  if env \
    PATH="$mock_directory:$PATH" \
    CARGO_HOME="$case_directory/cargo-home" \
    RUSTUP_HOME="$case_directory/rustup-home" \
    XDG_DATA_HOME="$case_directory/data" \
    OHM_INSTALL_DIR="${OHM_TEST_INSTALL_DIR:-$case_directory/toolchain}" \
    OHM_DOWNLOAD_URL="${OHM_TEST_DOWNLOAD_URL-file://$release_directory}" \
    OHM_TEST_SYSTEM="${OHM_TEST_SYSTEM:-Darwin}" \
    OHM_TEST_ARCHITECTURE="${OHM_TEST_ARCHITECTURE:-arm64}" \
    OHM_TEST_APPLE_SILICON="${OHM_TEST_APPLE_SILICON:-0}" \
    OHM_TEST_LIBC="${OHM_TEST_LIBC:-glibc}" \
    OHM_TEST_CURL_FAILURE="${OHM_TEST_CURL_FAILURE:-}" \
    OHM_TEST_VERSION="${OHM_TEST_VERSION:-$version}" \
    OHM_TEST_RUSTC_BRAND="${OHM_TEST_RUSTC_BRAND:-$version}" \
    OHM_TEST_RUSTC_UPSTREAM_VERSION="${OHM_TEST_RUSTC_UPSTREAM_VERSION:-1.97.1}" \
    OHM_TEST_RUSTDOC="${OHM_TEST_RUSTDOC:-present}" \
    OHM_TEST_WILD="${OHM_TEST_WILD:-missing}" \
    OHM_TEST_RUSTUP_ALIAS_FAILURE="${OHM_TEST_RUSTUP_ALIAS_FAILURE:-0}" \
    OHM_TEST_ACTIVATION_RACE="${OHM_TEST_ACTIVATION_RACE:-0}" \
    OHM_TEST_ACTIVATION_DESTINATION="${OHM_TEST_ACTIVATION_DESTINATION:-}" \
    OHM_TEST_RELEASE_DIRECTORY="$release_directory" \
    OHM_TEST_RUSTUP_LOG="$rustup_log" \
    OHM_TEST_CURL_LOG="$curl_log" \
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

assert_lines_in_order() {
  file=$1
  shift
  previous_line=0

  for expected_line in "$@"; do
    line_number=$(awk -v expected="$expected_line" -v previous="$previous_line" '
      NR > previous && $0 == expected { print NR; exit }
    ' "$file")
    if [ -z "$line_number" ]; then
      echo "expected installer progress messages in order in '$file'" >&2
      sed -n '1,100p' "$file" >&2
      exit 1
    fi
    previous_line=$line_number
  done
}

assert_no_links() {
  if [ -s "$temporary_directory/cases/$1/rustup.log" ]; then
    echo "unexpected rustup changes for '$1'" >&2
    exit 1
  fi
}

mkdir -p "$temporary_directory/back\\slash"
TMPDIR="$temporary_directory/back\\slash" run_case escaped-tempdir success

run_case help success --help
assert_contains "$temporary_directory/cases/help/output.log" 'Usage: install.sh'
assert_no_links help

for unsupported_option in --version --archive --checksums --prefix --no-alias --run; do
  run_case unsupported-option failure "$unsupported_option"
  assert_no_links unsupported-option
done

truncated_installer="$temporary_directory/truncated-installer.sh"
awk '
  /^main "\$@"/ { found = 1; exit }
  { print }
  END { if (!found) exit 1 }
' "$installer" > "$truncated_installer"
OHM_TEST_INSTALLER=$truncated_installer
run_case truncated-installer failure
unset OHM_TEST_INSTALLER
assert_no_links truncated-installer
if [ -e "$temporary_directory/cases/truncated-installer/toolchain" ]; then
  echo 'truncated installer unexpectedly installed a toolchain' >&2
  exit 1
fi

saved_path=$PATH
mv "$mock_directory/rustup" "$mock_directory/rustup-hidden"
PATH=/usr/bin:/bin
run_case missing-rustup failure
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

OHM_TEST_SYSTEM=FreeBSD
run_case unsupported-platform failure
unset OHM_TEST_SYSTEM
assert_no_links unsupported-platform

OHM_TEST_SYSTEM=Linux
OHM_TEST_ARCHITECTURE=aarch64
run_case unsupported-linux-architecture failure
unset OHM_TEST_SYSTEM OHM_TEST_ARCHITECTURE
assert_no_links unsupported-linux-architecture

OHM_TEST_SYSTEM=Linux
OHM_TEST_ARCHITECTURE=x86_64
OHM_TEST_LIBC=musl
run_case unsupported-linux-musl failure
unset OHM_TEST_SYSTEM OHM_TEST_ARCHITECTURE OHM_TEST_LIBC
assert_no_links unsupported-linux-musl
assert_not_contains "$temporary_directory/cases/unsupported-linux-musl/curl.log" 'https://'

OHM_TEST_ARCHITECTURE=x86_64
run_case unsupported-architecture failure
unset OHM_TEST_ARCHITECTURE
assert_no_links unsupported-architecture

OHM_TEST_ARCHITECTURE=x86_64
OHM_TEST_APPLE_SILICON=1
run_case rosetta-apple-silicon success
unset OHM_TEST_ARCHITECTURE OHM_TEST_APPLE_SILICON
assert_contains "$temporary_directory/cases/rosetta-apple-silicon/rustup.log" \
  "toolchain link $version "

OHM_TEST_SYSTEM=Linux
OHM_TEST_ARCHITECTURE=x86_64
run_case linux-x86_64 success
unset OHM_TEST_SYSTEM OHM_TEST_ARCHITECTURE
assert_contains "$temporary_directory/cases/linux-x86_64/rustup.log" \
  "toolchain link $version "

OHM_TEST_INSTALLER=$source_installer
run_case unversioned-installer failure
unset OHM_TEST_INSTALLER
assert_no_links unversioned-installer

OHM_TEST_DOWNLOAD_URL=
run_case embedded-public-latest success
unset OHM_TEST_DOWNLOAD_URL
assert_not_contains "$temporary_directory/cases/embedded-public-latest/curl.log" \
  'api.github.com'
assert_not_contains "$temporary_directory/cases/embedded-public-latest/curl.log" \
  'releases.astral.sh'
assert_not_contains "$temporary_directory/cases/embedded-public-latest/curl.log" \
  'SHA256SUMS'
assert_contains "$temporary_directory/cases/embedded-public-latest/curl.log" \
  "https://labs.astral.sh/ohm/releases/$version/$archive_name"
assert_contains "$temporary_directory/cases/embedded-public-latest/curl.log" '--retry '
assert_contains "$temporary_directory/cases/embedded-public-latest/curl.log" '--silent'
assert_not_contains "$temporary_directory/cases/embedded-public-latest/curl.log" '--progress-bar'
assert_lines_in_order "$temporary_directory/cases/embedded-public-latest/output.log" \
  "ohm: downloading $version for aarch64-apple-darwin" \
  'ohm: verifying archive checksum' \
  'ohm: inspecting archive contents' \
  'ohm: extracting toolchain' \
  'ohm: installing toolchain components' \
  'ohm: registering toolchains with rustup'
assert_contains "$temporary_directory/cases/embedded-public-latest/rustup.log" \
  "toolchain link $version "
assert_contains "$temporary_directory/cases/embedded-public-latest/rustup.log" \
  'toolchain link ohm '

OHM_TEST_SYSTEM=Linux
OHM_TEST_ARCHITECTURE=x86_64
OHM_TEST_DOWNLOAD_URL=
run_case linux-public-archive success
unset OHM_TEST_SYSTEM OHM_TEST_ARCHITECTURE OHM_TEST_DOWNLOAD_URL
assert_contains "$temporary_directory/cases/linux-public-archive/curl.log" \
  "https://labs.astral.sh/ohm/releases/$version/$linux_archive_name"

bad_embedded_installer="$temporary_directory/bad-embedded-installer.sh"
sed "s/^embedded_archive_sha256_aarch64_apple_darwin=.*/embedded_archive_sha256_aarch64_apple_darwin=$(printf '%064d' 0)/" \
  "$installer" > "$bad_embedded_installer"
OHM_TEST_INSTALLER=$bad_embedded_installer
run_case mismatched-embedded-checksum failure
unset OHM_TEST_INSTALLER
assert_no_links mismatched-embedded-checksum

invalid_embedded_installer="$temporary_directory/invalid-embedded-installer.sh"
sed 's/^embedded_archive_sha256_aarch64_apple_darwin=.*/embedded_archive_sha256_aarch64_apple_darwin=not-a-checksum/' \
  "$installer" > "$invalid_embedded_installer"
OHM_TEST_INSTALLER=$invalid_embedded_installer
run_case invalid-embedded-checksum failure
unset OHM_TEST_INSTALLER
assert_no_links invalid-embedded-checksum
assert_not_contains "$temporary_directory/cases/invalid-embedded-checksum/curl.log" 'https://'

wrong_platform_installer="$temporary_directory/wrong-platform-installer.sh"
sed "s/^embedded_archive_sha256_x86_64_unknown_linux_gnu=.*/embedded_archive_sha256_x86_64_unknown_linux_gnu=$archive_checksum/" \
  "$installer" > "$wrong_platform_installer"
OHM_TEST_SYSTEM=Linux
OHM_TEST_ARCHITECTURE=x86_64
OHM_TEST_INSTALLER=$wrong_platform_installer
run_case wrong-platform-checksum failure
unset OHM_TEST_SYSTEM OHM_TEST_ARCHITECTURE OHM_TEST_INSTALLER
assert_no_links wrong-platform-checksum

OHM_TEST_DOWNLOAD_URL=
OHM_TEST_CURL_FAILURE=1
run_case public-archive-failure failure
unset OHM_TEST_CURL_FAILURE
unset OHM_TEST_DOWNLOAD_URL
assert_no_links public-archive-failure

unsafe_version_installer="$temporary_directory/unsafe-version-installer.sh"
sed 's|^embedded_version=.*|embedded_version=../1.97.1-2|' \
  "$installer" > "$unsafe_version_installer"
OHM_TEST_INSTALLER=$unsafe_version_installer
run_case unsafe-version failure
unset OHM_TEST_INSTALLER
assert_no_links unsafe-version

multiline_installer="$temporary_directory/multiline-installer.sh"
awk -v release_version="$version" '
  /^embedded_version=/ {
    print "embedded_version='\''" release_version
    print "invalid'\''"
    next
  }
  { print }
' "$installer" > "$multiline_installer"
OHM_TEST_INSTALLER=$multiline_installer
run_case multiline-version failure
unset OHM_TEST_INSTALLER
assert_no_links multiline-version
assert_not_contains "$temporary_directory/cases/multiline-version/curl.log" 'https://'

OHM_TEST_INSTALL_DIR=/
run_case unsafe-prefix failure
unset OHM_TEST_INSTALL_DIR
assert_no_links unsafe-prefix

OHM_TEST_INSTALL_DIR="$temporary_directory/cases/multiline-dot-component/"$'line\n..'"/toolchain"
run_case multiline-dot-component success
unset OHM_TEST_INSTALL_DIR

mkdir -p "$temporary_directory/temp with spaces"
TMPDIR="$temporary_directory/temp with spaces" \
  OHM_TEST_INSTALL_DIR="$temporary_directory/cases/space in parent/\$(false)/toolchain" \
  run_case literal-staging-path success

for component in . ..; do
  OHM_TEST_INSTALL_DIR="$temporary_directory/cases/relative-component/$component"
  run_case relative-component failure
  assert_contains "$output" 'OHM_INSTALL_DIR must not contain relative path components'
done
unset OHM_TEST_INSTALL_DIR

mkdir "$temporary_directory/local release%"
cp "$release_directory/$archive_name" "$temporary_directory/local release%/$archive_name"
OHM_TEST_DOWNLOAD_URL="file://$temporary_directory/local%20release%25"
run_case encoded-file-url success
OHM_TEST_DOWNLOAD_URL="file://$temporary_directory/local%00%20release%25"
run_case encoded-nul-file-url failure
assert_no_links encoded-nul-file-url
unset OHM_TEST_DOWNLOAD_URL

for unsafe_url in http://example.invalid file://example.invalid/archive ftp://example.invalid; do
  OHM_TEST_DOWNLOAD_URL=$unsafe_url
  run_case unsafe-download-url failure
  assert_no_links unsafe-download-url
done
unset OHM_TEST_DOWNLOAD_URL

ln -s /tmp "$fixture_directory/$archive_root/unsafe-link"
unsafe_archive="$temporary_directory/$archive_name"
tar -czf "$unsafe_archive" -C "$fixture_directory" "$archive_root"
unsafe_checksum="$(shasum -a 256 "$unsafe_archive" | awk '{ print $1 }')"
unsafe_archive_installer="$temporary_directory/unsafe-archive-installer.sh"
sed "s/^embedded_archive_sha256_aarch64_apple_darwin=.*/embedded_archive_sha256_aarch64_apple_darwin=$unsafe_checksum/" \
  "$installer" > "$unsafe_archive_installer"
OHM_TEST_INSTALLER=$unsafe_archive_installer
OHM_TEST_DOWNLOAD_URL="file://$temporary_directory"
run_case unsafe-archive failure
unset OHM_TEST_INSTALLER OHM_TEST_DOWNLOAD_URL
assert_no_links unsafe-archive

OHM_TEST_RUSTC_BRAND=ohm-1.97.1-1
run_case mismatched-rustc-version failure
unset OHM_TEST_RUSTC_BRAND
assert_no_links mismatched-rustc-version

OHM_TEST_RUSTC_UPSTREAM_VERSION=1.96.0
run_case mismatched-rustc-upstream failure
unset OHM_TEST_RUSTC_UPSTREAM_VERSION
assert_no_links mismatched-rustc-upstream

OHM_TEST_RUSTDOC=missing
run_case missing-rustdoc failure
unset OHM_TEST_RUSTDOC
assert_contains "$temporary_directory/cases/missing-rustdoc/output.log" \
  'installed tool is missing or not executable: rustdoc'
assert_no_links missing-rustdoc

OHM_TEST_RUSTDOC=broken
run_case broken-rustdoc failure
unset OHM_TEST_RUSTDOC
assert_contains "$temporary_directory/cases/broken-rustdoc/output.log" \
  'installed tool did not start successfully: rustdoc'
assert_no_links broken-rustdoc

OHM_TEST_INSTALL_DIR="$temporary_directory/cases/trailing-slash-prefix/toolchain/"
run_case trailing-slash-prefix success
unset OHM_TEST_INSTALL_DIR
if [ ! -x "$temporary_directory/cases/trailing-slash-prefix/toolchain/bin/rustc" ]; then
  echo 'trailing-slash prefix did not receive the installed toolchain' >&2
  exit 1
fi

run_case local-install success
assert_contains "$temporary_directory/cases/local-install/output.log" \
  "ohm: copying $version for aarch64-apple-darwin"
if [ ! -x "$temporary_directory/cases/local-install/toolchain/bin/rustdoc" ]; then
  echo 'historical-version fixture did not install rustdoc' >&2
  exit 1
fi
assert_not_contains "$temporary_directory/cases/local-install/output.log" 'ohm: downloading'
assert_contains "$temporary_directory/cases/local-install/rustup.log" \
  "toolchain link $version "
assert_contains "$temporary_directory/cases/local-install/rustup.log" 'toolchain link ohm '
assert_not_contains "$temporary_directory/cases/local-install/curl.log" 'https://'

run_case local-install success
assert_no_links local-install

incomplete_prefix="$temporary_directory/cases/incomplete-prefix/toolchain"
mkdir -p "$incomplete_prefix"
run_case incomplete-prefix failure
assert_no_links incomplete-prefix

activation_race_prefix="$temporary_directory/cases/activation-race/toolchain"
OHM_TEST_ACTIVATION_RACE=1
OHM_TEST_ACTIVATION_DESTINATION=$activation_race_prefix
run_case activation-race failure
unset OHM_TEST_ACTIVATION_RACE OHM_TEST_ACTIVATION_DESTINATION
assert_no_links activation-race
if [ ! -f "$activation_race_prefix/race-marker" ] || \
   [ -e "$activation_race_prefix/bin/rustc" ]; then
  echo 'installer overwrote the competing activation destination' >&2
  exit 1
fi

race_directory="$temporary_directory/cases/immutable-link-race"
mkdir -p "$race_directory/other"
OHM_TEST_RUSTUP_RACER="$race_directory" run_case immutable-link-race failure
if [ ! "$race_directory/rustup-home/toolchains/$version" -ef "$race_directory/other" ]; then
  echo 'installer replaced the concurrently registered version' >&2
  exit 1
fi

existing_alias_directory="$temporary_directory/cases/replace-alias/rustup-home/toolchains"
# Command substitution strips trailing newlines from a path printed by pwd.
existing_alias_target="$temporary_directory/cases/replace-alias/toolchain"$'\n'
mkdir -p "$existing_alias_directory" "$existing_alias_target"
ln -s "$existing_alias_target" "$existing_alias_directory/ohm"
run_case replace-alias success
assert_contains "$temporary_directory/cases/replace-alias/rustup.log" \
  'toolchain link ohm '
if [ ! "$existing_alias_directory/ohm" -ef "$temporary_directory/cases/replace-alias/toolchain" ]; then
  echo 'existing custom rustup alias was not updated to the new Ohm toolchain' >&2
  exit 1
fi

conflicting_version_directory="$temporary_directory/cases/conflicting-version/rustup-home/toolchains"
conflicting_version_target="$temporary_directory/cases/conflicting-version/toolchain"$'\n'
mkdir -p "$conflicting_version_directory" "$conflicting_version_target"
ln -s "$conflicting_version_target" "$conflicting_version_directory/$version"
run_case conflicting-version failure
assert_no_links conflicting-version

failing_alias_directory="$temporary_directory/cases/failed-alias/rustup-home/toolchains"
failing_alias_target="$temporary_directory/cases/failed-alias/previous-toolchain"
mkdir -p "$failing_alias_directory" "$failing_alias_target"
ln -s "$failing_alias_target" "$failing_alias_directory/ohm"
OHM_TEST_RUSTUP_ALIAS_FAILURE=1
run_case failed-alias failure
unset OHM_TEST_RUSTUP_ALIAS_FAILURE
if [ ! -L "$failing_alias_directory/ohm" ] || \
   [ "$(readlink "$failing_alias_directory/ohm")" != "$failing_alias_target" ]; then
  echo 'failed rustup registration replaced the existing Ohm alias' >&2
  exit 1
fi

managed_alias_directory="$temporary_directory/cases/managed-alias/rustup-home/toolchains/ohm"
mkdir -p "$managed_alias_directory"
run_case managed-alias failure
if [ ! -d "$managed_alias_directory" ] || [ -L "$managed_alias_directory" ]; then
  echo 'installer replaced a managed rustup toolchain' >&2
  exit 1
fi

wild_installer="$temporary_directory/wild-installer.sh"
sed 's/^embedded_wild_version=$/embedded_wild_version=0.10.0/' "$installer" > "$wild_installer"
OHM_TEST_INSTALLER="$wild_installer"
OHM_TEST_SYSTEM=Linux
OHM_TEST_ARCHITECTURE=x86_64
run_case missing-wild failure
assert_contains "$output" 'bundled Wild linker is missing'
OHM_TEST_WILD=0.9.0
run_case wrong-wild-version failure
assert_contains "$output" 'bundled Wild linker has an unexpected version'
OHM_TEST_WILD=0.10.0
run_case bundled-wild success
unset OHM_TEST_INSTALLER OHM_TEST_SYSTEM OHM_TEST_ARCHITECTURE OHM_TEST_WILD

echo 'Ohm installer tests passed'
