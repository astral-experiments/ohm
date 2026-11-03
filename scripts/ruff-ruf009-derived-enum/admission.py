"""Admit the frozen physical source proof and the actual opaque-lifetime reader before any Cargo measurement."""

import argparse, hashlib, itertools, json, os, subprocess, sys, tempfile
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent


def read(p):
    return json.loads(p.read_bytes())


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", "repos/astral-experiments/ohm/" + path]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=("pilot", "confirmation"))
    a = p.parse_args()
    r = read(HERE / "registration.json")
    ga = r["native_admission"]
    n = read(HERE / "native-admission.json")
    assert (
        n["unique_cargo_commands"] == 314
        and n["terminal"] == ga["terminal"]
        and sha(HERE / "native-admission.json") == ga["independent"]
    )
    x = api("actions/runs/" + str(ga["run"]))
    assert (x["head_sha"], x["run_attempt"], x["conclusion"], x["event"]) == (
        ga["head"],
        1,
        "success",
        "workflow_dispatch",
    )
    artifact = api("actions/artifacts/" + str(ga["artifact"]))
    assert (
        artifact["workflow_run"]["id"] == ga["run"]
        and artifact["digest"] == "sha256:" + ga["zip"]
        and artifact["size_in_bytes"] == ga["bytes"]
    )
    orders = r["confirm_orders"]
    rank = r["allocation_uniform_rank_of_70"]
    first = list(itertools.combinations(range(8), 4))[rank]
    assert (
        orders == ["PC" if i in first else "CP" for i in range(8)]
        and len({r["qa_branch"], r["factory_branch"]}) == 2
    )
    if a.phase == "confirmation":
        return
    s = r["opaque_reader_controls"]
    row = api("actions/artifacts/" + str(s["artifact"]))
    assert (
        row["workflow_run"]["id"] == s["run"]
        and row["size_in_bytes"] == s["bytes"]
        and row["digest"] == "sha256:" + s["sha256"]
    )
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        original = root / "prior.zip"
        with original.open("xb") as out:
            subprocess.run(
                [
                    "gh",
                    "api",
                    "repos/astral-experiments/ohm/actions/artifacts/" + str(s["artifact"]) + "/zip",
                ],
                check=True,
                stdout=out,
            )
        assert sha(original) == s["sha256"]
        sys.path.insert(0, str(HERE))
        import opaque_selftest

        with zipfile.ZipFile(original) as z:
            for old, new, _, _ in opaque_selftest.CASES.values():
                for h in (old, new):
                    key = "members/" + h + ".rmeta.zst"
                    m = z.getinfo(key)
                    assert 0 < m.file_size < 24 << 20
                    (root / Path(key).name).write_bytes(z.read(key))
        subprocess.run(
            [
                sys.executable,
                "-IB",
                HERE / "opaque_selftest.py",
                root,
                Path(os.environ["RUNNER_TEMP"]) / "ruf009-opaque-controls.json",
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
