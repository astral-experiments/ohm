"""Run the secondary content census after the structural ledger has closed."""

import subprocess
import sys
from pathlib import Path
from bindings import need, save, sha

HERE = Path(__file__).resolve().parent


def collect(work, where):
    need(
        where.parent.parent.name == "structural"
        and where.parent.name in ("Fon", "Kon")
        and where.name in ("first-B", "return-B"),
        "off-window content witness",
    )
    tool = HERE / "object_equality.py"
    need(
        sha(tool) == "ea6526bd3466552797cd0e003ec0c831a78c4fb560d483c72b42e8d55a36685d",
        "unexpected object comparator",
    )
    cmd = [
        sys.executable,
        "-IB",
        tool,
        "--target",
        work / "target",
        "--build",
        work / "build",
        "--cold-ledger",
        where.parent / "cold-A/path-inodes.json.gz",
        "--ledger",
        where / "path-inodes.json.gz",
        "--out",
        where / "object-equality.json.gz",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    (where / "object-equality.stdout").write_bytes(proc.stdout)
    (where / "object-equality.stderr").write_bytes(proc.stderr)
    save(
        where / "object-equality-status.json",
        dict(
            exit=proc.returncode,
            source=sha(tool),
            argv=list(map(str, cmd)),
            scope="independent structural-only native object comparison",
            eligible=proc.returncode == 0,
            required_for_pmu=False,
        ),
    )
