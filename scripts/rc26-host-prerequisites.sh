#!/usr/bin/bash
set -euo pipefail

# The opening and its semantic witnesses require these literal paths.
tools=(/usr/bin/python3.12 /usr/bin/strace)

snapshot() {
    local label=$1 tool
    printf 'host-prerequisites %s\n' "$label"
    for tool in "${tools[@]}"; do
        if [[ -x $tool ]]; then
            printf 'executable %s\n' "$tool"
            /usr/bin/realpath -- "$tool" || :
            /usr/bin/sha256sum -- "$tool" || :
            "$tool" --version || :
        else
            printf 'missing-executable %s\n' "$tool"
        fi
    done
    /usr/bin/dpkg-query -W -f='${binary:Package}\t${db:Status-Abbrev}\t${Version}\t${Architecture}\n' python3.12 python3.12-minimal strace || :
}

# Keep both per-binary snapshots in the uploaded log, including a failed apt transaction.
trap 'status=$?; set +e; snapshot after; printf "host-prerequisites exit=%s\n" "$status"; exit "$status"' EXIT
snapshot before
source /etc/os-release
arch=$(/usr/bin/dpkg --print-architecture)
printf 'distribution %s %s %s %s\n' "$ID" "$VERSION_ID" "$VERSION_CODENAME" "$arch"
[[ $ID == ubuntu && $VERSION_ID == 24.04 && $VERSION_CODENAME == noble && $arch == amd64 ]] || {
    echo 'Expected the registered Ubuntu 24.04 amd64 runner' >&2; exit 1;
}

missing=()
# python3.12-minimal owns the interpreter; python3.12 provides its complete standard library.
if [[ ! -x ${tools[0]} ]]; then missing+=(python3.12-minimal python3.12); fi
if [[ ! -x ${tools[1]} ]]; then missing+=(strace); fi
if (( ${#missing[@]} )); then
    # Give apt only official Noble sources and an isolated index. No repository or durable
    # host apt-source configuration is edited; sudo is used only for these two apt commands.
    key=/usr/share/keyrings/ubuntu-archive-keyring.gpg
    [[ -r $key ]] || { echo "Missing distribution archive keyring: $key" >&2; exit 1; }
    /usr/bin/sha256sum "$key"
    tmp=$(/usr/bin/mktemp -d /tmp/uv-20991-apt.XXXXXXXX)
    /usr/bin/mkdir "$tmp/empty" "$tmp/lists"
    /usr/bin/printf '%s\n' \
        "deb [arch=amd64 signed-by=$key] https://archive.ubuntu.com/ubuntu noble main universe" \
        "deb [arch=amd64 signed-by=$key] https://archive.ubuntu.com/ubuntu noble-updates main universe" \
        "deb [arch=amd64 signed-by=$key] https://security.ubuntu.com/ubuntu noble-security main universe" > "$tmp/sources.list"
    /usr/bin/chmod 0755 "$tmp" "$tmp/empty" "$tmp/lists"
    /usr/bin/chmod 0644 "$tmp/sources.list"
    options=(-o "Dir::Etc::sourcelist=$tmp/sources.list" -o "Dir::Etc::sourceparts=$tmp/empty"
             -o "Dir::State::lists=$tmp/lists" -o 'Dir::Cache::pkgcache=' -o 'Dir::Cache::srcpkgcache='
             -o Acquire::AllowInsecureRepositories=false -o Acquire::AllowDowngradeToInsecureRepositories=false
             -o APT::Get::AllowUnauthenticated=false -o Acquire::Retries=1 -o Acquire::https::Timeout=15
             -o DPkg::Lock::Timeout=15 -o Dpkg::Use-Pty=0)
    printf 'Ubuntu packages requested:'; printf ' %s' "${missing[@]}"; printf '\n'
    /usr/bin/timeout --kill-after=10s 120s /usr/bin/sudo -n /usr/bin/apt-get "${options[@]}" -o APT::Update::Error-Mode=any update -qq
    /usr/bin/apt-cache "${options[@]}" policy "${missing[@]}"
    /usr/bin/timeout --kill-after=10s 120s /usr/bin/sudo -n /usr/bin/apt-get "${options[@]}" --yes --no-install-recommends --no-remove --reinstall install "${missing[@]}"
fi

for tool in "${tools[@]}"; do
    [[ -x $tool ]] || { echo "Required executable still unavailable: $tool" >&2; exit 1; }
done
"${tools[0]}" -ISB -c 'import sys; assert sys.version_info[:2] == (3, 12); print(sys.version)'
"${tools[1]}" --version
