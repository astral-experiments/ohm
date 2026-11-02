"""Verify actual async-drop providers and relocations using both authenticated SDKs."""
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
for role, label, commit in (("P", "normal", REG["compiler_parent"]), ("C", "defer", REG["compiler_candidate"])):
    arm = arms[label]
    driver, = [v for k, v in arm["files"].items() if k.startswith("lib/librustc_driver-") and k.endswith(".so")]
    subprocess.run([
        sys.executable, "-IB", HERE / "async-provider/verify_async.py",
        "--shared-fixture", HERE / "providers", "--sdk-root", arm["root"], "--expect-commit", commit,
        "--expect-driver-sha256", driver, "--factory-receipts", ROOT / "factory-receipts.zip",
        "--expect-factory-sha256", receipt[2][7:], "--work", ROOT / "async-work", "--out", LOG / ("async-" + role),
    ], check=True)
