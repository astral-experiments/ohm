"""Expose only an already-qualified, source-sealed commit to actions/checkout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bindings

print("source_head=" + bindings.spec()["head"])
