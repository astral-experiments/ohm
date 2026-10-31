#!/usr/bin/env bash
set -euo pipefail
# Sourcing lets the separate real worktree control use the same successful install
# before the original script's EXIT trap removes its private directory.
exec 3>"$OHM_QA_RECEIPTS/commands.raw"
export BASH_XTRACEFD=3
PS4='+QA ${BASH_SOURCE[0]:-none}:${LINENO}: '
set -x
source "$1" "$2" ohm-1.99.0-22 "$OHM_QA_TARGET" 0d76dc1f4fe7ffb86ee5e1a8a9cc4d6bef1d1bf6
set +x
printf '%s\n' 0 >"$OHM_QA_RECEIPTS/release-shell.exit"
"$OHM_QA_PY" -IB "$OHM_QA_TOOLS/installed.py" final "$toolchain_root"
"$OHM_QA_PY" -IB "$OHM_QA_TOOLS/payloads.py" "$smoke_root" "$OHM_QA_RECEIPTS"
"$OHM_QA_PY" -IB "$OHM_QA_TOOLS/worktree.py" "$toolchain_root" "$smoke_root" "$OHM_QA_RECEIPTS"
