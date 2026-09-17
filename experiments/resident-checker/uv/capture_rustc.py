#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
if (
    "--crate-name" in arguments
    and arguments[arguments.index("--crate-name") + 1] == "uv_pep440"
):
    path = Path(os.environ["OHM_UV_CAPTURE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cwd": os.getcwd(),
                "argv": arguments,
                "env": {
                    k: v
                    for k, v in os.environ.items()
                    if k.startswith("CARGO_")
                    and k
                    not in {
                        "CARGO_HOME",
                        "CARGO_TARGET_DIR",
                        "CARGO_BUILD_BUILD_DIR",
                        "CARGO_MAKEFLAGS",
                    }
                },
            },
            indent=2,
        )
        + "\n"
    )
os.execv(arguments[0], arguments)
