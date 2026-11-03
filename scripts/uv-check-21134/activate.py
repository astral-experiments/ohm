"""Materialize the same four-placement measurement workflow only from admitted production originals."""

from pathlib import Path
import argparse, os, sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, require, read, sha
from host import payload
from media import enroll, authorize

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("original_run_directory", type=Path)
ap.add_argument("qualified_directory", type=Path)
if __name__ == "__main__":
    a = ap.parse_args()
    payload()
    workflow = HERE.parents[1] / ".github/workflows/ci.yml"
    future = HERE / "G-qualified-lock.json"
    require(not future.exists() and "false && (" in workflow.read_text(), "already activated or modified")
    enroll(a.original_run_directory, a.qualified_directory, future)
    authorize(read(future))
    with (workflow.parent / "ci.yml.reviewed-next").open("xb") as out:
        out.write((HERE / "workflow-enabled.yml").read_bytes())
    os.replace(workflow.parent / "ci.yml.reviewed-next", workflow)
    print(sha(future), sha(workflow))
