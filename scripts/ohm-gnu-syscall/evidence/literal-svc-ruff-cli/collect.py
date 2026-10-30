"""Retain original clocks and output records after reopening all native program bytes."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from paired_counts import ORIGINAL_QA, ORIGINAL_RUN, paired_stats, verify

API = "repos/astral-experiments/ohm/actions/"
GH = os.environ.get("GH_BIN") or shutil.which("gh-auto") or shutil.which("gh")


def get(path):
    return json.loads(subprocess.check_output([GH, "api", API + path]))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_file(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def tar_member(archive, name, data):
    info = tarfile.TarInfo(name)
    info.mode = 0o644
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def compact(z, verified):
    retained = {}
    body = io.BytesIO()
    with tarfile.open(fileobj=body, mode="w") as archive:
        for name in sorted(z.namelist()):
            if name.endswith("/") or name.startswith("paired/native-elf/chunks/"):
                continue
            if not name.startswith("paired/") and name != "candidate.json":
                continue
            wire = z.read(name)
            if name.endswith(".gz"):
                key, data = name[:-3] + ".raw", gzip.decompress(wire)
            else:
                key, data = name, wire
            retained[key] = [sha(wire), sha(data)]
            tar_member(archive, key, data)
        for name, value in (("original-members.json", retained), ("native-archive-readback.json", verified)):
            tar_member(archive, name, json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    return subprocess.check_output(["zstd", "-q", "-9", "-c"], input=body.getvalue()), len(retained)


def reopen(asset, i, order, out, run_id, head):
    assert asset["name"] == f"gnu-svc-holdout-{i}" and not asset["expired"]
    assert (asset["workflow_run"]["id"], asset["workflow_run"]["head_sha"]) == (run_id, head)
    with tempfile.TemporaryFile() as f:
        endpoint = API + f'artifacts/{asset["id"]}/zip'
        for attempt in range(5):
            f.seek(0)
            f.truncate()
            res = subprocess.run([GH, "api", endpoint], stdout=f, stderr=subprocess.PIPE)
            if res.returncode == 0:
                break
            if not any(t in res.stderr for t in (b"502", b"503", b"504")):
                raise RuntimeError(res.stderr.decode())
            time.sleep(15 * (attempt + 1))
        else:
            raise RuntimeError(res.stderr.decode())
        assert f.tell() == asset["size_in_bytes"]
        f.seek(0)
        digest = hashlib.file_digest(f, "sha256").hexdigest()
        assert "sha256:" + digest == asset["digest"]
        f.seek(0)
        with zipfile.ZipFile(f) as z:
            values = verify(z, order, True)
            checked = {"run": run_id, "head": head, "position": i, "artifact": asset["id"],
                       "size": asset["size_in_bytes"], "sha256": digest, "pair": values}
            blob, count = compact(z, checked)
    (out / "pairs" / f"{i:02}.tar.zst").write_bytes(blob)
    meta = {"position": i, "archive": asset["id"], "zip_bytes": asset["size_in_bytes"], "zip_sha256": digest,
            "retained_bytes": len(blob), "retained_sha256": sha(blob), "retained_originals": count}
    return meta, values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--run", type=int, default=ORIGINAL_RUN, help="the holdout workflow run to enroll")
    parser.add_argument("--head", default=ORIGINAL_QA, help="the complete QA commit used to dispatch that run")
    args = parser.parse_args()
    out = args.destination
    run = get(f"runs/{args.run}")
    assert run["id"] == args.run and run["head_sha"] == args.head and run["event"] == "workflow_dispatch"
    assert run["path"] == ".github/workflows/ci.yml"
    assert run["head_branch"] == "charlie/qa-gnu-ruff-syscall" and run["conclusion"] == "success"
    registered = json.loads((HERE / "registered-pairs.json").read_bytes())
    orders = registered["schedules"]["holdout"]
    assets = get(f"runs/{args.run}/artifacts?per_page=50")["artifacts"]
    by_name = {r["name"]: r for r in assets}
    assert len(assets) == len(by_name) == len(orders) == 12
    assert set(by_name) == {f"gnu-svc-holdout-{i}" for i in range(1, 13)}
    (out / "pairs").mkdir(parents=True, exist_ok=True)
    records, results = [], []
    for i, order in enumerate(orders, 1):
        meta, values = reopen(by_name[f"gnu-svc-holdout-{i}"], i, order, out, args.run, args.head)
        records.append(meta)
        results.append(values)
        print(f"Block {i}: complete native bytes and calibrated clocks agree", flush=True)
    json_file(out / "registration.json", {"run": args.run, "workflow": args.head, "pairs": records})
    json_file(out / "results.json", paired_stats(results, orders))
    for name in ("registered-pairs.json", "paired_counts.py", "verify.py"):
        shutil.copyfile(HERE / name, out / name)
    subprocess.run([sys.executable, "-IB", out / "verify.py", "--run", str(args.run), "--head", args.head],
                   check=True)


if __name__ == "__main__":
    main()
