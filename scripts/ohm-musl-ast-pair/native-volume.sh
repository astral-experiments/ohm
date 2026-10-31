#!/usr/bin/env bash
# The original runner's SDK file and scratch directory returned different device IDs.
# Use one native, executable filesystem for the complete source kit, donors and test roots.
set -euo pipefail
out="$RUNNER_TEMP/musl-provider-evidence"
volume="$RUNNER_TEMP/musl-provider-volume"
mkdir -m 700 "$out" "$volume"
# Prefer the native filesystem the runner already provides if its actual regular files qualify.
if ! python3 -IB scripts/ohm-musl-ast-pair/provider_stage.py probe "$volume" "$out/storage.json"; then
    if sudo -n mount -t tmpfs -o size=6G,exec,nodev,nosuid,mode=0700 tmpfs "$volume"; then
        sudo -n chown "$(id -u):$(id -g)" "$volume"
    else
        volume=$(mktemp -d /dev/shm/ohm-musl-v2-XXXXXXXX)
    fi
    python3 -IB scripts/ohm-musl-ast-pair/provider_stage.py probe "$volume" "$out/storage.json"
fi
printf 'MUSL_GUARD_VOLUME=%s\nMUSL_GUARD_EVIDENCE=%s\n' "$volume" "$out" >> "$GITHUB_ENV"
