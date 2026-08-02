#!/bin/sh
set -eu

repository=astral-sh/ohm
embedded_version=
embedded_archive_sha256=
requested_version=
archive_path=
checksums_path=
installation_prefix=
workflow_run=
install_alias=true
temporary_directory=
staging_directory=
activated_prefix=
alias_backup=
script_complete=false

fail() {
    printf 'ohm: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf '%s\n' \
        'Usage: install.sh [--version VERSION] [--run RUN_ID]' \
        '                  [--archive PATH --checksums PATH] [--prefix PATH] [--no-alias]' \
        '' \
        'Install an Ohm macOS Apple Silicon toolchain.' \
        'Use --run RUN_ID to install a private GitHub Actions build artifact.' \
        'Without --run or --archive, install the latest public GitHub release.'
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

require_argument() {
    [ "$#" -ge 2 ] || fail "$1 requires an argument"
}

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
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version)
            require_argument "$@"
            requested_version=$2
            shift 2
            ;;
        --archive)
            require_argument "$@"
            archive_path=$2
            shift 2
            ;;
        --checksums)
            require_argument "$@"
            checksums_path=$2
            shift 2
            ;;
        --prefix)
            require_argument "$@"
            installation_prefix=$2
            shift 2
            ;;
        --run)
            require_argument "$@"
            workflow_run=$2
            shift 2
            ;;
        --no-alias)
            install_alias=false
            shift
            ;;
        --help|-h)
            usage
            script_complete=true
            return 0
            ;;
        *) fail "unrecognized option: $1" ;;
    esac
done

[ "$(uname -s)" = Darwin ] || fail 'only macOS is currently supported'
case "$(uname -m)" in
    arm64|aarch64) host_target=aarch64-apple-darwin ;;
    x86_64)
        [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" = 1 ] ||
            fail 'Intel macOS artifacts are not currently available'
        host_target=aarch64-apple-darwin
        ;;
    *) fail 'unsupported macOS architecture' ;;
esac

command -v rustup >/dev/null 2>&1 || fail 'rustup is required to register the installed toolchain'
[ -n "${HOME:-}" ] || [ -n "${RUSTUP_HOME:-}" ] ||
    fail 'HOME or RUSTUP_HOME must be set to register the installed toolchain'

version=
if [ -n "$requested_version" ]; then
    version=$(normalize_version "$requested_version")
fi
if [ -n "$embedded_version" ]; then
    release_version=$(normalize_version "$embedded_version")
    [ -z "$version" ] || [ "$version" = "$release_version" ] ||
        fail 'requested Ohm version does not match the embedded release version'
    version=$release_version
fi
if [ -n "$embedded_archive_sha256" ]; then
    printf '%s\n' "$embedded_archive_sha256" | awk '
        NR == 1 && length($0) == 64 && $0 ~ /^[[:xdigit:]]+$/ { valid = 1 }
        NR != 1 { invalid = 1 }
        END { exit invalid || !valid }
    ' || fail 'the embedded archive checksum is invalid'
fi

if [ -n "$workflow_run" ]; then
    printf '%s\n' "$workflow_run" | awk '
        NR == 1 && /^[0-9]+$/ { valid = 1 }
        NR != 1 { invalid = 1 }
        END { exit invalid || !valid }
    ' ||
        fail 'GitHub Actions run IDs must contain only digits'
    [ -z "$archive_path" ] && [ -z "$checksums_path" ] ||
        fail '--run cannot be combined with --archive or --checksums'
    command -v gh >/dev/null 2>&1 || fail 'GitHub CLI is required for private Actions artifacts'
elif [ -n "$archive_path" ] || [ -n "$checksums_path" ]; then
    [ -n "$archive_path" ] && [ -n "$checksums_path" ] ||
        fail '--archive and --checksums must be provided together'
    [ -n "$version" ] || fail '--archive requires --version'
else
    command -v curl >/dev/null 2>&1 || fail 'curl is required to download public Ohm releases'
fi

temporary_directory=$(mktemp -d "${TMPDIR:-/tmp}/ohm-installer.XXXXXXXX") ||
    fail 'could not create a temporary directory'

if [ -n "$workflow_run" ]; then
    download_directory=$temporary_directory/download
    mkdir -p "$download_directory"

    if [ -n "$version" ]; then
        GH_PROMPT_DISABLED=1 gh run download "$workflow_run" \
            --repo "$repository" \
            --name "$version-$host_target" \
            --dir "$download_directory" ||
            fail 'could not download the private GitHub Actions artifact; check GitHub authentication'
    else
        GH_PROMPT_DISABLED=1 gh run download "$workflow_run" \
            --repo "$repository" \
            --pattern "*-$host_target" \
            --dir "$download_directory" ||
            fail 'could not download the private GitHub Actions artifact; check GitHub authentication'
    fi

    archive_candidates=$temporary_directory/archive-candidates
    find "$download_directory" -type f -name "ohm-*-$host_target.tar.xz" -print \
        > "$archive_candidates"
    archive_count=$(awk 'END { print NR }' "$archive_candidates")
    [ "$archive_count" -eq 1 ] ||
        fail 'the workflow artifact must contain exactly one matching Ohm archive'
    archive_path=$(sed -n '1p' "$archive_candidates")
    archive_name=${archive_path##*/}
    inferred_version=${archive_name%-"$host_target".tar.xz}
    inferred_version=$(normalize_version "$inferred_version")

    if [ -n "$version" ]; then
        [ "$version" = "$inferred_version" ] ||
            fail 'workflow archive version does not match the requested version'
    else
        version=$inferred_version
    fi

    checksums_path=${archive_path%/*}/SHA256SUMS
    [ -f "$checksums_path" ] || fail 'the workflow artifact does not include SHA256SUMS'
elif [ -z "$archive_path" ]; then
    if [ -z "$version" ]; then
        release_metadata=$temporary_directory/latest-release.json
        curl --fail --silent --show-error --location \
            --retry 3 --retry-delay 1 \
            --proto '=https' --tlsv1.2 \
            --output "$release_metadata" \
            "https://api.github.com/repos/$repository/releases/latest" ||
            fail 'could not retrieve the latest public Ohm release'

        release_tag=$(awk '
            /"tag_name"[[:space:]]*:/ {
                tag = $0
                sub(/^.*"tag_name"[[:space:]]*:[[:space:]]*"/, "", tag)
                sub(/".*$/, "", tag)
                print tag
                found = 1
                exit
            }
            END { if (!found) exit 1 }
        ' "$release_metadata") || fail 'the latest release metadata does not contain a valid tag'
        version=$(normalize_version "$release_tag")
    fi

    archive_name=$version-$host_target.tar.xz
    archive_path=$temporary_directory/$archive_name
    release_url=https://github.com/$repository/releases/download/$version

    curl --fail --silent --show-error --location \
        --retry 3 --retry-delay 1 \
        --proto '=https' --tlsv1.2 \
        --output "$archive_path" "$release_url/$archive_name" ||
        fail 'could not download the public Ohm release archive'
    if [ -z "$embedded_archive_sha256" ]; then
        checksums_path=$temporary_directory/SHA256SUMS
        curl --fail --silent --show-error --location \
            --retry 3 --retry-delay 1 \
            --proto '=https' --tlsv1.2 \
            --output "$checksums_path" "$release_url/SHA256SUMS" ||
            fail 'could not download the public Ohm release checksums'
    fi
fi

[ -f "$archive_path" ] || fail "archive not found: $archive_path"
if [ -z "$embedded_archive_sha256" ] || [ -n "$checksums_path" ]; then
    [ -f "$checksums_path" ] || fail "checksums not found: $checksums_path"
fi
archive_name=${archive_path##*/}

if [ -z "$installation_prefix" ]; then
    [ -n "${HOME:-}" ] || fail 'HOME must be set when --prefix is omitted'
    installation_prefix=${XDG_DATA_HOME:-"$HOME/.local/share"}/ohm/toolchains/$version
fi
while [ "$installation_prefix" != / ] && [ "${installation_prefix%/}" != "$installation_prefix" ]; do
    installation_prefix=${installation_prefix%/}
done

case "$installation_prefix" in
    /*) ;;
    *) fail '--prefix must be an absolute path' ;;
esac
case "$installation_prefix" in
    /|/Users|/private|/tmp|/private/tmp|"${HOME:-}"|"${HOME:-}/"|"${RUSTUP_HOME:-}"|"${CARGO_HOME:-}")
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
' || fail '--prefix must not contain relative path components'

if [ -n "$checksums_path" ]; then
    expected_checksum=$(awk -v wanted="$archive_name" '
    {
        checksum = $1
        filename = $0
        sub(/^[^[:space:]]+[[:space:]]+\*?/, "", filename)
        if (filename == wanted) {
            if (length(checksum) != 64 || checksum !~ /^[[:xdigit:]]+$/) {
                invalid = 1
            }
            count++
            match_checksum = tolower(checksum)
        }
    }
    END {
        if (invalid || count != 1) {
            exit 1
        }
        print match_checksum
    }
' "$checksums_path") || fail 'the checksum manifest has no unique valid entry for the archive'
else
    expected_checksum=$embedded_archive_sha256
fi
if [ -n "$embedded_archive_sha256" ]; then
    [ "$expected_checksum" = "$embedded_archive_sha256" ] ||
        fail 'the checksum manifest does not match the embedded archive checksum'
fi
actual_checksum=$(shasum -a 256 "$archive_path" | awk '{ print tolower($1) }') ||
    fail 'could not calculate the archive checksum'
[ "$actual_checksum" = "$expected_checksum" ] || fail 'archive checksum verification failed'

upstream_version=${version#ohm-}
upstream_version=${upstream_version%-*}
archive_root=rust-$upstream_version-dev-$host_target

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
    for executable in rustc cargo cargo-clippy clippy-driver rustfmt cargo-fmt; do
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
    tar -xf "$archive_path" -C "$extracted_directory" || fail 'could not extract the archive'
    inner_installer=$extracted_directory/$archive_root/install.sh
    [ -f "$inner_installer" ] && [ ! -L "$inner_installer" ] ||
        fail 'the archive does not contain a regular Rust installation script'
    staged_prefix=$staging_directory/toolchain
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

link_toolchain "$version"
if [ "$install_alias" = true ]; then
    link_toolchain ohm
fi

printf 'Installed %s at %s\n' "$version" "$installation_prefix"
if [ "$install_alias" = true ]; then
    printf 'Run: cargo +ohm --version\n'
else
    printf 'Run: cargo +%s --version\n' "$version"
fi
script_complete=true
}

main "$@"
