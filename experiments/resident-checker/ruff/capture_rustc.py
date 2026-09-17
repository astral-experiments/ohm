#!/usr/bin/env python3
"""Capture this Ruff package's rustc commands, optionally enabling the resident graph."""

import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
manifest = Path(os.environ.get("CARGO_MANIFEST_DIR", ""))
if (
    manifest.parts[-2:] == ("crates", "ruff_python_parser")
    and "--crate-name" in arguments
):
    name = arguments[arguments.index("--crate-name") + 1]
    category = (
        "test"
        if "--test" in arguments
        else "lib"
        if name == "ruff_python_parser"
        else "bin"
    )
    if os.environ.get("OHM_RUFF_QUERY_GRAPH") == "1":
        arguments.append("-Zohm-resident-query-graph")
    capture = Path(os.environ["OHM_RUFF_CAPTURE"]) / f"{name}.{category}.json"
    capture.write_text(
        json.dumps(
            {
                "cwd": os.getcwd(),
                "argv": arguments,
                "env": {
                    key: value
                    for key, value in os.environ.items()
                    if key.startswith(("CARGO_PKG_", "CARGO_MANIFEST"))
                },
            },
            indent=2,
        )
        + "\n"
    )
os.execv(arguments[0], arguments)
