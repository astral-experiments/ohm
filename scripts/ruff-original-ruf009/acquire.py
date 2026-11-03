"""Reopen the same authenticated SDK on each fresh historical Ruff worker."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ruff-ruf009-derived-enum"))
import case
case.w.BRANCH = "charlie/qa-ruf009-historical-check-20261103"
case.ROOT.mkdir()
case.BASE.mkdir()
case.w.checked_head()
config = json.loads((case.HERE / "factory.json").read_text())
kit = case.old.scope_matched.kit("ruf009", config)
opened = Path(kit["arms"]["normal"]["root"]).parent
assert Path(kit["arms"]["defer"]["root"]).parent == opened
assert json.loads((opened / "rustcs.json").read_text()) == kit
study = Path(os.environ["RUNNER_TEMP"]) / "ohm-original-ruf009"
study.mkdir()
(study / "sdk.json").write_text(json.dumps({"directory": str(opened), "factory": config}) + "\n")
