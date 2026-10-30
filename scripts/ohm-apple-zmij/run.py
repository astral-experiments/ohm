"""Run only bundled, reviewed modules even when the caller enforces Python's safe-path mode."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    directory = Path(__file__).resolve().parent
    allowed = {"admit", "calibrate", "cohort", "host", "pilot", "prepare", "test_protocol", "verbs", "verify"}
    if len(sys.argv) < 2 or sys.argv[1] not in allowed:
        raise SystemExit("select one of " + ", ".join(sorted(allowed)))
    file = directory / (sys.argv[1] + ".py")
    sys.path.insert(0, str(directory))
    sys.argv = [str(file), *sys.argv[2:]]
    runpy.run_path(str(file), run_name="__main__")
