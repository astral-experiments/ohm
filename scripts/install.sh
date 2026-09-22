#!/bin/sh
set -eu

embedded_version=
embedded_wild_version=
embedded_archive_sha256_aarch64_apple_darwin=
embedded_archive_sha256_x86_64_unknown_linux_gnu=
installation_prefix=${OHM_INSTALL_DIR:-}
temporary_directory=
staging_directory=
activated_prefix=
alias_backup=
script_complete=false

fail() {
    printf 'ohm: %s\n' "$*" >&2
    exit 1
}

info() {
    printf 'ohm: %s\n' "$*" >&2
}

usage() {
    printf '%s\n' \
        'Usage: install.sh [--help]' \
        '' \
        'Install the embedded, checksum-pinned Ohm toolchain for this platform.' \
        'Set OHM_INSTALL_DIR to override its installation directory.'
}

cleanup() {
    exit_status=$?

    if [ -n "$alias_backup" ] && [ -L "$alias_backup" ]; then
        alias_path=${alias_backup%.ohm-backup.*}
        if [ ! -e "$alias_path" ] && [ ! -L "$alias_path" ]; then
            mv "$alias_backup" "$alias_path" ||
                printf 'ohm: could not restore the previous rustup alias\n' >&2
        fi
    fi

    if [ -n "$activated_prefix" ] && [ -d "$activated_prefix" ]; then
        if [ "$activated_prefix" = "$installation_prefix" ]; then
            rm -rf "$activated_prefix"
        else
            printf 'ohm: refusing to remove an unsafe installation prefix\n' >&2
        fi
    fi

    if [ -n "$staging_directory" ] && [ -d "$staging_directory" ]; then
        case "${staging_directory##*/}" in
            .ohm-install.????????) rm -rf "$staging_directory" ;;
            *) printf 'ohm: refusing to remove unsafe staging directory\n' >&2 ;;
        esac
    fi

    if [ -n "$temporary_directory" ] && [ -d "$temporary_directory" ]; then
        case "${temporary_directory##*/}" in
            ohm-installer.????????) rm -rf "$temporary_directory" ;;
            *) printf 'ohm: refusing to remove unsafe temporary directory\n' >&2 ;;
        esac
    fi

    if [ "$script_complete" != true ] && [ "$exit_status" -eq 0 ]; then
        printf 'ohm: installer ended before reaching its completion marker\n' >&2
        exit_status=1
    fi

    exit "$exit_status"
}

trap cleanup 0
trap 'exit 130' HUP INT TERM

normalize_version() {
    case "$1" in
        ohm-*) normalized=$1 ;;
        *) normalized=ohm-$1 ;;
    esac

    printf '%s\n' "$normalized" | awk '
        NR == 1 && /^[o][h][m]-[0-9]+\.[0-9]+\.[0-9]+-[1-9][0-9]*$/ { valid = 1 }
        NR != 1 { invalid = 1 }
        END { exit invalid || !valid }
    ' || fail "invalid Ohm version: $1"

    printf '%s\n' "$normalized"
}

main() {
case "$#" in
    0) ;;
    1)
        [ "$1" = --help ] || fail "unrecognized option: $1"
        usage
        script_complete=true
        return 0
        ;;
    *) fail 'the release installer does not accept additional arguments' ;;
esac

case "$(uname -s)" in
    Darwin)
        case "$(uname -m)" in
            arm64|aarch64) host_target=aarch64-apple-darwin ;;
            x86_64)
                [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" = 1 ] ||
                    fail 'Intel macOS artifacts are not currently available'
                host_target=aarch64-apple-darwin
                ;;
            *) fail 'unsupported macOS architecture' ;;
        esac
        embedded_archive_sha256=$embedded_archive_sha256_aarch64_apple_darwin
        ;;
    Linux)
        case "$(uname -m)" in
            x86_64|amd64) host_target=x86_64-unknown-linux-gnu ;;
            *) fail 'only x86_64 Linux is currently supported' ;;
        esac
        if command -v ldd >/dev/null 2>&1 && ldd --version 2>&1 | grep -qi musl; then
            fail 'musl-based Linux distributions are not currently supported'
        fi
        embedded_archive_sha256=$embedded_archive_sha256_x86_64_unknown_linux_gnu
        ;;
    *) fail 'only macOS and Linux are currently supported' ;;
esac

command -v rustup >/dev/null 2>&1 || fail 'rustup is required to register the installed toolchain'
[ -n "${HOME:-}" ] || [ -n "${RUSTUP_HOME:-}" ] ||
    fail 'HOME or RUSTUP_HOME must be set to register the installed toolchain'

[ -n "$embedded_version" ] && [ -n "$embedded_archive_sha256" ] ||
    fail 'a release-specific installer with an embedded checksum is required'
version=$(normalize_version "$embedded_version")
printf '%s\n' "$embedded_archive_sha256" | awk '
    NR == 1 && length($0) == 64 && $0 ~ /^[[:xdigit:]]+$/ { valid = 1 }
    NR != 1 { invalid = 1 }
    END { exit invalid || !valid }
' || fail 'the embedded archive checksum is invalid'

download_url=${OHM_DOWNLOAD_URL:-https://labs.astral.sh/ohm/releases/$version}
case "$download_url" in
    https://*) command -v curl >/dev/null 2>&1 || fail 'curl is required to download Ohm' ;;
    file:///*) ;;
    *) fail 'OHM_DOWNLOAD_URL must use an HTTPS URL or an absolute file URL' ;;
esac

temporary_directory=$(mktemp -d "${TMPDIR:-/tmp}/ohm-installer.XXXXXXXX") ||
    fail 'could not create a temporary directory'

archive_name=$version-$host_target.tar.gz
archive_path=$temporary_directory/$archive_name
case "$download_url" in
    https://*)
        info "downloading $version for $host_target"
        curl_progress=--silent
        if [ -t 2 ]; then
            curl_progress=--progress-bar
        fi
        curl --fail "$curl_progress" --show-error --location \
            --retry 3 --retry-delay 1 \
            --proto '=https' --tlsv1.2 \
            --output "$archive_path" "${download_url%/}/$archive_name" ||
            fail 'could not download the public Ohm release archive'
        ;;
    file:///*)
        info "copying $version for $host_target"
        cp "${download_url#file://}/$archive_name" "$archive_path" ||
            fail 'could not copy the local Ohm release archive'
        ;;
esac
[ -f "$archive_path" ] || fail "archive not found: $archive_path"

if [ -z "$installation_prefix" ]; then
    [ -n "${HOME:-}" ] || fail 'HOME must be set when OHM_INSTALL_DIR is omitted'
    installation_prefix=${XDG_DATA_HOME:-"$HOME/.local/share"}/ohm/toolchains/$version
fi
while [ "$installation_prefix" != / ] && [ "${installation_prefix%/}" != "$installation_prefix" ]; do
    installation_prefix=${installation_prefix%/}
done

case "$installation_prefix" in
    /*) ;;
    *) fail 'OHM_INSTALL_DIR must be an absolute path' ;;
esac
case "$installation_prefix" in
    /|/Users|/home|/root|/usr|/usr/local|/var|/opt|/etc|/bin|/sbin|/private|/tmp|/private/tmp|"${HOME:-}"|"${HOME:-}/"|"${RUSTUP_HOME:-}"|"${CARGO_HOME:-}")
        fail 'refusing to install into a broad or managed directory'
        ;;
esac
printf '%s\n' "$installation_prefix" | awk '
    {
        count = split($0, components, "/")
        for (component_number = 1; component_number <= count; component_number++) {
            if (components[component_number] == "." || components[component_number] == "..") {
                exit 1
            }
        }
    }
' || fail 'OHM_INSTALL_DIR must not contain relative path components'

info 'verifying archive checksum'
if command -v sha256sum >/dev/null 2>&1; then
    actual_checksum=$(sha256sum "$archive_path" | awk '{ print tolower($1) }') ||
        fail 'could not calculate the archive checksum'
elif command -v shasum >/dev/null 2>&1; then
    actual_checksum=$(shasum -a 256 "$archive_path" | awk '{ print tolower($1) }') ||
        fail 'could not calculate the archive checksum'
else
    fail 'sha256sum or shasum is required to verify the archive checksum'
fi
[ "$actual_checksum" = "$embedded_archive_sha256" ] || fail 'archive checksum verification failed'

upstream_version=${version#ohm-}
upstream_version=${upstream_version%-*}
archive_root=rust-$upstream_version-dev-$host_target

info 'inspecting archive contents'
tar -tf "$archive_path" > "$temporary_directory/members" || fail 'could not inspect the archive'
awk -v expected_root="$archive_root" '
    {
        if ($0 == "" || substr($0, 1, 1) == "/" || index($0, "\\") != 0) {
            exit 1
        }
        count = split($0, components, "/")
        if (components[1] != expected_root) {
            exit 1
        }
        for (component_number = 1; component_number <= count; component_number++) {
            if (components[component_number] == ".." || components[component_number] == ".") {
                exit 1
            }
        }
        members++
    }
    END { if (members == 0) exit 1 }
' "$temporary_directory/members" || fail 'the archive contains unsafe or unexpected paths'
tar -tvf "$archive_path" > "$temporary_directory/member-details" ||
    fail 'could not inspect archive member types'
awk '
    substr($0, 1, 1) != "-" && substr($0, 1, 1) != "d" { exit 1 }
' "$temporary_directory/member-details" ||
    fail 'the archive contains symbolic links, hard links, or unsupported member types'

verify_installation() {
    installation_directory=$1
    for source_file in Cargo.toml core/src/lib.rs alloc/src/lib.rs std/src/lib.rs; do
        [ -s "$installation_directory/lib/rustlib/src/rust/library/$source_file" ] ||
            fail "installed standard-library source is missing or empty: $source_file"
    done
    for executable in rustc rustdoc cargo cargo-clippy clippy-driver rustfmt cargo-fmt; do
        executable_path=$installation_directory/bin/$executable
        [ -f "$executable_path" ] && [ -x "$executable_path" ] ||
            fail "installed tool is missing or not executable: $executable"

        if [ "$executable" = rustc ]; then
            compiler_version=$("$executable_path" --version) ||
                fail 'the installed Rust compiler did not start successfully'
            case "$compiler_version" in
                "rustc $upstream_version "*|"rustc $upstream_version-"*) ;;
                *) fail 'the installed Rust compiler has an unexpected upstream version' ;;
            esac
            case "$compiler_version" in
                *"($version)"*) ;;
                *) fail 'the installed Rust compiler has an unexpected Ohm release version' ;;
            esac
        else
            "$executable_path" --version >/dev/null 2>&1 ||
                fail "installed tool did not start successfully: $executable"
        fi
    done
    if [ "$host_target" = x86_64-unknown-linux-gnu ] && [ -n "$embedded_wild_version" ]; then
        wild_path=$installation_directory/lib/rustlib/$host_target/bin/wild-ld/ld.bfd
        [ -f "$wild_path" ] && [ -x "$wild_path" ] ||
            fail 'the bundled Wild linker is missing or not executable'
        wild_version=$("$wild_path" --version) ||
            fail 'the bundled Wild linker did not start successfully'
        case "$wild_version" in
            "Wild $embedded_wild_version"|"Wild $embedded_wild_version "*) ;;
            *) fail 'the bundled Wild linker has an unexpected version' ;;
        esac
    fi
}

if [ -e "$installation_prefix" ] || [ -L "$installation_prefix" ]; then
    [ -d "$installation_prefix" ] && [ ! -L "$installation_prefix" ] ||
        fail 'the installation prefix already exists and is not a real directory'
    [ -f "$installation_prefix/.ohm-version" ] ||
        fail 'the installation prefix already exists without Ohm version metadata'
    installed_version=$(sed -n '1p' "$installation_prefix/.ohm-version")
    [ "$installed_version" = "$version" ] ||
        fail 'the installation prefix contains a different Ohm version'
    verify_installation "$installation_prefix"
else
    prefix_parent=${installation_prefix%/*}
    [ -n "$prefix_parent" ] && [ "$prefix_parent" != / ] ||
        fail 'the installation prefix parent is unsafe'
    mkdir -p "$prefix_parent" || fail 'could not create the installation parent directory'
    staging_directory=$(mktemp -d "$prefix_parent/.ohm-install.XXXXXXXX") ||
        fail 'could not create an installation staging directory'
    extracted_directory=$temporary_directory/extracted
    mkdir -p "$extracted_directory"
    info 'extracting toolchain'
    tar --no-same-owner -xf "$archive_path" -C "$extracted_directory" ||
        fail 'could not extract the archive'
    inner_installer=$extracted_directory/$archive_root/install.sh
    [ -f "$inner_installer" ] && [ ! -L "$inner_installer" ] ||
        fail 'the archive does not contain a regular Rust installation script'
    staged_prefix=$staging_directory/toolchain
    info 'installing toolchain components'
    sh "$inner_installer" --prefix="$staged_prefix" --disable-ldconfig ||
        fail 'the Rust distribution installer failed'
    verify_installation "$staged_prefix"
    printf '%s\n' "$version" > "$staged_prefix/.ohm-version"

    mkdir "$installation_prefix" ||
        fail 'the installation prefix was created by another process'
    activated_prefix=$installation_prefix
    for staged_entry in "$staged_prefix"/* "$staged_prefix"/.[!.]* "$staged_prefix"/..?*; do
        [ -e "$staged_entry" ] || [ -L "$staged_entry" ] || continue
        mv "$staged_entry" "$installation_prefix/" ||
            fail 'could not activate the installed toolchain'
    done
    rmdir "$staged_prefix" || fail 'could not remove the empty staged toolchain'
    verify_installation "$installation_prefix"
    activated_prefix=
    rmdir "$staging_directory" || fail 'could not remove the empty installation staging directory'
    staging_directory=
fi

rustup_home=${RUSTUP_HOME:-"$HOME/.rustup"}
toolchains_directory=$rustup_home/toolchains
mkdir -p "$toolchains_directory" || fail 'could not create the rustup toolchains directory'

link_toolchain() {
    toolchain_name=$1
    case "$toolchain_name" in
        "$version"|ohm) ;;
        *) fail 'refusing to modify an unexpected rustup toolchain name' ;;
    esac
    link_path=$toolchains_directory/$toolchain_name

    if [ -L "$link_path" ]; then
        current_destination=$(cd "$link_path" 2>/dev/null && pwd -P) || current_destination=
        desired_destination=$(cd "$installation_prefix" && pwd -P) ||
            fail 'could not resolve the installed toolchain path'
        if [ "$current_destination" = "$desired_destination" ]; then
            return
        fi
        if [ "$toolchain_name" != ohm ]; then
            fail "refusing to replace an existing immutable rustup toolchain: $toolchain_name"
        fi
        alias_backup=$link_path.ohm-backup.$$
        [ ! -e "$alias_backup" ] && [ ! -L "$alias_backup" ] ||
            fail 'an existing rustup alias backup prevents safe replacement'
        mv "$link_path" "$alias_backup" ||
            fail 'could not preserve the previous custom rustup toolchain link'
    elif [ -e "$link_path" ]; then
        fail "refusing to replace an existing managed rustup toolchain: $toolchain_name"
    fi

    if ! rustup toolchain link "$toolchain_name" "$installation_prefix"; then
        if [ -n "$alias_backup" ]; then
            mv "$alias_backup" "$link_path" ||
                fail 'could not restore the previous custom rustup toolchain link'
            alias_backup=
        fi
        fail "could not register rustup toolchain: $toolchain_name"
    fi

    if [ -n "$alias_backup" ]; then
        rm -f "$alias_backup" || fail 'could not remove the previous rustup alias backup'
        alias_backup=
    fi
}

info 'registering toolchains with rustup'
link_toolchain "$version"
link_toolchain ohm

printf 'Installed %s at %s\n' "$version" "$installation_prefix"
printf '%s\n' 'Warning: Ohm is experimental; use it only for development iteration.'
printf 'Run: cargo +ohm --version\n'
script_complete=true
}

main "$@"
