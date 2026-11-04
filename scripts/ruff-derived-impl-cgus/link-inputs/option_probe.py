"""Read Cargo's effective tri-state on its normal external subcommand boundary."""

import os
import subprocess
from pathlib import Path


def probe(root, cwd, env):
    root = Path(root)
    root.mkdir()
    helper = root / "cargo-ohm-native-link-option-observer"
    helper.write_text("""#!/bin/sh
printf '%s\\n' "${__CARGO_RELINK_ONLY-UNSET}" "${__CARGO_OHM_DEFAULTS-UNSET}"
""")
    helper.chmod(0o700)
    result = {}
    for key, extra in [
        ("default", []),
        ("yes", ["-Zrelink-only=yes"]),
        ("no", ["-Zrelink-only=no"]),
    ]:
        cmd = ["cargo", "+ohm", *extra, "ohm-native-link-option-observer"]
        ran = subprocess.run(
            cmd,
            cwd=cwd,
            env=env | {"PATH": str(root) + os.pathsep + env["PATH"]},
            capture_output=True,
            check=True,
            timeout=30,
        )
        data = ran.stdout.decode().splitlines()
        if len(data) != 2 or ran.stderr or (key != "default" and data[0] != key):
            raise RuntimeError(
                (
                    "different registered Cargo subcommand transport",
                    key,
                    ran.stdout,
                    ran.stderr,
                )
            )
        result[key] = {
            "args": cmd,
            "inherited_relink_only": data[0],
            "inherited_ohm_defaults": data[1],
        }
    return result
