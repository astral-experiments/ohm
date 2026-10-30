"""Independently read the public adapter's terminal native records and raw Callgrind files."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = "astral-experiments/ohm"
NAME = "public-versioned-gnu-counter-raw"
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()


def api(endpoint):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/{endpoint}"]))


def main(run, commit, root):
    assert os.environ["GITHUB_REPOSITORY"] == REPO and run.isdigit() and len(commit) == 40
    wf = api(f"actions/runs/{run}")
    assert wf["head_sha"] == commit and wf["run_attempt"] == 1 and wf["event"] == "workflow_dispatch"
    root.mkdir(parents=True)
    rows = api(f"actions/runs/{run}/artifacts?per_page=100")["artifacts"]
    row, = [a for a in rows if a["name"] == NAME and not a["expired"]]
    digest = row["digest"].removeprefix("sha256:")
    assert len(digest) == 64 and 0 < row["size_in_bytes"] < 256 * 2**20
    original = root / "reviewer.zip"
    with original.open("xb") as f:
        subprocess.run(["gh", "api", f"repos/{REPO}/actions/artifacts/{row['id']}/zip"], stdout=f, check=True)
    assert original.stat().st_size == row["size_in_bytes"] and sha(original) == digest
    output = root / "verified"
    output.mkdir()
    for script, name in (("reopen_native.py", "native.json"), ("reopen_counter.py", "counter.json")):
        subprocess.run([sys.executable, "-IB", HERE / script, original, "--output", output / name], check=True)
    native, counted = (json.loads((output / n).read_bytes()) for n in ("native.json", "counter.json"))
    assert native["role"] == counted["role"] == "V"
    assert native["source"] == counted["source"] == "8f42a1c11e66c2a55299914d5025e4fa7549ead4"
    assert native["raw_terminal"] == counted["native_terminal"] and counted["formal_observations"] == 0
    receipt = {"run": int(run), "QA": commit, "raw_artifact": [row["id"], row["size_in_bytes"], digest],
               "counter_projection": sha(output / "counter.json"), "native_projection": sha(output / "native.json"),
               "counter_program": sha(HERE / "count_ir.py"), "counter_reader": sha(HERE / "reopen_counter.py"),
               "not_in_primary": True}
    (output / "qualified.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(receipt)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
