#!/usr/bin/env bash
set -euo pipefail
unset PYTHONPATH PYTHONHOME PYTHONSAFEPATH VIRTUAL_ENV
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
exec /usr/bin/python3 -E -S "$(dirname "$0")/reproduce.py" "$@"
