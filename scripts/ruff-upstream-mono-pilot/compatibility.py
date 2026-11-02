"""Test real cross-version reads using the authenticated pair of factory installations."""
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ruff-indexed-check-pmu"))
from acquire import LOG, REG, ROOT, need

arms = json.loads((LOG / "compiler-installations.json").read_bytes())["arms"]
receipt, = [a for name, a in REG["factory_artifacts"].items() if name.endswith("-receipts")]
need(receipt[2].startswith("sha256:"), "unregistered factory receipt")
# The receiver must decline the previous compiler’s incremental file format in both directions.
subprocess.run([
    sys.executable, "-IB", HERE / "cross-version/cross_version.py",
    "--factory-receipts", ROOT / "factory-receipts.zip", "--expect-factory-sha256", receipt[2][7:],
    "--parent-sdk", arms["normal"]["root"], "--parent-commit", REG["compiler_parent"], "--parent-format", "26655",
    "--child-sdk", arms["defer"]["root"], "--child-commit", REG["compiler_candidate"], "--child-format", "24450",
    "--work", ROOT / "compat-work", "--out", LOG / "compatibility",
], check=True)
