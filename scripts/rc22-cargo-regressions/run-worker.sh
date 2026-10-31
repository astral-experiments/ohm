#!/usr/bin/env bash
set -euo pipefail
suite=$1
d="$(realpath "$(dirname "$0")")"
orig="$(realpath "$RUNNER_TEMP")"
workparent="$orig"
proof="$orig/rc22-proof"
kit="$orig/rc22-kit"
role_root="$kit/installed"
owned=
nonce=

# Copy only the worker's packet, including partial output. Drop only the freshly
# allocated case on the Namespace volume after its original receipts have been copied.
finish() {
    rc=$?
    trap - EXIT
    set +e
    copy_status=0
    printf '%d\n' "$rc" > "$proof/worker.exit"
    if [[ -n "$workparent" && -d "$workparent/rc22-regression/packet" ]]; then
        sudo cp -a --no-dereference "$workparent/rc22-regression/packet" "$proof/packet"
        copy_status=$?
        if (( copy_status == 0 )); then sudo chown -hR "$(id -u):$(id -g)" "$proof/packet"; copy_status=$?; fi
        if (( rc == 0 && copy_status != 0 )); then rc=$copy_status; fi
    elif (( rc == 0 )); then
        rc=1
    fi
    if [[ -n "$owned" && -n "$nonce" && "$copy_status" == 0 ]]; then
        if python3 -IB "$d/task_dir.py" drop "$workparent" "$owned" "$nonce" >>"$proof/owned-directory.log" 2>&1; then
            sudo -n rmdir -- "$workparent" || rc=1
        else
            rc=1
        fi
    fi
    printf '%d\n' "$rc" > "$proof/carrier.exit"
    exit "$rc"
}
trap finish EXIT
test ! -e "$proof/packet"
test -f "$kit/qualified.json"
test -z "${GH_TOKEN:-}" && test -z "${GITHUB_TOKEN:-}"
test "$(uname -sm)" = "Linux x86_64"
cat /proc/sys/kernel/random/boot_id > "$proof/boot.txt"
uname -a > "$proof/uname.txt"
id > "$proof/user.txt"
printf '%s\n' "$GITHUB_SHA" "$GITHUB_RUN_ID" "$GITHUB_RUN_ATTEMPT" "$GITHUB_JOB" "$suite" > "$proof/current-run.txt"
if [[ "$suite" == ruff-recovery ]]; then
    test "$(nproc)" -ge 16
    # This is the actual second ext4 device used by the two witnessed 16-CPU
    # jobs. The runner root is commonly overlay. Never reuse another target.
    findmnt -n -o SOURCE,TARGET,FSTYPE,OPTIONS -T /cache > "$proof/cache-filesystem.txt"
    df -B1 /cache > "$proof/cache-space.txt"
    test "$(findmnt -n -o FSTYPE -T /cache)" = ext4
    test "$(findmnt -n -o TARGET -T /cache)" = /cache
    test "$(df -B1 --output=avail /cache | tail -1)" -ge $((42*1024**3))
    workparent="$(sudo -n mktemp -d "/cache/ohm-rc22-recovery-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT-XXXXXXXX")"
    sudo -n chown "$(id -u):$(id -g)" "$workparent"
    nonce="$(cat /proc/sys/kernel/random/uuid)"
    owned="$(python3 -IB "$d/task_dir.py" claim "$workparent" '' "$nonce")"
    printf '%s %s %s\n' "$workparent" "$owned" "$nonce" > "$proof/owned-directory.log"
    command=(python3 -IB "$d/ruff_recovery.py" "$workparent/rc22-regression")
else
    case "$suite" in shared|late|private|private-fallback) ;; *) exit 2 ;; esac
    command=(python3 -IB "$d/native_mounts.py" outer "$suite" "$workparent/rc22-regression" "$GITHUB_WORKSPACE/shared" "$GITHUB_WORKSPACE/private")
fi
findmnt -n -o SOURCE,TARGET,FSTYPE,OPTIONS -T "$workparent" > "$proof/filesystem.txt"
df -B1 "$workparent" > "$proof/filesystem-before.txt"
command+=("$role_root/sdk" "$role_root/roles/pinned/cargo" "$role_root/roles/fourfix/cargo" "$kit/registration.json")
printf '%s\0' "${command[@]}" > "$proof/argv.nul"
RUNNER_TEMP="$workparent" "${command[@]}" >"$proof/worker.stdout" 2>"$proof/worker.stderr" || { rc=$?; tail -c 3000 "$proof/worker.stderr" >&2; exit "$rc"; }
test -s "$workparent/rc22-regression/packet/complete.json"
df -B1 "$workparent" > "$proof/filesystem-after.txt"
