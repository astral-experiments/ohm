#!/usr/bin/env bash
# Run both target classifications with the same already-installed GNU distribution.
set -euo pipefail
umask 077
case "$OHM_TARGET:$RUNNER_OS" in x86_64-unknown-linux-gnu:Linux) ;; *) exit 2 ;; esac
test "$(id -u)" != 0
report="$RUNNER_TEMP/rc23-final-reports/cross"
mkdir -m 700 "$report"
exec > >(tee "$report/runner.log") 2>&1
suite="$GITHUB_WORKSPACE/qa-code/scripts/rc23-final-installed/cross"
(cd "$suite" && sha256sum --strict --check OPERATIONS.sha256) > "$report/fixture-checksums.txt"
catalog="$RUNNER_TEMP/rc23-final-reports/original-gnu-catalog.json"
id="$(jq -er '.id | select(type=="number" and .>0)' "$catalog")"
official="$RUNNER_TEMP/rc23-original/$id.zip"
test -f "$official" && test ! -L "$official"
test "$(stat -c %s "$official")" = "$(jq -r .size_in_bytes "$catalog")"
cd "$RUNNER_TEMP"
if ! command -v qemu-aarch64 >/dev/null && ! command -v qemu-aarch64-static >/dev/null; then
    sudo -n apt-get update -qq
    sudo -n apt-get install --no-install-recommends -y qemu-user
fi
clang_bin="$(command -v clang)"
qemu_bin="$(command -v qemu-aarch64 || command -v qemu-aarch64-static)"
{
    "$qemu_bin" --version
    "$clang_bin" --version
    "$clang_bin" -print-targets
    sha256sum "$(readlink -f "$qemu_bin")" "$(readlink -f "$clang_bin")"
    dpkg-query -S "$qemu_bin" || dpkg-query -S "$(readlink -f "$qemu_bin")"
} > "$report/native-tools.txt"
grep -Eq '^ *aarch64[[:space:]]+-' "$report/native-tools.txt"
ram="$RUNNER_TEMP/rc23-cross-ram"
mkdir -m 700 "$ram"
sudo -n mount -t tmpfs -o "size=768m,nodev,nosuid,uid=$(id -u),gid=$(id -g),mode=700" tmpfs "$ram"
finish() {
    local outcome=$? escrow=0
    set +e
    printf '%s\n' "$outcome" > "$report/exit-code"
    if [[ -d "$ram/case" ]]; then
        # Keep every command, provider, compiler output and ELF, including a partial target.
        tar --one-file-system --sparse -C "$ram" -czf "$report/original.tar.gz" case \
            && (cd "$report" && sha256sum original.tar.gz > SHA256SUMS) || escrow=1
    fi
    sudo -n umount -- "$ram" || escrow=1
    if (( outcome != 0 )); then exit "$outcome"; fi
    exit "$escrow"
}
trap finish EXIT
findmnt -T "$ram" -o TARGET,SOURCE,FSTYPE,OPTIONS > "$report/mount.txt"
python3 -ISB "$suite/check.py" preflight > "$report/source-preflight.json"
python3 -ISB "$suite/check.py" run --target both --catalog "$catalog" --official "$official" \
    --sdk "$RUNNER_TEMP/rc23-candidate/sdk" --rustup "$(command -v rustup)" \
    --rustup-home "$RUNNER_TEMP/rc23-candidate/rustup" --work "$ram/case"
