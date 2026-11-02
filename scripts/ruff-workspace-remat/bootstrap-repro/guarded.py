import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guards

p = Path.cwd()
name = sys.argv[1]
limits = {"effective": 8 << 30, "work": 512 << 20}
initial = guards.resources(p, p)
minimum = {k: initial[k] for k in limits}
assert all(initial[k] >= b for k, b in limits.items()), initial
refusal = None
with (
    (p / (name + ".stdout")).open("ab") as out,
    (p / (name + ".stderr")).open("ab") as err,
):
    child = subprocess.Popen(
        sys.argv[2:], start_new_session=True, stdout=out, stderr=err
    )
    try:
        while child.poll() is None:
            sample = guards.resources(p, p)
            minimum = {k: min(minimum[k], sample[k]) for k in limits}
            if any(sample[k] < b for k, b in limits.items()):
                refusal = sample
                os.killpg(child.pid, signal.SIGTERM)
                break
            time.sleep(0.15)
    finally:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
(p / (name + ".resources.json")).write_text(
    json.dumps(
        {
            "initial": initial,
            "minimum": minimum,
            "refusal": refusal,
            "exit": child.returncode,
        },
        indent=2,
    )
    + "\n"
)
print(name, child.returncode, minimum, refusal)
sys.exit(1 if refusal else child.returncode)
