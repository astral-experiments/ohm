#!/usr/bin/env python3
"""Capture the real doctest rustc command and its argument files before executing it."""

import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
capture = Path(os.environ["OHM_RUFF_CAPTURE"]) / f"doctest.{os.getpid()}.json"
argfiles = {
    value[1:]: Path(value[1:]).read_text()
    for value in arguments[1:]
    if value.startswith("@") and Path(value[1:]).is_file()
}
capture.write_text(
    json.dumps({"cwd": os.getcwd(), "argv": arguments, "argfiles": argfiles}, indent=2)
    + "\n"
)
os.execv(arguments[0], arguments)
