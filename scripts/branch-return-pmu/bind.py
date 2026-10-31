"""Expose only an already-qualified, source-sealed commit to actions/checkout."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bindings
import link_diagnostic

link_diagnostic.spec(json.loads(link_diagnostic.FILE.read_bytes()))
print("source_head=" + bindings.spec()["head"])
